"""Secure contracts toolkit normalizer for workbench tasks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.workbench_runner import WorkbenchSlitherRunner


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SecureContractsToolkit:
    """Normalize vulnerability classes from available tool outputs."""

    state_store: StateStore
    artifacts_dir: Path
    slither_runner: WorkbenchSlitherRunner

    def run(self, target_path: str) -> dict[str, Any]:
        """Normalize Slither findings into security classes."""
        workbench_dir = self.artifacts_dir / "workbench"
        workbench_dir.mkdir(parents=True, exist_ok=True)
        output_path = workbench_dir / "secure_contracts.json"
        log_path = workbench_dir / "secure_contracts.log"
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
            except Exception as exc:  # noqa: BLE001 - degrade to empty
                slither_log.write_text(f"Slither unavailable: {exc}\n")

        classes = self._normalize(slither_json)
        payload = {"vulnerability_classes": classes}
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
        log_path.write_text(f"Classes: {len(classes)}\n")

        state = self.state_store.load()
        state.setdefault("workbench", {})
        state["workbench"]["secure_contracts"] = {
            "source_tool": source_tool,
            "artifact_paths": [str(output_path), str(log_path), str(slither_log)],
            "confidence": confidence,
            "executed_at": _now_iso(),
        }
        self.state_store.save(state)
        return payload

    def _normalize(self, slither_json: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not slither_json:
            return []
        detectors = slither_json.get("results", {}).get("detectors", [])
        classes: dict[str, dict[str, Any]] = {}
        for detector in detectors:
            check = (detector.get("check") or "").lower()
            if "reentrancy" in check:
                key = "reentrancy"
            elif "unchecked" in check and "return" in check:
                key = "unchecked_return"
            elif "delegatecall" in check or "low-level" in check or "call" in check:
                key = "dangerous_call"
            else:
                continue

            classes.setdefault(
                key,
                {
                    "class": key,
                    "evidence": [],
                },
            )
            classes[key]["evidence"].append(
                {
                    "check": detector.get("check"),
                    "description": detector.get("description"),
                }
            )
        return [classes[key] for key in sorted(classes.keys())]
