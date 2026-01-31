"""Differential review mode for security-focused change analysis."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

from ralph_wiggum.state import StateStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DifferentialReview:
    """Generate a deterministic delta report between two Git refs."""

    state_store: StateStore
    artifacts_dir: Path
    repo_path: Path = Path(".")

    def run(self, base_ref: str, head_ref: str, target_path: str) -> dict[str, Any]:
        """Run the differential review and persist artifacts/state."""
        diff_dir = self.artifacts_dir / "diff"
        diff_dir.mkdir(parents=True, exist_ok=True)

        changed_files = self._changed_solidity_files(base_ref, head_ref, target_path)
        changed_files_path = diff_dir / "changed_files.json"
        changed_files_path.write_text(json.dumps({"files": changed_files}, indent=2) + "\n")
        (diff_dir / "changed_files.log").write_text(f"Changed Solidity files: {len(changed_files)}\n")

        base_analysis = self._analyze_ref(base_ref, changed_files)
        head_analysis = self._analyze_ref(head_ref, changed_files)

        delta = self._delta_classes(base_analysis["classes"], head_analysis["classes"])

        delta_report = {
            "base_ref": base_ref,
            "head_ref": head_ref,
            "changed_files": changed_files,
            "summary": {
                "resolved": len(delta["resolved"]),
                "regressed": len(delta["regressed"]),
                "unchanged": len(delta["unchanged"]),
            },
            "capabilities": {
                "entrypoints": base_analysis["entrypoints"]["capability"],
                "static_scan": head_analysis["static_scan"],
            },
            "delta": delta,
        }

        delta_report_path = diff_dir / "delta_report.json"
        delta_report_path.write_text(json.dumps(delta_report, indent=2) + "\n")
        delta_report_md_path = diff_dir / "delta_report.md"
        delta_report_md_path.write_text(self._render_markdown(delta_report) + "\n")

        state = self.state_store.load()
        state["diff_review"] = {
            "base_ref": base_ref,
            "head_ref": head_ref,
            "changed_files": changed_files,
            "summary": delta_report["summary"],
            "artifact_paths": [
                str(changed_files_path),
                str(delta_report_path),
                str(delta_report_md_path),
                str(base_analysis["entrypoints"]["artifact_path"]),
                str(base_analysis["entrypoints"]["log_path"]),
            ],
            "provenance": {
                "entrypoints": base_analysis["entrypoints"],
                "static_scan": head_analysis["static_scan"],
            },
            "executed_at": _now_iso(),
        }
        self.state_store.save(state)

        return delta_report

    def _changed_solidity_files(self, base_ref: str, head_ref: str, target_path: str) -> list[str]:
        command = [
            "git",
            "diff",
            "--name-only",
            base_ref,
            head_ref,
            "--",
            target_path,
        ]
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        files = [line.strip() for line in result.stdout.splitlines() if line.strip().endswith(".sol")]
        return sorted(files)

    def _analyze_ref(self, ref: str, files: list[str]) -> dict[str, Any]:
        entrypoints = self._entrypoints_for_ref(ref, files)
        classes, static_scan_cap = self._static_scan_classes(ref, files)
        return {
            "entrypoints": entrypoints,
            "classes": classes,
            "static_scan": static_scan_cap,
        }

    def _entrypoints_for_ref(self, ref: str, files: list[str]) -> dict[str, Any]:
        entrypoints: list[dict[str, Any]] = []
        for path in files:
            content = self._read_file_at_ref(ref, path)
            entrypoints.extend(self._entrypoints_from_source(content, path))

        entrypoints = sorted(entrypoints, key=lambda item: item["name"])
        diff_dir = self.artifacts_dir / "diff"
        output_path = diff_dir / "entrypoints.json"
        log_path = diff_dir / "entrypoints.log"
        output_path.write_text(json.dumps({"entrypoints": entrypoints}, indent=2) + "\n")
        log_path.write_text(f"Entry points: {len(entrypoints)}\n")
        return {
            "entrypoints": entrypoints,
            "artifact_path": str(output_path),
            "log_path": str(log_path),
            "capability": {
                "status": "executed",
                "reason": "heuristic",
                "confidence": "medium",
            },
        }

    def _static_scan_classes(self, ref: str, files: list[str]) -> tuple[set[str], dict[str, str]]:
        slither_json_path = self.artifacts_dir / "slither.json"
        if slither_json_path.exists():
            slither_json = json.loads(slither_json_path.read_text())
            classes = self._classes_from_slither(slither_json)
            return classes, {"status": "executed", "reason": "slither_json", "confidence": "high"}
        return self._classes_from_source(ref, files), {
            "status": "skipped",
            "reason": "slither_unavailable",
            "confidence": "low",
        }

    def _classes_from_slither(self, slither_json: dict[str, Any]) -> set[str]:
        detectors = slither_json.get("results", {}).get("detectors", [])
        classes = set()
        for detector in detectors:
            check = (detector.get("check") or "").lower()
            if "reentrancy" in check:
                classes.add("reentrancy")
            elif "unchecked" in check and "return" in check:
                classes.add("unchecked_return")
            elif "delegatecall" in check or "low-level" in check or "call" in check:
                classes.add("dangerous_call")
        return classes

    def _classes_from_source(self, ref: str, files: Iterable[str]) -> set[str]:
        classes = set()
        for path in files:
            try:
                content = self._read_file_at_ref(ref, path)
            except subprocess.CalledProcessError:
                continue
            if "call(" in content or "delegatecall" in content:
                classes.add("dangerous_call")
        return classes

    def _read_file_at_ref(self, ref: str, path: str) -> str:
        command = ["git", "show", f"{ref}:{path}"]
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.stdout

    def _entrypoints_from_source(self, content: str, path: str) -> list[dict[str, Any]]:
        entrypoints: list[dict[str, Any]] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = re.search(r"function\s+(\w+)\s*\(", line)
            if not match:
                continue
            name = match.group(1)
            lower = line.lower()
            if "public" not in lower and "external" not in lower:
                continue
            if "view" in lower or "pure" in lower:
                continue
            entrypoints.append(
                {
                    "name": name,
                    "path": path,
                    "lines": [line_number],
                }
            )
        return entrypoints

    def _delta_classes(self, base: set[str], head: set[str]) -> dict[str, list[str]]:
        resolved = sorted(base - head)
        regressed = sorted(head - base)
        unchanged = sorted(base & head)
        return {
            "resolved": resolved,
            "regressed": regressed,
            "unchanged": unchanged,
        }

    def _render_markdown(self, delta_report: dict[str, Any]) -> str:
        lines = [
            "# Ralph Wiggum Differential Review",
            "",
            f"Base: `{delta_report['base_ref']}`",
            f"Head: `{delta_report['head_ref']}`",
            "",
            "## Changed Solidity Files",
        ]
        for path in delta_report["changed_files"]:
            lines.append(f"- {path}")
        if not delta_report["changed_files"]:
            lines.append("- None")

        lines.extend(["", "## Delta Summary"])
        summary = delta_report["summary"]
        lines.append(f"- Resolved: {summary['resolved']}")
        lines.append(f"- Regressed: {summary['regressed']}")
        lines.append(f"- Unchanged: {summary['unchanged']}")

        lines.extend(["", "## Findings Delta"])
        for key in ("regressed", "resolved", "unchanged"):
            items = delta_report["delta"][key]
            lines.append(f"- {key.title()}: {', '.join(items) if items else 'None'}")

        lines.extend(["", "## Capabilities"])
        for name, info in delta_report["capabilities"].items():
            lines.append(
                f"- {name}: {info['status']} ({info['reason']}), confidence={info['confidence']}"
            )
        return "\n".join(lines)
