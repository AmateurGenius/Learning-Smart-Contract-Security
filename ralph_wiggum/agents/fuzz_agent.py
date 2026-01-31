"""Foundry fuzzing agent for executing forge tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.foundry_runner import FoundryRunner


@dataclass
class FuzzAgent:
    """Run Foundry fuzz tests when thresholds are met."""

    state_store: StateStore
    runner: FoundryRunner
    fuzz_runs: int = 256
    static_threshold: int = 1
    graph_threshold: int = 1

    def should_run(self, state: dict[str, Any]) -> tuple[bool, str]:
        """Return whether the fuzz agent should run and a reason."""
        budget = state.get("budget", {})
        cap = budget.get("cap")
        spent = budget.get("spent", 0)
        if cap and spent >= cap:
            return False, "budget_exceeded"

        static_signals = state.get("static_scan", {}).get("signals", {})
        static_score = sum(static_signals.values()) if isinstance(static_signals, dict) else 0
        graph_score = state.get("graph_analysis", {}).get("score", 0)
        if static_score >= self.static_threshold or graph_score >= self.graph_threshold:
            return True, "threshold_met"
        return False, "threshold_not_met"

    def run(self, target_path: str) -> dict[str, Any]:
        """Run forge fuzz tests and persist failures into state."""
        result = self.runner.run(target_path, fuzz_runs=self.fuzz_runs)
        state = self.state_store.load()
        state.setdefault("fuzz", {})
        state["fuzz"]["log_path"] = result.get("log_path")
        if result.get("status") == "failed":
            state["fuzz_failures"] = result.get("failures", [])
        self.state_store.save(state)
        return result
