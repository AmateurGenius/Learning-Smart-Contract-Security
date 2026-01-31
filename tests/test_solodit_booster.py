"""Tests for the Solodit signal booster."""
from __future__ import annotations

from ralph_wiggum.agents.solodit import SoloditSignalBooster


def test_solodit_booster_enriches_state() -> None:
    """Solodit booster should emit heuristic pattern matches."""
    state = {
        "static_scan": {
            "signals": {"reentrancy": 2, "delegatecall": 0},
            "evidence": [{"path": "contracts/Vault.sol"}],
        }
    }

    booster = SoloditSignalBooster()
    enrichment = booster.enrich(state)

    assert enrichment["status"] == "heuristic"
    assert enrichment["disclaimer"].startswith("External enrichment")
    assert enrichment["pattern_matches"][0]["status"] == "unverified"
    assert enrichment["pattern_matches"][0]["category"] == "reentrancy"
    assert enrichment["pattern_matches"][0]["evidence_count"] == 1
