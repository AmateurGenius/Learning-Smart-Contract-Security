"""Static scan agent that runs Slither and records initial signals."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ralph_wiggum.escalation import EscalationRouter
from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.quick_linter import QuickLinterRunner
from ralph_wiggum.tools.runner_pool import RunnerPool, ToolJob, ToolResult
from ralph_wiggum.tools.slither_runner import SlitherRunner


@dataclass
class StaticScan:
    """Run Slither and extract initial security signals."""

    state_store: StateStore
    slither_runner: SlitherRunner
    escalation_router: EscalationRouter = field(default_factory=EscalationRouter)
    runner_pool: RunnerPool | None = None
    quick_linters: list[QuickLinterRunner] = field(default_factory=list)
    thresholds: dict[str, int] = field(
        default_factory=lambda: {
            "reentrancy": 1,
            "unchecked_return": 1,
            "delegatecall": 1,
        }
    )

    def run(self, target_path: str) -> dict[str, Any]:
        """Run the static analysis and persist findings to state."""
        slither_json, tool_results = self._run_tools(target_path)
        signals, evidence, slither_findings = self._extract_signals(slither_json)
        linter_findings = RunnerPool.merge_findings(
            result for result in tool_results if result.name != "slither"
        )
        merged_findings = self._sort_findings(slither_findings + linter_findings)
        artifact_paths = RunnerPool.merge_artifacts(tool_results)

        findings = {
            "signals": signals,
            "evidence": evidence,
            "findings": merged_findings,
            "artifacts": {
                "slither_json": str(self.slither_runner.artifacts_dir / "slither.json"),
                "slither_log": str(self.slither_runner.artifacts_dir / "slither.log"),
            },
            "artifact_paths": artifact_paths,
        }

        state = self.state_store.load()
        state["static_scan"] = findings

        if self._should_escalate(signals):
            state["escalation_level"] = 1
            self.escalation_router.level = 1

        self.state_store.save(state)
        return findings

    def _run_tools(self, target_path: str) -> tuple[dict[str, Any], list[ToolResult]]:
        """Run Slither plus any quick linters through the runner pool."""
        pool = self.runner_pool or RunnerPool(parallel=False)
        jobs = [ToolJob(name="slither", runner=lambda: self._run_slither(target_path))]
        for linter in self.quick_linters:
            jobs.append(ToolJob(name=linter.name, runner=lambda runner=linter: runner.run(target_path)))
        results = pool.run(jobs)
        slither_result = next((result for result in results if result.name == "slither"), None)
        if slither_result is None or not isinstance(slither_result.payload, dict):
            raise RuntimeError("Slither runner did not return JSON payload")
        return slither_result.payload, results

    def _run_slither(self, target_path: str) -> ToolResult:
        """Run Slither and wrap the output in a ToolResult."""
        slither_json = self.slither_runner.run(target_path)
        artifacts = [
            str(self.slither_runner.artifacts_dir / "slither.json"),
            str(self.slither_runner.artifacts_dir / "slither.log"),
        ]
        return ToolResult(name="slither", artifacts=artifacts, payload=slither_json)

    @staticmethod
    def _sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return findings in deterministic order."""
        return sorted(findings, key=RunnerPool._finding_sort_key)

    def _should_escalate(self, signals: dict[str, int]) -> bool:
        """Determine whether the findings exceed escalation thresholds."""
        for key, threshold in self.thresholds.items():
            if signals.get(key, 0) >= threshold:
                return True
        return False

    def _extract_signals(
        self, slither_json: dict[str, Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract signal counts and evidence entries from Slither JSON."""
        detectors = slither_json.get("results", {}).get("detectors", [])
        counts = {"reentrancy": 0, "unchecked_return": 0, "delegatecall": 0}
        evidence: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        artifact_paths = [
            str(self.slither_runner.artifacts_dir / "slither.json"),
            str(self.slither_runner.artifacts_dir / "slither.log"),
        ]

        for detector in detectors:
            check = (detector.get("check") or "").lower()
            if "reentrancy" in check:
                counts["reentrancy"] += 1
                category = "reentrancy"
            elif "unchecked" in check and "return" in check:
                counts["unchecked_return"] += 1
                category = "unchecked_return"
            elif "delegatecall" in check or "low-level" in check or "call" in check:
                counts["delegatecall"] += 1
                category = "dangerous_call"
            else:
                continue

            finding = {
                "category": category,
                "check": detector.get("check"),
                "description": detector.get("description"),
                "impact": detector.get("impact"),
                "confidence": detector.get("confidence", "unknown"),
                "source_tool": "slither",
                "artifact_paths": artifact_paths,
            }
            findings.append(finding)

            for element in detector.get("elements", []):
                source = element.get("source_mapping", {})
                evidence.append(
                    {
                        "category": category,
                        "check": detector.get("check"),
                        "description": detector.get("description"),
                        "path": source.get("filename_absolute") or source.get("filename"),
                        "lines": source.get("lines"),
                    }
                )

        return counts, evidence, findings
