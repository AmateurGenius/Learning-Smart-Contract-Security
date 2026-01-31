"""Tests for the Slither runner adapter."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest import mock

import pytest

from ralph_wiggum.tools.slither_runner import SlitherRunner


def test_slither_runner_parses_json(tmp_path: Path) -> None:
    """Slither runner should parse JSON output on success."""
    artifacts_dir = tmp_path / "artifacts"
    output_path = artifacts_dir / "slither.json"
    output_payload = {"results": {"detectors": []}}

    def fake_run(*args, **kwargs):
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output_payload))
        return mock.Mock(stdout="ok", stderr="")

    runner = SlitherRunner(artifacts_dir=artifacts_dir)

    with mock.patch("subprocess.run", side_effect=fake_run):
        assert runner.run("/tmp/contracts") == output_payload
        assert (artifacts_dir / "slither.log").read_text()


def test_slither_runner_timeout(tmp_path: Path) -> None:
    """Slither runner should raise on timeout."""
    runner = SlitherRunner(artifacts_dir=tmp_path)

    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="slither", timeout=1),
    ):
        with pytest.raises(RuntimeError, match="timed out"):
            runner.run("/tmp/contracts", timeout_seconds=1)
