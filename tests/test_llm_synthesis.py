"""Tests for LLM synthesis client behavior."""
from __future__ import annotations

from unittest import mock

from ralph_wiggum.agents.llm_synthesis import LLMClient, LLMSynthesis


def test_llm_synthesis_unavailable() -> None:
    """LLM synthesis should return unavailable when no client is configured."""
    synth = LLMSynthesis(client=None)
    result = synth.summarize({"foo": "bar"})
    assert result["status"] == "unavailable"
    assert result["summary"] is None


def test_llm_client_chat_parses_response() -> None:
    """LLMClient should parse JSON response."""
    client = LLMClient(base_url="http://example.com", model="test")

    response = mock.Mock()
    response.read.return_value = b'{"choices":[{"message":{"content":"hi"}}]}'
    response.__enter__ = lambda self: self
    response.__exit__ = lambda *args: None

    with mock.patch("urllib.request.urlopen", return_value=response):
        payload = client.chat([{"role": "user", "content": "ping"}])

    assert payload["choices"][0]["message"]["content"] == "hi"
