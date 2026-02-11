"""Runner for invoking Slither and parsing JSON output."""
from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


@dataclass
class SlitherRunner:
    """Adapter for running Slither and returning parsed JSON."""

    artifacts_dir: Path

    def run(self, target_path: str, timeout_seconds: int = 300) -> dict:
        """Run Slither against a target path and return the JSON payload."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.artifacts_dir / "slither.json"
        log_path = self.artifacts_dir / "slither.log"
        artifact_paths = [str(output_path), str(log_path)]

        if self._use_existing_output(output_path):
            self._write_log(log_path, "Using existing Slither JSON output.", "")
            payload = json.loads(output_path.read_text())
            if isinstance(payload, dict):
                payload.setdefault("status", "success")
                payload.setdefault("artifact_paths", artifact_paths)
            return payload

        execution = self._resolve_execution(target_path, output_path)
        command = execution.get("command")
        if command is None:
            evidence = execution.get("evidence", "slither_unavailable")
            self._write_log(log_path, "", evidence)
            return {
                "status": "skipped",
                "reason": "slither_unavailable",
                "evidence": evidence,
                "results": {"detectors": []},
                "artifact_paths": artifact_paths,
            }
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=execution.get("cwd"),
            )
        except subprocess.TimeoutExpired as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            return {
                "status": "failed",
                "reason": "slither_timeout",
                "results": {"detectors": []},
                "artifact_paths": artifact_paths,
            }
        except FileNotFoundError as exc:
            evidence = "docker compose not installed" if command and command[0] == "docker" else "binary slither not found"
            self._write_log(log_path, "", evidence)
            return {
                "status": "skipped",
                "reason": "slither_unavailable",
                "evidence": evidence,
                "results": {"detectors": []},
                "artifact_paths": artifact_paths,
            }
        except subprocess.CalledProcessError as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            return {
                "status": "failed",
                "reason": f"slither_failed: {stderr}",
                "results": {"detectors": []},
                "artifact_paths": artifact_paths,
            }

        self._write_log(log_path, result.stdout, result.stderr)

        if not output_path.exists():
            return {
                "status": "failed",
                "reason": "slither_no_output",
                "results": {"detectors": []},
                "artifact_paths": artifact_paths,
            }

        payload = json.loads(output_path.read_text())
        if isinstance(payload, dict):
            payload.setdefault("status", "success")
            payload.setdefault("artifact_paths", artifact_paths)
            payload.setdefault("execution_mode", execution.get("mode"))
        return payload

    def _resolve_execution(self, target_path: str, output_path: Path) -> dict[str, object]:
        """Resolve the execution command, preferring docker compose exec."""
        if self._docker_compose_available():
            if not self._docker_compose_service("slither"):
                return {"command": None, "evidence": "service slither not defined"}
            if not self._docker_compose_service_running("slither"):
                return {"command": None, "evidence": "service slither not running"}
            container_target = self._container_target_path(target_path)
            return {
                "mode": "docker",
                "command": [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "slither",
                    "slither",
                    container_target,
                    "--json",
                    str(Path("artifacts") / "slither.json"),
                ],
                "cwd": None,
            }
        if shutil.which("slither"):
            return {
                "mode": "local",
                "command": ["slither", target_path, "--json", str(output_path)],
                "cwd": None,
            }
        return {"command": None, "evidence": "binary slither not found"}

    def _docker_compose_available(self) -> bool:
        """Return True when docker compose is available and configured."""
        if not Path("docker-compose.yml").exists():
            return False
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        return True

    def _docker_compose_service(self, service: str) -> bool:
        try:
            result = subprocess.run(
                ["docker", "compose", "config", "--services"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        services = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return service in services

    def _docker_compose_service_running(self, service: str) -> bool:
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--services", "--filter", "status=running"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        running = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return service in running

    @staticmethod
    def _container_target_path(target_path: str) -> str:
        resolved = Path(target_path).resolve()
        repo_root = Path.cwd().resolve()
        try:
            relative = resolved.relative_to(repo_root)
        except ValueError:
            return target_path
        return relative.as_posix()

    def _write_log(self, log_path: Path, stdout: str | None, stderr: str | None) -> None:
        """Write the combined stdout/stderr log."""
        log_path.write_text(
            "\n".join(
                [
                    "### stdout",
                    (stdout or "").strip(),
                    "",
                    "### stderr",
                    (stderr or "").strip(),
                ]
            )
            + "\n"
        )

    def _use_existing_output(self, output_path: Path) -> bool:
        """Return True when offline mode should reuse an existing JSON file."""
        if not output_path.exists():
            return False
        return os.getenv("RALPH_OFFLINE") == "1" or os.getenv("RALPH_USE_EXISTING_SLITHER") == "1"
