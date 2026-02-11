"""Repair agent that proposes minimal patches and verifies improvements."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import os

from ralph_wiggum.scoring import collect_findings, score_findings
from ralph_wiggum.state import StateStore


Verifier = Callable[[dict[str, Any], str], dict[str, Any]]


@dataclass
class RepairAgent:
    """Propose minimal patches and verify fixes for high-confidence findings."""

    state_store: StateStore
    artifacts_dir: Path
    verifier: Verifier | None = None

    def should_run(self, state: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
        """Check if repair should run and return a target finding."""
        scored = score_findings(collect_findings(state))
        if not scored:
            return False, "no_findings", None

        finding = scored[0].get("finding", {})
        confidence = str(finding.get("confidence", "")).lower()
        has_repro = any(
            finding.get(key) for key in ("repro", "repro_steps", "repro_path")
        )
        if confidence != "high" or not has_repro:
            return False, "insufficient_evidence", finding

        if not self._has_budget(state):
            return False, "insufficient_budget", finding

        return True, "eligible", finding

    def run(self, target_path: str) -> dict[str, Any]:
        """Run the repair loop and persist results."""
        state = self.state_store.load()
        should_run, reason, finding = self.should_run(state)
        if not should_run:
            state["repair"] = {"status": "skipped", "reason": reason}
            self.state_store.save(state)
            return state["repair"]

        repairs_dir = self.artifacts_dir / "repairs"
        repairs_dir.mkdir(parents=True, exist_ok=True)
        patch_path = repairs_dir / "patch_1.diff"
        description = str(finding.get("description", "repair"))
        patch_content = "\n".join(
            [
                f"# Proposed patch for: {description}",
                "# TODO: Replace with real diff when available.",
                "",
            ]
        )
        patch_path.write_text(patch_content)

        verifier = self.verifier or (lambda *_: {"status": "skipped", "reason": "no_verifier"})
        score_before = score_findings(collect_findings(state))
        result = verifier(finding, str(patch_path))
        score_after = result.get("score_after")
        resolved = result.get("resolved")

        success = False
        if isinstance(score_after, (int, float)) and score_before:
            success = score_after < score_before[0].get("score", 0)
        if resolved is True:
            success = True

        status = "success" if success else "failed"
        repair_record = {
            "status": status,
            "patch_path": str(patch_path),
            "source_tool": finding.get("source_tool", "unknown"),
            "confidence": finding.get("confidence", "unknown"),
            "description": description,
            "verifier_result": result,
        }
        if not success:
            repair_record["reason"] = result.get("reason", "verification_failed")

        state["repair"] = repair_record
        self.state_store.save(state)
        return repair_record

    def _has_budget(self, state: dict[str, Any]) -> bool:
        budget = state.get("budget", {})
        cap = budget.get("cap")
        spent = budget.get("spent", 0)
        min_budget = int(os.getenv("REPAIR_MIN_BUDGET", "1"))
        if cap is None:
            return False
        return (cap - spent) >= min_budget
