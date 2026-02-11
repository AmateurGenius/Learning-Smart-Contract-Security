"""Tests for StaticScan signal extraction and escalation."""
from __future__ import annotations

import json
from pathlib import Path

from ralph_wiggum.agents.static_scan import StaticScan
from ralph_wiggum.escalation import EscalationRouter
from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.slither_runner import SlitherRunner


def test_static_scan_records_signals_and_escalates(tmp_path: Path) -> None:
    """Static scan should write signals and trigger escalation when thresholds hit."""
    artifacts_dir = tmp_path / "artifacts"
    state_store = StateStore(tmp_path / "state.json")
    state_store.save({"status": "ready"})

    slither_runner = SlitherRunner(artifacts_dir=artifacts_dir)
    fixture_path = Path(__file__).parent / "fixtures" / "slither.json"
    slither_payload = json.loads(fixture_path.read_text())
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "slither.json").write_text(json.dumps(slither_payload))
    (artifacts_dir / "slither.log").write_text("slither log")

    slither_runner.run = lambda _: slither_payload

    scan = StaticScan(
        state_store=state_store,
        slither_runner=slither_runner,
        escalation_router=EscalationRouter(),
    )
    findings = scan.run(str(tmp_path))

    assert findings["signals"]["reentrancy"] == 1
    assert findings["signals"]["unchecked_return"] == 1
    assert findings["signals"]["delegatecall"] == 1
    assert findings["findings"][0]["source_tool"] == "slither"
    assert "slither.json" in findings["findings"][0]["artifact_paths"][0]

    state = state_store.load()
    assert state["escalation_level"] == 1
    assert state["static_scan"]["artifacts"]["slither_json"].endswith("slither.json")


def test_static_scan_handles_missing_slither(tmp_path: Path) -> None:
    """Static scan should skip cleanly when Slither is unavailable."""
    artifacts_dir = tmp_path / "artifacts"
    state_store = StateStore(tmp_path / "state.json")
    state_store.save({"status": "ready"})

    slither_runner = SlitherRunner(artifacts_dir=artifacts_dir)
    slither_runner.run = lambda _: {
        "status": "skipped",
        "reason": "slither_unavailable",
        "results": {"detectors": []},
    }

    scan = StaticScan(
        state_store=state_store,
        slither_runner=slither_runner,
        escalation_router=EscalationRouter(),
    )
    findings = scan.run(str(tmp_path))

    assert findings["status"] == "skipped"
    assert findings["signals"] == {"reentrancy": 0, "unchecked_return": 0, "delegatecall": 0}
    state = state_store.load()
    assert state.get("escalation_level") is None
