"""Budget tracking utilities for agent execution."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Budget:
    """Placeholder budget tracker for time, token, or cost limits."""

    token_limit: int = 0
    cost_limit_usd: float = 0.0
    time_limit_seconds: int = 0
