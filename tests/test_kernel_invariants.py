"""Tests for kernel invariant handling."""
from __future__ import annotations

from pathlib import Path

from ralph_wiggum.kernel import Kernel
from ralph_wiggum.state import StateStore


def test_kernel_handles_invariant_failure(tmp_path: Path) -> None:
    """Kernel should mark failure and still write report.md on invariant errors."""
    artifacts_dir = tmp_path / "artifacts"
    state_path = tmp_path / "state.json"
    state_store = StateStore(state_path)
    state_store.save(
        {
            "budget": {"spent": 1, "cap": 10, "last_spent": 5},
            "capabilities": {"executed": {}, "skipped": {}},
        }
    )

    kernel = Kernel(state_store=state_store, artifacts_dir=artifacts_dir)
    report_path = kernel.run(str(tmp_path))

    state = state_store.load()
    assert state["status"] == "failed_invariant"
    assert report_path.exists()
    assert "## Errors" in report_path.read_text()


def test_kernel_flags_missing_finding_provenance(tmp_path: Path) -> None:
    """Kernel should fail when findings lack provenance fields."""
    artifacts_dir = tmp_path / "artifacts"
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "findings": [{"id": "f1"}],
            "capabilities": {"executed": {}, "skipped": {}},
        }
    )

    kernel = Kernel(state_store=state_store, artifacts_dir=artifacts_dir)
    report_path = kernel.run(str(tmp_path))

    state = state_store.load()
    assert state["status"] == "failed_invariant"
    assert report_path.exists()


def test_kernel_records_fuzz_agent_skip_reason(tmp_path: Path) -> None:
    """Kernel should record fuzz agent skip reasons when thresholds not met."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "budget": {"spent": 0, "cap": 0},
            "capabilities": {"executed": {}, "skipped": {}},
            "static_scan": {"signals": {"reentrancy": 0}},
            "graph_analysis": {"score": 0},
        }
    )

    kernel = Kernel(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
    kernel.run(str(tmp_path))

    state = state_store.load()
    skipped = state["capabilities"]["skipped"]
    assert "fuzz_agent" in skipped
