"""Tests for the Foundry runner adapter."""
from __future__ import annotations

from pathlib import Path
import subprocess
from unittest import mock

import pytest

from ralph_wiggum.tools.foundry_runner import FoundryRunner


def test_foundry_runner_writes_logs(tmp_path: Path) -> None:
    """Foundry runner should write stdout and stderr logs."""
    artifacts_dir = tmp_path / "artifacts"
    runner = FoundryRunner(artifacts_dir=artifacts_dir)

    completed = mock.Mock(stdout="ok", stderr="", returncode=0)

    with mock.patch("subprocess.run", return_value=completed) as mocked:
        result = runner.run(str(tmp_path), fuzz_runs=10, timeout_seconds=1)

    assert mocked.call_args[0][0][:3] == ["forge", "test", "--fuzz-runs"]
    assert Path(result["log_path"]).read_text()
    assert result["status"] == "success"


def test_foundry_runner_timeout(tmp_path: Path) -> None:
    """Foundry runner should raise on timeout."""
    runner = FoundryRunner(artifacts_dir=tmp_path)

    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="forge", timeout=1),
    ):
        with pytest.raises(RuntimeError, match="timed out"):
            runner.run(str(tmp_path), fuzz_runs=5, timeout_seconds=1)
