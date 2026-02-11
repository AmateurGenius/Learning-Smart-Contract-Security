"""Tests for differential review mode."""
from __future__ import annotations

from pathlib import Path
import subprocess

from ralph_wiggum.diff_review import DifferentialReview
from ralph_wiggum.state import StateStore


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_diff_review_delta_outputs(tmp_path: Path) -> None:
    """Differential review should classify regressions deterministically."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    contracts_dir = repo / "contracts"
    contracts_dir.mkdir()
    vault_path = contracts_dir / "Vault.sol"
    vault_path.write_text(
        "pragma solidity ^0.8.13;\ncontract Vault { function withdraw() public {} }\n"
    )
    _git(repo, "add", "contracts/Vault.sol")
    _git(repo, "commit", "-m", "base")
    base_ref = _git(repo, "rev-parse", "HEAD")

    vault_path.write_text(
        "pragma solidity ^0.8.13;\ncontract Vault { function withdraw() public { (bool ok,) = address(0).call(\"\"); ok; } }\n"
    )
    _git(repo, "add", "contracts/Vault.sol")
    _git(repo, "commit", "-m", "head")
    head_ref = _git(repo, "rev-parse", "HEAD")

    state_store = StateStore(repo / "state.json")
    state_store.save({"status": "ready"})

    review = DifferentialReview(
        state_store=state_store,
        artifacts_dir=repo / "artifacts",
        repo_path=repo,
    )
    report = review.run(base_ref, head_ref, "contracts")

    assert report["changed_files"] == ["contracts/Vault.sol"]
    assert report["delta"]["regressed"] == ["dangerous_call"]
    assert report["delta"]["resolved"] == []
    assert report["delta"]["unchanged"] == []
    assert report["capabilities"]["static_scan"]["status"] == "skipped"

    delta_report_md = (repo / "artifacts" / "diff" / "delta_report.md").read_text()
    assert "Regressed: dangerous_call" in delta_report_md

    state = state_store.load()
    diff_state = state["diff_review"]
    assert diff_state["base_ref"] == base_ref
    assert diff_state["head_ref"] == head_ref
    for artifact_path in diff_state["artifact_paths"]:
        assert Path(artifact_path).exists()
