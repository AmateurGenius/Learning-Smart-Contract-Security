"""Tests for workbench entrypoints output."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from ralph_wiggum.state import StateStore
from ralph_wiggum.workbench.entrypoints import EntryPointAnalyzer
from ralph_wiggum.tools.workbench_runner import WorkbenchSlitherRunner


def test_entrypoints_output_and_state(tmp_path: Path) -> None:
    """Entrypoints task should write deterministic output and state."""
    artifacts_dir = tmp_path / "artifacts"
    state_store = StateStore(tmp_path / "state.json")
    state_store.save({"status": "ready"})

    slither_fixture = Path(__file__).parent / "fixtures" / "workbench" / "slither_entrypoints.json"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "slither.json").write_text(slither_fixture.read_text())

    analyzer = EntryPointAnalyzer(
        state_store=state_store,
        artifacts_dir=artifacts_dir,
        slither_runner=WorkbenchSlitherRunner(artifacts_dir),
    )

    with mock.patch("ralph_wiggum.workbench.entrypoints._now_iso", return_value="2024-01-01T00:00:00+00:00"):
        payload = analyzer.run(str(tmp_path))

    output_path = artifacts_dir / "workbench" / "entrypoints.json"
    assert output_path.exists()
    output = json.loads(output_path.read_text())
    assert output == payload
    assert output["entrypoints"][0]["name"] == "adminSet"
    assert output["entrypoints"][1]["name"] == "withdraw"

    state = state_store.load()
    entrypoints_state = state["workbench"]["entrypoints"]
    assert entrypoints_state["source_tool"] == "slither"
    assert entrypoints_state["confidence"] == "high"
    for artifact_path in entrypoints_state["artifact_paths"]:
        assert Path(artifact_path).exists()
