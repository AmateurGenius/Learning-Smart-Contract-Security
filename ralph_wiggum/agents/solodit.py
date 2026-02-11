"""Solodit signal booster with HTTP and offline fixture support."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import URLError

from ralph_wiggum.scoring import collect_findings


@dataclass
class SoloditClient:
    """HTTP client for Solodit-style enrichment endpoints."""

    base_url: str
    api_key: str | None = None

    def enrich(self, payload: dict[str, Any], timeout_seconds: int = 30) -> dict[str, Any]:
        """POST enrichment payloads to the Solodit endpoint."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            f"{self.base_url.rstrip('/')}/v1/enrich",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


@dataclass
class SoloditSignalBooster:
    """Enrich state signals with Solodit responses or offline fixtures."""

    client: SoloditClient | None = None
    artifacts_dir: Path = Path("artifacts")
    offline_fixtures: bool = False
    fixtures_dir: Path | None = None
    source: str = "solodit"

    @classmethod
    def from_env(
        cls,
        *,
        artifacts_dir: Path = Path("artifacts"),
        offline_fixtures: bool = False,
        fixtures_dir: Path | None = None,
    ) -> "SoloditSignalBooster":
        """Create a Solodit booster from environment variables."""
        base_url = os.getenv("SOLODIT_BASE_URL")
        api_key = os.getenv("SOLODIT_API_KEY")
        client = None
        if base_url:
            client = SoloditClient(base_url=base_url, api_key=api_key)
        return cls(
            client=client,
            artifacts_dir=artifacts_dir,
            offline_fixtures=offline_fixtures,
            fixtures_dir=fixtures_dir,
        )

    def is_available(self) -> bool:
        """Return True when Solodit enrichment can run."""
        return self.offline_fixtures or self.client is not None

    def enrich(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return an enrichment payload derived from the current state."""
        artifacts_dir = self.artifacts_dir / "solodit"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        request_path = artifacts_dir / "solodit_request.json"
        response_path = artifacts_dir / "solodit_response.json"
        error_path = artifacts_dir / "solodit_error.json"

        signals = state.get("static_scan", {}).get("signals", {})
        evidence = state.get("static_scan", {}).get("evidence", [])
        findings = collect_findings(state)
        payload = {
            "signals": signals,
            "evidence": evidence,
            "findings": findings,
            "metadata": {"target": state.get("target_path"), "escalation_level": state.get("escalation_level")},
        }
        request_path.write_text(json.dumps(payload, indent=2) + "\n")

        if self.offline_fixtures:
            response = self._load_fixture()
            if response is None:
                error_payload = {"error": "offline_fixture_missing"}
                error_path.write_text(json.dumps(error_payload, indent=2) + "\n")
                return {
                    "status": "error",
                    "reason": "offline_fixture_missing",
                    "pattern_matches": [],
                    "source": self.source,
                }
            response_path.write_text(json.dumps(response, indent=2) + "\n")
            return self._normalize_response(response, request_path, response_path)

        if not self.client:
            return {"status": "unavailable", "pattern_matches": [], "source": self.source}

        try:
            response = self.client.enrich(payload)
            response_path.write_text(json.dumps(response, indent=2) + "\n")
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            error_payload = {"error": str(exc)}
            error_path.write_text(json.dumps(error_payload, indent=2) + "\n")
            return {
                "status": "error",
                "reason": str(exc),
                "pattern_matches": [],
                "source": self.source,
            }

        return self._normalize_response(response, request_path, response_path)

    def _normalize_response(self, response: dict[str, Any], request_path: Path, response_path: Path) -> dict[str, Any]:
        matches = response.get("pattern_matches", [])
        if not isinstance(matches, list):
            matches = []
        return {
            "status": "success" if matches or response.get("status") == "success" else "error",
            "source": self.source,
            "pattern_matches": matches,
            "disclaimer": "External heuristic enrichment; not proven evidence.",
            "artifact_paths": [str(request_path), str(response_path)],
        }

    def _load_fixture(self) -> dict[str, Any] | None:
        fixtures_dir = self.fixtures_dir or Path("tests") / "fixtures" / "solodit"
        if not fixtures_dir.exists():
            return None
        fixture_files = sorted(path for path in fixtures_dir.iterdir() if path.suffix == ".json")
        if not fixture_files:
            return None
        return json.loads(fixture_files[0].read_text())
