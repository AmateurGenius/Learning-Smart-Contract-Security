"""End-to-end CLI integration tests for the run & verify harness."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(cwd: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "ralph_wiggum.cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result


def _make_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["RALPH_OFFLINE"] = "1"
    return env


def _prepare_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir()
    fixture_slither = REPO_ROOT / "tests" / "fixtures" / "slither.json"
    shutil.copy(fixture_slither, artifacts_dir / "slither.json")
    state = {
        "budget": {"cap": 1, "spent": 1},
        "capabilities": {"executed": [], "skipped": []},
    }
    (workspace / "state.json").write_text(json.dumps(state, indent=2))
    return workspace


def _copy_contract_fixture(target_root: Path) -> Path:
    fixture_dir = REPO_ROOT / "tests" / "fixtures" / "contracts"
    contracts_dir = target_root / "contracts"
    shutil.copytree(fixture_dir, contracts_dir)
    return contracts_dir


def _create_diff_repo(base_path: Path) -> tuple[Path, str, str]:
    repo = base_path / "diff_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    contracts_dir = repo / "contracts"
    contracts_dir.mkdir()
    vault_path = contracts_dir / "Vault.sol"
    vault_path.write_text("pragma solidity ^0.8.13;\ncontract Vault { function withdraw() public {} }\n")
    subprocess.run(["git", "add", "contracts/Vault.sol"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    vault_path.write_text(
        "pragma solidity ^0.8.13;\ncontract Vault { function withdraw() public { (bool ok,) = address(0).call(\"\"); ok; } }\n"
    )
    subprocess.run(["git", "add", "contracts/Vault.sol"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "head"], cwd=repo, check=True)
    head_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, base_ref, head_ref


def test_cli_run_and_verify(tmp_path: Path) -> None:
    """Run audit/workbench/diff CLI commands against fixtures."""
    env = _make_env()
    workspace = _prepare_workspace(tmp_path)
    target_path = _copy_contract_fixture(workspace)

    _run_cli(workspace, "audit", str(target_path), env=env)
    report_path = workspace / "artifacts" / "report.md"
    assert report_path.exists()
    assert "Capabilities Executed / Skipped" in report_path.read_text()

    _run_cli(workspace, "workbench", str(target_path), env=env)
    entrypoints_path = workspace / "artifacts" / "workbench" / "entrypoints.json"
    assert entrypoints_path.exists()

    _run_cli(workspace, "entrypoints", str(target_path), env=env)
    assert entrypoints_path.exists()

    repo, base_ref, head_ref = _create_diff_repo(tmp_path)
    _run_cli(repo, "diff", base_ref, head_ref, "--target", "contracts", env=env)
    diff_dir = repo / "artifacts" / "diff"
    assert (diff_dir / "delta_report.json").exists()
    assert (diff_dir / "delta_report.md").exists()


def test_workbench_output_is_deterministic(tmp_path: Path) -> None:
    """Workbench output should be deterministic across runs."""
    env = _make_env()
    workspace = _prepare_workspace(tmp_path)
    target_path = _copy_contract_fixture(workspace)

    _run_cli(workspace, "workbench", str(target_path), env=env)
    entrypoints_path = workspace / "artifacts" / "workbench" / "entrypoints.json"
    secure_path = workspace / "artifacts" / "workbench" / "secure_contracts.json"
    first_entrypoints = entrypoints_path.read_text()
    first_secure = secure_path.read_text()

    _run_cli(workspace, "workbench", str(target_path), env=env)
    assert entrypoints_path.read_text() == first_entrypoints
    assert secure_path.read_text() == first_secure
