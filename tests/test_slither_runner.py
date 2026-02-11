"""Tests for the Slither runner adapter."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest import mock

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

    with mock.patch.object(
        runner,
        "_resolve_execution",
        return_value={"command": ["slither", "/tmp/contracts"], "cwd": None, "mode": "local"},
    ):
        with mock.patch("subprocess.run", side_effect=fake_run):
            result = runner.run("/tmp/contracts")
            assert result["results"]["detectors"] == []
            assert result["status"] == "success"
            assert (artifacts_dir / "slither.log").read_text()


def test_slither_runner_timeout(tmp_path: Path) -> None:
    """Slither runner should report timeout failures."""
    runner = SlitherRunner(artifacts_dir=tmp_path)

    with mock.patch.object(
        runner,
        "_resolve_execution",
        return_value={"command": ["slither", "/tmp/contracts"], "cwd": None, "mode": "local"},
    ):
        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="slither", timeout=1),
        ):
            result = runner.run("/tmp/contracts", timeout_seconds=1)

    assert result["status"] == "failed"
    assert result["reason"] == "slither_timeout"


def test_slither_runner_prefers_docker_compose(tmp_path: Path) -> None:
    """Slither runner should prefer docker compose when available."""
    runner = SlitherRunner(artifacts_dir=tmp_path)
    output_path = tmp_path / "slither.json"

    with mock.patch.object(runner, "_docker_compose_available", return_value=True), \
        mock.patch.object(runner, "_docker_compose_service", return_value=True), \
        mock.patch.object(runner, "_docker_compose_service_running", return_value=True), \
        mock.patch("shutil.which", return_value=None):
        execution = runner._resolve_execution("/tmp/contracts", output_path)

    command = execution["command"]
    assert command[:4] == ["docker", "compose", "exec", "-T"]


def test_slither_runner_falls_back_to_local_binary(tmp_path: Path) -> None:
    """Slither runner should fall back to local binary when compose is unavailable."""
    runner = SlitherRunner(artifacts_dir=tmp_path)
    output_path = tmp_path / "slither.json"

    with mock.patch.object(runner, "_docker_compose_available", return_value=False), \
        mock.patch("shutil.which", return_value="/usr/bin/slither"):
        execution = runner._resolve_execution("/tmp/contracts", output_path)

    assert execution["command"] == ["slither", "/tmp/contracts", "--json", str(output_path)]
