"""Tests for FuzzAgent routing and state updates."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from ralph_wiggum.agents.fuzz_agent import FuzzAgent
from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.foundry_runner import FoundryRunner


def test_fuzz_agent_respects_thresholds(tmp_path: Path) -> None:
    """FuzzAgent should only run when thresholds are met."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "budget": {"spent": 0, "cap": 0},
            "static_scan": {"signals": {"reentrancy": 0}},
            "graph_analysis": {"score": 0},
        }
    )

    agent = FuzzAgent(state_store=state_store, runner=FoundryRunner(tmp_path))
    should_run, reason = agent.should_run(state_store.load())
    assert should_run is False
    assert reason == "threshold_not_met"


def test_fuzz_agent_runs_and_records_failures(tmp_path: Path) -> None:
    """FuzzAgent should persist failures and log path."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "budget": {"spent": 0, "cap": 0},
            "static_scan": {"signals": {"reentrancy": 1}},
        }
    )

    runner = FoundryRunner(tmp_path)
    agent = FuzzAgent(state_store=state_store, runner=runner)

    with mock.patch.object(
        runner,
        "run",
        return_value={
            "status": "failed",
            "log_path": str(tmp_path / "foundry_fuzz.log"),
            "failures": [{"test": "FAIL", "snippet": "FAIL"}],
        },
    ):
        result = agent.run(str(tmp_path))

    assert result["status"] == "failed"
    state = state_store.load()
    assert state["fuzz_failures"][0]["test"] == "FAIL"
    assert state["fuzz"]["log_path"].endswith("foundry_fuzz.log")
