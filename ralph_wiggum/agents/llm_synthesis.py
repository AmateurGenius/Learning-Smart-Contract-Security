"""LLM synthesis agent for OpenAI-compatible vLLM endpoints."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import URLError


@dataclass
class LLMClient:
    """Client for OpenAI-compatible chat completion endpoints."""

    base_url: str
    model: str
    api_key: str | None = None

    def chat(self, messages: list[dict[str, str]], timeout_seconds: int = 30) -> dict[str, Any]:
        """Send a chat completion request and return the parsed response."""
        payload = {
            "model": self.model,
            "messages": messages,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


@dataclass
class LLMSynthesis:
    """Synthesize findings using an optional LLM backend."""

    client: LLMClient | None = None
    artifacts_dir: Path = Path("artifacts")
    offline_fixtures: bool = False
    fixtures_dir: Path | None = None

    @classmethod
    def from_env(
        cls,
        *,
        artifacts_dir: Path = Path("artifacts"),
        offline_fixtures: bool = False,
        fixtures_dir: Path | None = None,
    ) -> "LLMSynthesis":
        """Build the synthesis agent from environment variables."""
        base_url = os.getenv("VLLM_BASE_URL")
        model = os.getenv("VLLM_MODEL")
        api_key = os.getenv("VLLM_API_KEY")
        client = None
        if base_url and model:
            client = LLMClient(base_url=base_url, model=model, api_key=api_key)
        return cls(
            client=client,
            artifacts_dir=artifacts_dir,
            offline_fixtures=offline_fixtures,
            fixtures_dir=fixtures_dir,
        )

    def is_available(self) -> bool:
        """Return True when synthesis can run (online or offline)."""
        return self.offline_fixtures or self.client is not None

    def summarize(self, context: dict[str, Any]) -> dict[str, Any]:
        """Summarize findings, returning a status and optional summary text."""
        artifacts_dir = self.artifacts_dir / "llm"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        request_path = artifacts_dir / "llm_request.json"
        response_path = artifacts_dir / "llm_response.json"
        error_path = artifacts_dir / "llm_error.json"

        messages = [
            {"role": "system", "content": "Summarize the audit findings."},
            {"role": "user", "content": json.dumps(context)},
        ]
        request_payload = {"model": self._model_name(), "messages": messages}
        request_path.write_text(json.dumps(request_payload, indent=2) + "\n")

        if self.offline_fixtures:
            response = self._load_fixture()
            if response is None:
                error_payload = {"error": "offline_fixture_missing"}
                error_path.write_text(json.dumps(error_payload, indent=2) + "\n")
                return {
                    "status": "error",
                    "summary": None,
                    "error": "offline_fixture_missing",
                    "artifact_paths": [str(request_path), str(error_path)],
                }
            response_path.write_text(json.dumps(response, indent=2) + "\n")
            summary = _extract_summary(response)
            return {
                "status": "success" if summary else "error",
                "summary": summary,
                "artifact_paths": [str(request_path), str(response_path)],
            }

        if not self.client:
            return {"status": "unavailable", "summary": None}

        try:
            response = self.client.chat(messages)
            response_path.write_text(json.dumps(response, indent=2) + "\n")
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            error_payload = {"error": str(exc)}
            error_path.write_text(json.dumps(error_payload, indent=2) + "\n")
            return {
                "status": "error",
                "summary": None,
                "error": str(exc),
                "artifact_paths": [str(request_path), str(error_path)],
            }

        summary = _extract_summary(response)

        return {
            "status": "success" if summary else "error",
            "summary": summary,
            "artifact_paths": [str(request_path), str(response_path)],
        }

    def _model_name(self) -> str:
        if self.client and self.client.model:
            return self.client.model
        return os.getenv("VLLM_MODEL", "fixture-model")

    def _load_fixture(self) -> dict[str, Any] | None:
        fixtures_dir = self.fixtures_dir or Path("tests") / "fixtures" / "llm"
        if not fixtures_dir.exists():
            return None
        fixture_files = sorted(path for path in fixtures_dir.iterdir() if path.suffix == ".json")
        if not fixture_files:
            return None
        return json.loads(fixture_files[0].read_text())


def _extract_summary(response: dict[str, Any]) -> str | None:
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
