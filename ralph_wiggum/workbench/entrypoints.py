"""Entry point analyzer for workbench tasks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.workbench_runner import WorkbenchSlitherRunner


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EntryPointAnalyzer:
    """Analyze entry points for state-changing public/external functions."""

    state_store: StateStore
    artifacts_dir: Path
    slither_runner: WorkbenchSlitherRunner

    def run(self, target_path: str) -> dict[str, Any]:
        """Analyze entry points and persist output/state."""
        workbench_dir = self.artifacts_dir / "workbench"
        workbench_dir.mkdir(parents=True, exist_ok=True)
        output_path = workbench_dir / "entrypoints.json"
        log_path = workbench_dir / "entrypoints.log"
        slither_log = workbench_dir / "slither_exec.log"
        slither_json_path = self.artifacts_dir / "slither.json"

        slither_json = None
        source_tool = "heuristic"
        confidence = "low"
        if slither_json_path.exists():
            slither_json = json.loads(slither_json_path.read_text())
            source_tool = "slither"
            confidence = "high"
            slither_log.write_text("Using existing Slither JSON.\n")
        else:
            try:
                self.slither_runner.run(target_path, slither_json_path, slither_log)
                if slither_json_path.exists():
                    slither_json = json.loads(slither_json_path.read_text())
                    source_tool = "slither"
                    confidence = "high"
            except Exception as exc:  # noqa: BLE001 - degrade to heuristic
                slither_log.write_text(f"Slither unavailable: {exc}\n")

        if slither_json:
            entrypoints = self._from_slither(slither_json)
        else:
            entrypoints = self._heuristic_scan(Path(target_path))

        entrypoints = sorted(entrypoints, key=lambda item: item["name"])
        payload = {"entrypoints": entrypoints}
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
        log_path.write_text(f"Entry points: {len(entrypoints)}\n")

        state = self.state_store.load()
        state.setdefault("workbench", {})
        state["workbench"]["entrypoints"] = {
            "source_tool": source_tool,
            "artifact_paths": [str(output_path), str(log_path), str(slither_log)],
            "confidence": confidence,
            "executed_at": _now_iso(),
        }
        self.state_store.save(state)
        return payload

    def _from_slither(self, slither_json: dict[str, Any]) -> list[dict[str, Any]]:
        entrypoints: list[dict[str, Any]] = []
        for function in slither_json.get("functions", []):
            visibility = (function.get("visibility") or "").lower()
            mutability = (function.get("state_mutability") or "").lower()
            name = function.get("name")
            if visibility not in {"public", "external"}:
                continue
            if mutability in {"view", "pure"}:
                continue
            evidence = []
            for element in function.get("elements", []):
                source = element.get("source_mapping", {})
                evidence.append(
                    {
                        "path": source.get("filename_absolute") or source.get("filename"),
                        "lines": source.get("lines"),
                    }
                )
            entrypoints.append({"name": name, "visibility": visibility, "evidence": evidence})
        return entrypoints

    def _heuristic_scan(self, target_path: Path) -> list[dict[str, Any]]:
        entrypoints: list[dict[str, Any]] = []
        for file_path in sorted(target_path.rglob("*.sol")):
            for line_number, line in enumerate(file_path.read_text().splitlines(), start=1):
                match = re.search(r"function\\s+(\\w+)\\s*\\(", line)
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
                        "visibility": "public/external",
                        "evidence": [{"path": str(file_path), "lines": [line_number]}],
                    }
                )
        return entrypoints
