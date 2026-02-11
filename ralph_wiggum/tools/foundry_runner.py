"""Runner for executing Foundry tests in a target repository."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess


@dataclass
class FoundryRunner:
    """Adapter for running forge test with configurable fuzz runs."""

    artifacts_dir: Path

    def run(self, target_path: str, fuzz_runs: int = 256, timeout_seconds: int = 600) -> dict:
        """Run Foundry tests and capture output to artifacts."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.artifacts_dir / "foundry_fuzz.log"
        artifact_paths = [str(log_path)]

        execution = self._resolve_execution(target_path, fuzz_runs)
        command = execution.get("command")
        if command is None:
            evidence = execution.get("evidence", "foundry_unavailable")
            self._write_log(log_path, "", evidence)
            return {
                "status": "skipped",
                "reason": "foundry_unavailable",
                "evidence": evidence,
                "log_path": str(log_path),
                "failures": [],
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
                "reason": "foundry_timeout",
                "log_path": str(log_path),
                "failures": [],
                "artifact_paths": artifact_paths,
            }
        except FileNotFoundError as exc:
            evidence = "docker compose not installed" if command and command[0] == "docker" else "binary forge not found"
            self._write_log(log_path, "", evidence)
            return {
                "status": "skipped",
                "reason": "foundry_unavailable",
                "evidence": evidence,
                "log_path": str(log_path),
                "failures": [],
                "artifact_paths": artifact_paths,
            }
        except subprocess.CalledProcessError as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            failures = self._extract_failures(exc.stdout or "" + "\n" + (exc.stderr or ""))
            return {
                "status": "failed",
                "reason": "foundry_failed",
                "log_path": str(log_path),
                "failures": failures,
                "artifact_paths": artifact_paths,
            }

        self._write_log(log_path, result.stdout, result.stderr)

        return {
            "status": "success",
            "log_path": str(log_path),
            "failures": [],
            "artifact_paths": artifact_paths,
            "execution_mode": execution.get("mode"),
        }

    def _resolve_execution(self, target_path: str, fuzz_runs: int) -> dict[str, object]:
        if self._docker_compose_available():
            if not self._docker_compose_service("foundry"):
                return {"command": None, "evidence": "service foundry not defined"}
            if not self._docker_compose_service_running("foundry"):
                return {"command": None, "evidence": "service foundry not running"}
            return {
                "mode": "docker",
                "command": [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "foundry",
                    "forge",
                    "test",
                    "--fuzz-runs",
                    str(fuzz_runs),
                ],
                "cwd": None,
            }
        if shutil.which("forge"):
            return {
                "mode": "local",
                "command": ["forge", "test", "--fuzz-runs", str(fuzz_runs)],
                "cwd": target_path,
            }
        return {"command": None, "evidence": "binary forge not found"}

    def _docker_compose_available(self) -> bool:
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

    def _write_log(self, log_path: Path, stdout: str | None, stderr: str | None) -> None:
        """Write combined stdout/stderr log."""
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

    def _extract_failures(self, output: str) -> list[dict]:
        """Extract minimal failure summaries from output."""
        failures = []
        for line in output.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            if "FAIL" in normalized or "Fail" in normalized or "FAILED" in normalized:
                seed = None
                if "seed" in normalized.lower():
                    seed = normalized
                failures.append({"test": normalized, "snippet": normalized, "seed": seed})
        return failures
