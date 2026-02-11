"""Solodit booster compatibility shim."""
from __future__ import annotations

from ralph_wiggum.agents.solodit import SoloditSignalBooster


class SoloditBooster(SoloditSignalBooster):
    """Backward-compatible alias for the Solodit signal booster."""
