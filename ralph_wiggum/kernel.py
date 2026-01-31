"""Kernel loop for orchestrating agent execution."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from ralph_wiggum.agents.graph_analysis import GraphAnalysis
from ralph_wiggum.agents.llm_synthesis import LLMSynthesis
from ralph_wiggum.agents.proof_agent import ProofAgent
from ralph_wiggum.agents.repair_agent import RepairAgent
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

    def run(self, target_path: str) -> Path:
        """Run the kernel loop for a given target path."""
        if self.budget is None:
            self.budget = Budget()
        if self.kill_switch is None:
            self.kill_switch = KillSwitch()
        self.state_store.ensure_state_file()

        state = self.state_store.load()
        state.setdefault("status", "running")
        state.setdefault("capabilities", {"executed": [], "skipped": []})
        state.setdefault("budget", {"spent": 0, "cap": 0})
        state["target_path"] = target_path
        self.state_store.save(state)

        errors = validate_state(state)
        if errors:
            return self._handle_invariant_failure(state, errors)

        agent_queue = state.get("agent_queue", [])
        for agent in agent_queue:
            self._record_capability(state, agent, executed=True, reason="queued")
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
            self._record_capability(state, "static_scan", executed=True, reason="kernel")
            self.state_store.save(state)
            static_scan.run(target_path)
            state = self.state_store.load()
            errors = validate_state(state)
            if errors:
                return self._handle_invariant_failure(state, errors)
        else:
            self._record_capability(state, "static_scan", executed=False, reason="already_present")
            self.state_store.save(state)
            state = self.state_store.load()

        slither_json_path = self.artifacts_dir / "slither.json"
        if "graph_analysis" not in state and slither_json_path.exists():
            graph_analysis = GraphAnalysis(state_store=self.state_store)
            self._record_capability(state, "graph_analysis", executed=True, reason="kernel")
            self.state_store.save(state)
            slither_json = json.loads(slither_json_path.read_text())
            graph_analysis.analyze(slither_json)
            state = self.state_store.load()
            errors = validate_state(state)
            if errors:
                return self._handle_invariant_failure(state, errors)
        elif "graph_analysis" not in state:
            self._record_capability(state, "graph_analysis", executed=False, reason="slither_json_missing")
            self.state_store.save(state)
            state = self.state_store.load()

        fuzz_agent = FuzzAgent(
            state_store=self.state_store,
            runner=FoundryRunner(self.artifacts_dir),
        )
        should_run, reason = fuzz_agent.should_run(state)
        if should_run:
            self._record_capability(state, "fuzz_agent", executed=True, reason=reason)
            self.state_store.save(state)
            fuzz_agent.run(target_path)
        else:
            self._record_capability(state, "fuzz_agent", executed=False, reason=reason)
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

    def _record_capability(self, state: dict[str, Any], name: str, executed: bool, reason: str) -> None:
        """Track capability execution in state with reasons."""
        capabilities = state.setdefault("capabilities", {"executed": [], "skipped": []})
        bucket = "executed" if executed else "skipped"
        entry = {"name": name, "reason": reason}
        if entry not in capabilities[bucket]:
            capabilities[bucket].append(entry)

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
            self._record_capability(state, "llm_synthesis", executed=False, reason="no_findings")
            state["llm_synthesis"] = {"status": "skipped", "reason": "no_findings"}
            self.state_store.save(state)
            return

        if not self._has_llm_budget(state):
            self._record_capability(state, "llm_synthesis", executed=False, reason="insufficient_budget")
            state["llm_synthesis"] = {"status": "skipped", "reason": "insufficient_budget"}
            self.state_store.save(state)
            return

        synthesis = LLMSynthesis.from_env()
        if synthesis.client is None:
            self._record_capability(state, "llm_synthesis", executed=False, reason="llm_unavailable")
            state["llm_synthesis"] = {"status": "skipped", "reason": "llm_unavailable"}
            self.state_store.save(state)
            return

        result = synthesis.summarize(state)
        if result.get("status") != "success" or not result.get("summary"):
            self._record_capability(state, "llm_synthesis", executed=False, reason="llm_error")
        else:
            self._record_capability(state, "llm_synthesis", executed=True, reason="completed")

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

    def _run_proof_agent(self, state: dict[str, Any]) -> None:
        """Run the proof agent to generate invariant stubs."""
        if not collect_findings(state):
            self._record_capability(state, "proof_agent", executed=False, reason="no_findings")
            state["proofs"] = {"status": "skipped", "reason": "no_findings", "artifacts": []}
            self.state_store.save(state)
            return

        proof_agent = ProofAgent(state_store=self.state_store, artifacts_dir=self.artifacts_dir)
        self._record_capability(state, "proof_agent", executed=True, reason="generated")
        self.state_store.save(state)
        proof_agent.run()

    def _run_repair_agent(self, state: dict[str, Any], target_path: str) -> None:
        """Run the repair agent if gating conditions are met."""
        repair_agent = RepairAgent(state_store=self.state_store, artifacts_dir=self.artifacts_dir)
        should_run, reason, _finding = repair_agent.should_run(state)
        if should_run:
            self._record_capability(state, "repair_agent", executed=True, reason=reason)
            self.state_store.save(state)
            repair_agent.run(target_path)
        else:
            self._record_capability(state, "repair_agent", executed=False, reason=reason)
            state["repair"] = {"status": "skipped", "reason": reason}
            self.state_store.save(state)
