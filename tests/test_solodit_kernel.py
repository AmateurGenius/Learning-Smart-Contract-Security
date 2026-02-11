"""Tests for Solodit integration in the kernel."""
from __future__ import annotations

from pathlib import Path

from ralph_wiggum.kernel import Kernel
from ralph_wiggum.state import StateStore


def test_solodit_skipped_when_unconfigured(tmp_path: Path) -> None:
    """Solodit should skip when the endpoint is not configured."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "capabilities": {"executed": {}, "skipped": {}},
            "budget": {"spent": 0, "cap": 5},
            "static_scan": {"signals": {}, "evidence": [], "findings": [], "status": "success"},
            "graph_analysis": {
                "score": 0,
                "graph_backend": "fallback",
                "cycles": [],
                "privileged_entry_points": [],
                "sensitive_external_calls": [],
            },
            "escalation_level": 2,
        }
    )

    kernel = Kernel(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
    kernel.run(str(tmp_path))

    state = state_store.load()
    skipped = state["capabilities"]["skipped"]
    assert skipped["solodit"]["reason"] == "solodit_unavailable"
