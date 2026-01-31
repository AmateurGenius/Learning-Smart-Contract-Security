"""Runner for executing Foundry tests in a target repository."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass
class FoundryRunner:
    """Adapter for running forge test with configurable fuzz runs."""

    artifacts_dir: Path

    def run(self, target_path: str, fuzz_runs: int = 256, timeout_seconds: int = 600) -> dict:
        """Run Foundry tests and capture output to artifacts."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.artifacts_dir / "foundry_fuzz.log"

        command = ["forge", "test", "--fuzz-runs", str(fuzz_runs)]
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=target_path,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Foundry tests timed out after {timeout_seconds}s for {target_path}"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError("Forge executable not found in PATH") from exc
        except subprocess.CalledProcessError as exc:
            self._write_log(log_path, exc.stdout, exc.stderr)
            failures = self._extract_failures(exc.stdout or "" + "\n" + (exc.stderr or ""))
            return {
                "status": "failed",
                "log_path": str(log_path),
                "failures": failures,
            }

        self._write_log(log_path, result.stdout, result.stderr)

        return {
            "status": "success",
            "log_path": str(log_path),
            "failures": [],
        }

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
                failures.append({"test": normalized, "snippet": normalized})
        return failures
