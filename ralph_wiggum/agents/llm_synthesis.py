"""LLM synthesis agent for OpenAI-compatible vLLM endpoints."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import request


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

    @classmethod
    def from_env(cls) -> "LLMSynthesis":
        """Build the synthesis agent from environment variables."""
        base_url = os.getenv("VLLM_BASE_URL")
        model = os.getenv("VLLM_MODEL")
        api_key = os.getenv("VLLM_API_KEY")
        if base_url and model:
            return cls(client=LLMClient(base_url=base_url, model=model, api_key=api_key))
        return cls(client=None)

    def summarize(self, context: dict[str, Any]) -> dict[str, Any]:
        """Summarize findings, returning a status and optional summary text."""
        if not self.client:
            return {"status": "unavailable", "summary": None}

        try:
            response = self.client.chat(
                [
                    {"role": "system", "content": "Summarize the audit findings."},
                    {"role": "user", "content": json.dumps(context)},
                ]
            )
        except Exception as exc:  # noqa: BLE001 - return graceful degradation
            return {"status": "error", "summary": None, "error": str(exc)}

        summary = None
        try:
            summary = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            summary = None

        return {"status": "success", "summary": summary}
