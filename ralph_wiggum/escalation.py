"""Escalation routing for audit findings."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationRouter:
    """Routes findings to escalation tiers 0 through 3."""

    level: int = 0

    def route(self, finding: str) -> int:
        """Return the escalation level for a finding."""
        _ = finding
        return max(0, min(self.level, 3))
