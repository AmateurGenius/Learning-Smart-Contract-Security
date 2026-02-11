"""Tests for the Foundry runner adapter."""
from __future__ import annotations

from pathlib import Path
import subprocess
from unittest import mock

from ralph_wiggum.tools.foundry_runner import FoundryRunner


def test_foundry_runner_writes_logs(tmp_path: Path) -> None:
    """Foundry runner should write stdout and stderr logs."""
    artifacts_dir = tmp_path / "artifacts"
    runner = FoundryRunner(artifacts_dir=artifacts_dir)

    completed = mock.Mock(stdout="ok", stderr="", returncode=0)

    with mock.patch.object(
        runner,
        "_resolve_execution",
        return_value={
            "command": ["forge", "test", "--fuzz-runs", "10"],
            "cwd": str(tmp_path),
            "mode": "local",
        },
    ):
        with mock.patch("subprocess.run", return_value=completed) as mocked:
            result = runner.run(str(tmp_path), fuzz_runs=10, timeout_seconds=1)

    assert mocked.call_args[0][0][:3] == ["forge", "test", "--fuzz-runs"]
    assert Path(result["log_path"]).read_text()
    assert result["status"] == "success"


def test_foundry_runner_timeout(tmp_path: Path) -> None:
    """Foundry runner should raise on timeout."""
    runner = FoundryRunner(artifacts_dir=tmp_path)

    with mock.patch.object(
        runner,
        "_resolve_execution",
        return_value={
            "command": ["forge", "test", "--fuzz-runs", "5"],
            "cwd": str(tmp_path),
            "mode": "local",
        },
    ):
        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="forge", timeout=1),
        ):
            result = runner.run(str(tmp_path), fuzz_runs=5, timeout_seconds=1)

    assert result["status"] == "failed"
    assert result["reason"] == "foundry_timeout"


def test_foundry_runner_missing_executable(tmp_path: Path) -> None:
    """Foundry runner should skip when forge is unavailable."""
    runner = FoundryRunner(artifacts_dir=tmp_path)

    with mock.patch.object(
        runner,
        "_resolve_execution",
        return_value={
            "command": ["forge", "test", "--fuzz-runs", "5"],
            "cwd": str(tmp_path),
            "mode": "local",
        },
    ):
        with mock.patch(
            "subprocess.run",
            side_effect=FileNotFoundError("forge"),
        ):
            result = runner.run(str(tmp_path), fuzz_runs=5, timeout_seconds=1)

    assert result["status"] == "skipped"
    assert result["reason"] == "foundry_unavailable"


def test_foundry_runner_prefers_docker_compose(tmp_path: Path) -> None:
    """Foundry runner should prefer docker compose when available."""
    runner = FoundryRunner(artifacts_dir=tmp_path)

    with mock.patch.object(runner, "_docker_compose_available", return_value=True), \
        mock.patch.object(runner, "_docker_compose_service", return_value=True), \
        mock.patch.object(runner, "_docker_compose_service_running", return_value=True), \
        mock.patch("shutil.which", return_value=None):
        execution = runner._resolve_execution(str(tmp_path), 128)

    command = execution["command"]
    assert command[:4] == ["docker", "compose", "exec", "-T"]


def test_foundry_runner_falls_back_to_local_binary(tmp_path: Path) -> None:
    """Foundry runner should fall back to local forge when compose is unavailable."""
    runner = FoundryRunner(artifacts_dir=tmp_path)

    with mock.patch.object(runner, "_docker_compose_available", return_value=False), \
        mock.patch("shutil.which", return_value="/usr/bin/forge"):
        execution = runner._resolve_execution(str(tmp_path), 64)

    assert execution["command"] == ["forge", "test", "--fuzz-runs", "64"]
