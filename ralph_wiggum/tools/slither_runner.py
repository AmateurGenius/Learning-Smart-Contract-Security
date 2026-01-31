"""Runner for invoking Slither and parsing JSON output."""
from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
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

        if self._use_existing_output(output_path):
            self._write_log(log_path, "Using existing Slither JSON output.", "")
            return json.loads(output_path.read_text())

        command = self._build_command(target_path, output_path)
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Slither timed out after {timeout_seconds}s for {target_path}"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError("Slither executable not found in PATH") from exc
        except subprocess.CalledProcessError as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            raise RuntimeError(f"Slither failed: {stderr}") from exc

        self._write_log(log_path, result.stdout, result.stderr)

        if not output_path.exists():
            raise RuntimeError("Slither did not produce an output JSON file")

        return json.loads(output_path.read_text())

    def _build_command(self, target_path: str, output_path: Path) -> list[str]:
        """Build the Slither command, preferring docker compose if available."""
        if self._docker_compose_available():
            return [
                "docker",
                "compose",
                "run",
                "--rm",
                "slither",
                "slither",
                target_path,
                "--json",
                str(output_path),
            ]
        return ["slither", target_path, "--json", str(output_path)]

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
