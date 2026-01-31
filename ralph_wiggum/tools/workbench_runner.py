"""Workbench helper for running Slither with docker compose when available."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass
class WorkbenchSlitherRunner:
    """Run Slither with docker compose exec when configured."""

    artifacts_dir: Path

    def run(self, target_path: str, output_path: Path, log_path: Path, timeout_seconds: int = 300) -> None:
        """Execute Slither and write stdout/stderr logs."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        command = self._build_command(target_path, output_path)
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            self._write_log(log_path, result.stdout, result.stderr)
        except subprocess.TimeoutExpired as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            raise RuntimeError(f"Slither timed out after {timeout_seconds}s for {target_path}") from exc
        except FileNotFoundError as exc:
            self._write_log(log_path, "", str(exc))
            raise RuntimeError("Slither executable not found") from exc
        except subprocess.CalledProcessError as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            raise RuntimeError(f"Slither failed: {stderr}") from exc

    def _build_command(self, target_path: str, output_path: Path) -> list[str]:
        if self._docker_compose_available():
            return [
                "docker",
                "compose",
                "exec",
                "-T",
                "slither",
                "slither",
                target_path,
                "--json",
                str(output_path),
            ]
        return ["slither", target_path, "--json", str(output_path)]

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

    @staticmethod
    def _write_log(log_path: Path, stdout: str | None, stderr: str | None) -> None:
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
