"""Tests for proof and repair agents."""
from __future__ import annotations

from pathlib import Path

from ralph_wiggum.agents.proof_agent import ProofAgent
from ralph_wiggum.agents.repair_agent import RepairAgent
from ralph_wiggum.state import StateStore


def test_proof_agent_writes_artifacts(tmp_path: Path) -> None:
    """Proof agent should write deterministic artifacts."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "findings": [
                {
                    "category": "reentrancy",
                    "description": "reentrancy issue",
                    "severity": "high",
                    "confidence": "high",
                    "source_tool": "slither",
                    "artifact_paths": ["slither.json"],
                }
            ]
        }
    )

    agent = ProofAgent(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
    artifacts = agent.run()

    assert artifacts
    assert artifacts[0].name.startswith("invariant_1_")
    assert artifacts[0].read_text().startswith("// SPDX-License-Identifier")


def test_repair_agent_skips_without_strong_evidence(tmp_path: Path) -> None:
    """Repair agent should skip when confidence/repro are missing."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "findings": [
                {
                    "category": "reentrancy",
                    "description": "issue",
                    "severity": "high",
                    "confidence": "medium",
                    "source_tool": "slither",
                    "artifact_paths": ["slither.json"],
                }
            ],
            "budget": {"spent": 0, "cap": 5},
        }
    )

    agent = RepairAgent(state_store=state_store, artifacts_dir=tmp_path / "artifacts")
    result = agent.run(str(tmp_path))

    assert result["status"] == "skipped"
    assert result["reason"] == "insufficient_evidence"


def test_repair_agent_records_success_with_provenance(tmp_path: Path) -> None:
    """Repair agent should record verification results with provenance."""
    state_store = StateStore(tmp_path / "state.json")
    state_store.save(
        {
            "findings": [
                {
                    "category": "reentrancy",
                    "description": "issue",
                    "severity": "high",
                    "confidence": "high",
                    "source_tool": "slither",
                    "artifact_paths": ["slither.json"],
                    "repro_steps": "forge test --match testExploit",
                }
            ],
            "budget": {"spent": 0, "cap": 5},
        }
    )

    def verifier(_finding: dict, _patch_path: str) -> dict:
        return {"status": "ok", "resolved": True, "score_after": 0}

    agent = RepairAgent(
        state_store=state_store,
        artifacts_dir=tmp_path / "artifacts",
        verifier=verifier,
    )
    result = agent.run(str(tmp_path))

    assert result["status"] == "success"
    assert result["patch_path"].endswith(".diff")
    assert result["source_tool"] == "slither"
