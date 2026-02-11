"""Tests for the Solodit signal booster."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from ralph_wiggum.agents.solodit import SoloditClient, SoloditSignalBooster


def test_solodit_booster_offline_fixture(tmp_path: Path) -> None:
    """Solodit booster should read offline fixtures when enabled."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "response.json").write_text(
        json.dumps({"status": "success", "pattern_matches": [{"category": "reentrancy"}]})
    )

    booster = SoloditSignalBooster(
        artifacts_dir=tmp_path,
        offline_fixtures=True,
        fixtures_dir=fixtures_dir,
    )
    enrichment = booster.enrich(
        {
            "static_scan": {
                "signals": {"reentrancy": 2},
                "evidence": [{"path": "contracts/Vault.sol"}],
            }
        }
    )

    assert enrichment["status"] == "success"
    assert enrichment["pattern_matches"][0]["category"] == "reentrancy"
    assert enrichment["disclaimer"].startswith("External heuristic")
    assert (tmp_path / "solodit" / "solodit_request.json").exists()
    assert (tmp_path / "solodit" / "solodit_response.json").exists()


def test_solodit_client_online_response(tmp_path: Path) -> None:
    """Solodit client should parse JSON responses from HTTP."""
    client = SoloditClient(base_url="http://example.com", api_key="token")
    response = mock.Mock()
    response.read.return_value = b'{"status":"success","pattern_matches":[{"category":"delegatecall"}]}'
    response.__enter__ = lambda self: self
    response.__exit__ = lambda *args: None

    with mock.patch("urllib.request.urlopen", return_value=response):
        result = client.enrich({"signals": {"delegatecall": 1}})

    assert result["pattern_matches"][0]["category"] == "delegatecall"
