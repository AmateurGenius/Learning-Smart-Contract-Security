"""Lightweight linter for quick heuristic signals."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ralph_wiggum.tools.runner_pool import ToolResult


@dataclass
class QuickLinterRunner:
    """Scan Solidity files for quick heuristic signals."""

    artifacts_dir: Path
    name: str = "quick_linter"

    def run(self, target_path: str) -> ToolResult:
        """Run the heuristic lint checks and return findings."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.artifacts_dir / "quick_lint.log"

        findings: list[dict[str, object]] = []
        for file_path in self._solidity_files(Path(target_path)):
            for line_number, line in enumerate(file_path.read_text().splitlines(), start=1):
                if "TODO" in line or "FIXME" in line:
                    findings.append(
                        {
                            "category": "lint",
                            "check": "todo_comment",
                            "description": "TODO/FIXME marker found in Solidity source.",
                            "path": str(file_path),
                            "lines": [line_number],
                            "source_tool": self.name,
                            "artifact_paths": [str(log_path)],
                            "confidence": "heuristic",
                        }
                    )

        log_lines = [
            "# Quick Lint Summary",
            f"Findings: {len(findings)}",
        ]
        log_path.write_text("\n".join(log_lines) + "\n")

        return ToolResult(
            name=self.name,
            artifacts=[str(log_path)],
            findings=sorted(findings, key=self._finding_sort_key),
            payload={"finding_count": len(findings)},
        )

    def _solidity_files(self, root: Path) -> Iterable[Path]:
        """Yield Solidity files under the target path in deterministic order."""
        if root.is_file() and root.suffix == ".sol":
            return [root]
        if not root.exists():
            return []
        return sorted(path for path in root.rglob("*.sol") if path.is_file())

    @staticmethod
    def _finding_sort_key(finding: dict[str, object]) -> tuple[str, int]:
        """Sort findings deterministically by path and line."""
        path = str(finding.get("path", ""))
        lines = finding.get("lines") or []
        line_number = lines[0] if isinstance(lines, list) and lines else 0
        return (path, int(line_number))
