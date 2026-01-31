"""Solodit signal booster stub for heuristic enrichment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SoloditSignalBooster:
    """Enrich state signals with placeholder Solodit-style pattern matches."""

    source: str = "solodit"

    def enrich(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return a new enrichment payload derived from the current state."""
        static_scan = state.get("static_scan", {})
        signals = static_scan.get("signals", {})
        evidence = static_scan.get("evidence", [])

        matches = []
        for category, count in signals.items():
            if not count:
                continue
            matches.append(
                {
                    "category": category,
                    "count": count,
                    "evidence_count": len(evidence),
                    "label": f"heuristic:{category}",
                    "source": self.source,
                    "status": "unverified",
                    "confidence": "low",
                    "disclaimer": "External heuristic match; not a proven vulnerability.",
                }
            )

        return {
            "source": self.source,
            "status": "heuristic",
            "disclaimer": "External enrichment only; requires manual validation.",
            "pattern_matches": matches,
        }
