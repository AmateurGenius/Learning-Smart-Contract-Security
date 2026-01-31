"""Kill switch controls for aborting execution."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KillSwitch:
    """Placeholder kill switch for emergency stop conditions."""

    enabled: bool = False

    def should_abort(self) -> bool:
        """Return whether execution should abort."""
        return self.enabled
