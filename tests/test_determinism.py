"""Tests for deterministic kernel output with parallel tool execution."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ralph_wiggum.kernel import Kernel
from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.quick_linter import QuickLinterRunner
from ralph_wiggum.tools.slither_runner import SlitherRunner


class StubSlitherRunner(SlitherRunner):
    """Stub Slither runner that writes fixture output without executing Slither."""

    def __init__(self, artifacts_dir: Path, payload: dict) -> None:
        super().__init__(artifacts_dir=artifacts_dir)
        self._payload = payload

    def run(self, target_path: str, timeout_seconds: int = 300) -> dict:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "slither.json").write_text(json.dumps(self._payload))
        (self.artifacts_dir / "slither.log").write_text("stub slither log")
        return self._payload


def _run_kernel(base_path: Path, parallel: bool) -> tuple[str, str]:
    base_path.mkdir(parents=True, exist_ok=True)
    artifacts_dir = base_path / "artifacts"
    state_path = base_path / "state.json"
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    if state_path.exists():
        state_path.unlink()

    state_store = StateStore(state_path)
    state_store.save(
        {
            "capabilities": {"executed": [], "skipped": []},
            "budget": {"spent": 1, "cap": 1},
        }
    )

    fixture_path = Path(__file__).parent / "fixtures" / "slither.json"
    slither_payload = json.loads(fixture_path.read_text())

    contracts_dir = base_path / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "Example.sol").write_text("// TODO: review\n")

    kernel = Kernel(
        state_store=state_store,
        artifacts_dir=artifacts_dir,
        parallel_tools=parallel,
        slither_runner=StubSlitherRunner(artifacts_dir, slither_payload),
        quick_linters=[QuickLinterRunner(artifacts_dir)],
    )
    report_path = kernel.run(str(base_path))
    return state_store.path.read_text(), report_path.read_text()


def test_parallel_runs_are_deterministic(tmp_path: Path) -> None:
    """Running with parallel tool execution should be deterministic."""
    base_path = tmp_path / "workspace"
    first_state, first_report = _run_kernel(base_path, parallel=True)
    second_state, second_report = _run_kernel(base_path, parallel=True)

    assert first_state == second_state
    assert first_report == second_report


def test_parallel_matches_sequential_output(tmp_path: Path) -> None:
    """Parallel and sequential tool execution should produce identical output."""
    base_path = tmp_path / "workspace"
    parallel_state, parallel_report = _run_kernel(base_path, parallel=True)
    sequential_state, sequential_report = _run_kernel(base_path, parallel=False)

    assert parallel_state == sequential_state
    assert parallel_report == sequential_report
