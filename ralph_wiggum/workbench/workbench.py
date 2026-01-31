"""Workbench orchestration for entrypoint and secure contracts tasks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ralph_wiggum.state import StateStore
from ralph_wiggum.tools.workbench_runner import WorkbenchSlitherRunner
from ralph_wiggum.workbench.entrypoints import EntryPointAnalyzer
from ralph_wiggum.workbench.secure_contracts import SecureContractsToolkit


@dataclass
class Workbench:
    """Run workbench tasks aligned with pre-compiled runbooks."""

    state_store: StateStore
    artifacts_dir: Path

    def run_entrypoints(self, target_path: str) -> dict[str, Any]:
        runner = WorkbenchSlitherRunner(self.artifacts_dir)
        analyzer = EntryPointAnalyzer(
            state_store=self.state_store,
            artifacts_dir=self.artifacts_dir,
            slither_runner=runner,
        )
        return analyzer.run(target_path)

    def run_secure_contracts(self, target_path: str) -> dict[str, Any]:
        runner = WorkbenchSlitherRunner(self.artifacts_dir)
        toolkit = SecureContractsToolkit(
            state_store=self.state_store,
            artifacts_dir=self.artifacts_dir,
            slither_runner=runner,
        )
        return toolkit.run(target_path)

    def run_all(self, target_path: str) -> dict[str, Any]:
        entrypoints = self.run_entrypoints(target_path)
        secure_contracts = self.run_secure_contracts(target_path)
        return {"entrypoints": entrypoints, "secure_contracts": secure_contracts}
