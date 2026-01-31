"""Tests for graph analysis risk scoring and escalation."""
from __future__ import annotations

from pathlib import Path
import builtins

import pytest

from ralph_wiggum.agents.graph_analysis import GraphAnalysis
from ralph_wiggum.escalation import EscalationRouter
from ralph_wiggum.state import StateStore


def _fixture_payload() -> dict:
    return {
        "function_calls": [
            {"caller": "ownerWithdraw", "callee": "_transfer"},
            {"caller": "_transfer", "callee": "ownerWithdraw"},
        ],
        "functions": [
            {
                "name": "ownerWithdraw",
                "visibility": "external",
                "modifiers": ["onlyOwner"],
                "calls": ["_transfer"],
            },
            {
                "name": "_transfer",
                "visibility": "internal",
                "external_calls": True,
            },
        ],
    }


def test_graph_analysis_fallback_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fallback backend should analyze graph risk without networkx."""
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "networkx":
            raise ModuleNotFoundError("No module named 'networkx'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    state_store = StateStore(tmp_path / "state.json")
    state_store.save({"status": "ready"})

    analysis = GraphAnalysis(
        state_store=state_store,
        escalation_router=EscalationRouter(),
    )
    findings = analysis.analyze(_fixture_payload())

    assert findings["score"] >= 1
    assert "ownerWithdraw" in findings["privileged_entry_points"]
    assert "_transfer" in findings["sensitive_external_calls"]
    assert findings["graph_backend"] == "fallback"

    state = state_store.load()
    assert state["escalation_level"] == 2
    assert state["graph_analysis"]["score"] == findings["score"]


def test_graph_analysis_networkx_parity(tmp_path: Path) -> None:
    """Networkx backend should analyze graph risk when available."""
    pytest.importorskip("networkx")

    state_store = StateStore(tmp_path / "state.json")
    state_store.save({"status": "ready"})

    analysis = GraphAnalysis(
        state_store=state_store,
        escalation_router=EscalationRouter(),
    )
    findings = analysis.analyze(_fixture_payload())

    assert findings["score"] >= 1
    assert "ownerWithdraw" in findings["privileged_entry_points"]
    assert "_transfer" in findings["sensitive_external_calls"]
    assert findings["graph_backend"] == "networkx"
