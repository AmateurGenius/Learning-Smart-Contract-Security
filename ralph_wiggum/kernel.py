"""Kernel loop for orchestrating agent execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from ralph_wiggum.agents.graph_analysis import GraphAnalysis
from ralph_wiggum.agents.llm_synthesis import LLMSynthesis
from ralph_wiggum.agents.proof_agent import ProofAgent
from ralph_wiggum.agents.repair_agent import RepairAgent
from ralph_wiggum.agents.solodit import SoloditSignalBooster
from ralph_wiggum.agents.static_scan import StaticScan
from ralph_wiggum.budget import Budget
from ralph_wiggum.invariants import validate_state
from ralph_wiggum.killswitch import KillSwitch
from ralph_wiggum.reporting import ReportGenerator
from ralph_wiggum.scoring import collect_findings
from ralph_wiggum.state import StateStore
from ralph_wiggum.agents.fuzz_agent import FuzzAgent
from ralph_wiggum.tools.foundry_runner import FoundryRunner
from ralph_wiggum.tools.quick_linter import QuickLinterRunner
from ralph_wiggum.tools.runner_pool import RunnerPool
from ralph_wiggum.tools.slither_runner import SlitherRunner


@dataclass
class Kernel:
    """Core orchestrator that will run the multi-agent audit loop."""

    state_store: StateStore
    artifacts_dir: Path = Path("artifacts")
    budget: Budget | None = None
    kill_switch: KillSwitch | None = None
    parallel_tools: bool = False
    slither_runner: SlitherRunner | None = None
    quick_linters: list[QuickLinterRunner] = field(default_factory=list)
    offline_fixtures: bool = False
    fixtures_dir: Path | None = None

    def run(self, target_path: str) -> Path:
        """Run the kernel loop for a given target path."""
        if self.budget is None:
            self.budget = Budget()
        if self.kill_switch is None:
            self.kill_switch = KillSwitch()
        self.state_store.ensure_state_file()

        state = self.state_store.load()
        state.setdefault("status", "running")
        state.setdefault("capabilities", {"executed": {}, "skipped": {}})
        state.setdefault("budget", {"spent": 0, "cap": 0})
        state["target_path"] = target_path
        self.state_store.save(state)

        errors = validate_state(state)
        if errors:
            return self._handle_invariant_failure(state, errors)

        agent_queue = state.get("agent_queue", [])
        for agent in agent_queue:
            self._record_capability_executed(
                state,
                agent,
                status="queued",
                started_at=self._now_iso(),
                finished_at=self._now_iso(),
                artifact_paths=[],
            )
            errors = validate_state(state)
            if errors:
                return self._handle_invariant_failure(state, errors)
            self.state_store.save(state)

        if "static_scan" not in state:
            slither_runner = self.slither_runner or SlitherRunner(self.artifacts_dir)
            runner_pool = RunnerPool(parallel=self.parallel_tools)
            static_scan = StaticScan(
                state_store=self.state_store,
                slither_runner=slither_runner,
                runner_pool=runner_pool,
                quick_linters=self.quick_linters,
            )
            self.state_store.save(state)
            started_at = self._now_iso()
            static_scan.run(target_path)
            state = self.state_store.load()
            finished_at = self._now_iso()
            static_status = state.get("static_scan", {}).get("status")
            artifact_paths = state.get("static_scan", {}).get("artifact_paths", [])
            if static_status in {"skipped", "failed"}:
                self._record_capability_skipped(
                    state,
                    "static_scan",
                    reason=state.get("static_scan", {}).get("reason", "slither_unavailable"),
                    evidence=state.get("static_scan", {}).get("skip_evidence", "slither_unavailable"),
                )
            else:
                self._record_capability_executed(
                    state,
                    "static_scan",
                    status=static_status or "success",
                    started_at=started_at,
                    finished_at=finished_at,
                    artifact_paths=artifact_paths,
                )
            self.state_store.save(state)
            errors = validate_state(state)
            if errors:
                return self._handle_invariant_failure(state, errors)
        else:
            self._record_capability_skipped(
                state,
                "static_scan",
                reason="already_present",
                evidence="state_contains_static_scan",
            )
            self.state_store.save(state)
            state = self.state_store.load()

        slither_json_path = self.artifacts_dir / "slither.json"
        if "graph_analysis" not in state and slither_json_path.exists():
            graph_analysis = GraphAnalysis(state_store=self.state_store)
            started_at = self._now_iso()
            self.state_store.save(state)
            slither_json = json.loads(slither_json_path.read_text())
            graph_analysis.analyze(slither_json)
            state = self.state_store.load()
            self._record_capability_executed(
                state,
                "graph_analysis",
                status="success",
                started_at=started_at,
                finished_at=self._now_iso(),
                artifact_paths=[str(slither_json_path)],
            )
            errors = validate_state(state)
            if errors:
                return self._handle_invariant_failure(state, errors)
        elif "graph_analysis" not in state:
            self._record_capability_skipped(
                state,
                "graph_analysis",
                reason="slither_json_missing",
                evidence="slither_json_missing",
            )
            self.state_store.save(state)
            state = self.state_store.load()

        state = self.state_store.load()
        self._run_solodit(state)
        state = self.state_store.load()

        fuzz_agent = FuzzAgent(
            state_store=self.state_store,
            runner=FoundryRunner(self.artifacts_dir),
        )
        should_run, reason = fuzz_agent.should_run(state)
        if should_run:
            self.state_store.save(state)
            started_at = self._now_iso()
            fuzz_result = fuzz_agent.run(target_path)
            state = self.state_store.load()
            if fuzz_result.get("status") in {"skipped", "failed"}:
                self._record_capability_skipped(
                    state,
                    "fuzz_agent",
                    reason=fuzz_result.get("reason", "foundry_unavailable"),
                    evidence=fuzz_result.get("evidence", "foundry_unavailable"),
                )
            else:
                self._record_capability_executed(
                    state,
                    "fuzz_agent",
                    status=fuzz_result.get("status", "success"),
                    started_at=started_at,
                    finished_at=self._now_iso(),
                    artifact_paths=[state.get("fuzz", {}).get("log_path")],
                )
            self.state_store.save(state)
        else:
            self._record_capability_skipped(state, "fuzz_agent", reason=reason, evidence="thresholds")
            self.state_store.save(state)

        state = self.state_store.load()
        self._run_proof_agent(state)
        state = self.state_store.load()
        self._run_repair_agent(state, target_path)
        state = self.state_store.load()
        self._run_llm_synthesis(state)
        state = self.state_store.load()
        errors = validate_state(state)
        if errors:
            return self._handle_invariant_failure(state, errors)

        state["status"] = "completed"
        self.state_store.save(state)
        return ReportGenerator(self.artifacts_dir).write_report(state)

    def _record_capability_executed(
        self,
        state: dict[str, Any],
        name: str,
        status: str,
        started_at: str,
        finished_at: str,
        artifact_paths: list[str],
    ) -> None:
        """Track executed capability details."""
        capabilities = state.setdefault("capabilities", {"executed": {}, "skipped": {}})
        capabilities["executed"][name] = {
            "started_at": started_at,
            "finished_at": finished_at,
            "artifact_paths": [path for path in artifact_paths if path],
            "status": status,
        }

    def _record_capability_skipped(
        self,
        state: dict[str, Any],
        name: str,
        reason: str,
        evidence: str,
    ) -> None:
        """Track skipped capability details."""
        capabilities = state.setdefault("capabilities", {"executed": {}, "skipped": {}})
        capabilities["skipped"][name] = {"reason": reason, "evidence": evidence}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _handle_invariant_failure(self, state: dict[str, Any], errors: list[str]) -> Path:
        """Persist failure state and write a report that includes errors."""
        state["status"] = "failed_invariant"
        state["invariant_errors"] = errors
        self.state_store.save(state)
        return ReportGenerator(self.artifacts_dir).write_report(state)

    def _run_llm_synthesis(self, state: dict[str, Any]) -> None:
        """Run LLM synthesis when findings and budget allow."""
        findings = collect_findings(state)
        if not findings:
            self._record_capability_skipped(
                state,
                "llm_synthesis",
                reason="no_findings",
                evidence="no_findings",
            )
            state["llm_synthesis"] = {"status": "skipped", "reason": "no_findings"}
            self.state_store.save(state)
            return

        if not self._has_llm_budget(state):
            self._record_capability_skipped(
                state,
                "llm_synthesis",
                reason="insufficient_budget",
                evidence="budget",
            )
            state["llm_synthesis"] = {"status": "skipped", "reason": "insufficient_budget"}
            self.state_store.save(state)
            return

        synthesis = LLMSynthesis.from_env(
            artifacts_dir=self.artifacts_dir,
            offline_fixtures=self.offline_fixtures,
            fixtures_dir=self.fixtures_dir,
        )
        if not synthesis.is_available():
            self._record_capability_skipped(
                state,
                "llm_synthesis",
                reason="llm_unavailable",
                evidence="llm_not_configured",
            )
            state["llm_synthesis"] = {"status": "skipped", "reason": "llm_unavailable"}
            self.state_store.save(state)
            return

        started_at = self._now_iso()
        result = synthesis.summarize(state)
        finished_at = self._now_iso()
        if result.get("status") != "success" or not result.get("summary"):
            self._record_capability_skipped(
                state,
                "llm_synthesis",
                reason="llm_error",
                evidence="llm_failed",
            )
        else:
            self._record_capability_executed(
                state,
                "llm_synthesis",
                status="success",
                started_at=started_at,
                finished_at=finished_at,
                artifact_paths=result.get("artifact_paths", []),
            )

        state["llm_synthesis"] = result
        self.state_store.save(state)

    def _has_llm_budget(self, state: dict[str, Any]) -> bool:
        """Check remaining budget against the LLM minimum threshold."""
        budget = state.get("budget", {})
        cap = budget.get("cap")
        spent = budget.get("spent", 0)
        min_budget = int(os.getenv("LLM_MIN_BUDGET", "1"))
        if cap is None:
            return False
        remaining = cap - spent
        return remaining >= min_budget

    def _run_solodit(self, state: dict[str, Any]) -> None:
        """Run Solodit enrichment when escalation level permits."""
        if state.get("escalation_level", 0) < 2:
            self._record_capability_skipped(
                state,
                "solodit",
                reason="escalation_level",
                evidence="escalation_level",
            )
            state["solodit"] = {"status": "skipped", "reason": "escalation_level"}
            self.state_store.save(state)
            return

        booster = SoloditSignalBooster.from_env(
            artifacts_dir=self.artifacts_dir,
            offline_fixtures=self.offline_fixtures,
            fixtures_dir=self.fixtures_dir,
        )
        if not booster.is_available():
            self._record_capability_skipped(
                state,
                "solodit",
                reason="solodit_unavailable",
                evidence="solodit_not_configured",
            )
            state["solodit"] = {"status": "skipped", "reason": "solodit_unavailable"}
            self.state_store.save(state)
            return

        started_at = self._now_iso()
        result = booster.enrich(state)
        finished_at = self._now_iso()
        if result.get("status") != "success":
            self._record_capability_skipped(
                state,
                "solodit",
                reason="solodit_error",
                evidence=result.get("reason", "solodit_error"),
            )
        else:
            self._record_capability_executed(
                state,
                "solodit",
                status="success",
                started_at=started_at,
                finished_at=finished_at,
                artifact_paths=result.get("artifact_paths", []),
            )
        state["solodit"] = result
        self.state_store.save(state)

    def _run_proof_agent(self, state: dict[str, Any]) -> None:
        """Run the proof agent to generate invariant stubs."""
        if not collect_findings(state):
            self._record_capability_skipped(
                state,
                "proof_agent",
                reason="no_findings",
                evidence="no_findings",
            )
            state["proofs"] = {"status": "skipped", "reason": "no_findings", "artifacts": []}
            self.state_store.save(state)
            return

        proof_agent = ProofAgent(state_store=self.state_store, artifacts_dir=self.artifacts_dir)
        started_at = self._now_iso()
        self.state_store.save(state)
        proof_agent.run()
        state = self.state_store.load()
        proofs = state.get("proofs", {})
        artifacts = proofs.get("artifacts", [])
        artifact_paths: list[str] = []
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    path = artifact.get("path")
                    if path:
                        artifact_paths.append(path)
                elif isinstance(artifact, str):
                    artifact_paths.append(artifact)
        self._record_capability_executed(
            state,
            "proof_agent",
            status="success",
            started_at=started_at,
            finished_at=self._now_iso(),
            artifact_paths=artifact_paths,
        )
        self.state_store.save(state)

    def _run_repair_agent(self, state: dict[str, Any], target_path: str) -> None:
        """Run the repair agent if gating conditions are met."""
        repair_agent = RepairAgent(state_store=self.state_store, artifacts_dir=self.artifacts_dir)
        should_run, reason, _finding = repair_agent.should_run(state)
        if should_run:
            started_at = self._now_iso()
            self.state_store.save(state)
            repair_agent.run(target_path)
            state = self.state_store.load()
            self._record_capability_executed(
                state,
                "repair_agent",
                status=state.get("repair", {}).get("status", "success"),
                started_at=started_at,
                finished_at=self._now_iso(),
                artifact_paths=[state.get("repair", {}).get("patch_path")],
            )
            self.state_store.save(state)
        else:
            self._record_capability_skipped(state, "repair_agent", reason=reason, evidence="gating")
            state["repair"] = {"status": "skipped", "reason": reason}
            self.state_store.save(state)
