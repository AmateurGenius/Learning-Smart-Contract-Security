"""Tests for LLM synthesis gating in the kernel."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from ralph_wiggum.agents.llm_synthesis import LLMSynthesis
from ralph_wiggum.kernel import Kernel
from ralph_wiggum.state import StateStore


def _base_state() -> dict:
    return {
        "capabilities": {"executed": [], "skipped": []},
        "budget": {"spent": 0, "cap": 5},
        "static_scan": {"signals": {}, "evidence": [], "findings": []},
    }


def test_llm_skipped_with_no_findings(tmp_path: Path) -> None:
    """LLM synthesis should skip when there are no findings."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(_base_state())

    kernel = Kernel(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
    kernel.run(str(tmp_path))

    state = state_store.load()
    skipped = state["capabilities"]["skipped"]
    assert any(entry["name"] == "llm_synthesis" and entry["reason"] == "no_findings" for entry in skipped)
    assert state["llm_synthesis"]["status"] == "skipped"


def test_llm_skipped_with_low_budget(tmp_path: Path) -> None:
    """LLM synthesis should skip when remaining budget is below minimum."""
    state = _base_state()
    state["budget"] = {"spent": 0, "cap": 0}
    state["findings"] = [
        {
            "category": "fuzz",
            "description": "fixture",
            "severity": "medium",
            "confidence": "medium",
            "source_tool": "foundry",
            "artifact_paths": ["foundry.log"],
        }
    ]
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(state)

    kernel = Kernel(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
    kernel.run(str(tmp_path))

    state = state_store.load()
    skipped = state["capabilities"]["skipped"]
    assert any(entry["name"] == "llm_synthesis" and entry["reason"] == "insufficient_budget" for entry in skipped)
    assert state["llm_synthesis"]["status"] == "skipped"


def test_llm_error_still_writes_report(tmp_path: Path) -> None:
    """LLM synthesis errors should be recorded and report still written."""
    state = _base_state()
    state["findings"] = [
        {
            "category": "static",
            "description": "fixture",
            "severity": "high",
            "confidence": "high",
            "source_tool": "slither",
            "artifact_paths": ["slither.json"],
        }
    ]
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(state)

    synthesis = LLMSynthesis(client=mock.Mock())
    synthesis.summarize = mock.Mock(return_value={"status": "error", "summary": None, "error": "boom"})

    with mock.patch("ralph_wiggum.kernel.LLMSynthesis.from_env", return_value=synthesis):
        kernel = Kernel(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
        report_path = kernel.run(str(tmp_path))

    assert report_path.exists()
    state = state_store.load()
    skipped = state["capabilities"]["skipped"]
    assert any(entry["name"] == "llm_synthesis" and entry["reason"] == "llm_error" for entry in skipped)
    assert state["llm_synthesis"]["status"] == "error"
