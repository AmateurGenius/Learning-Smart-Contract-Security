"""State persistence for the auditor."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class StateStore:
    """Handles reading and writing the persistent state file."""

    path: Path

    def ensure_state_file(self) -> None:
        """Ensure the state file exists with a minimal JSON payload."""
        if not self.path.exists():
            self.path.write_text(json.dumps({"status": "initialized"}, indent=2))

    def load(self) -> dict:
        """Load state from disk."""
        if not self.path.exists():
            return {"status": "missing"}
        return json.loads(self.path.read_text())

    def save(self, payload: dict) -> None:
        """Save state to disk."""
        self.path.write_text(json.dumps(payload, indent=2))
