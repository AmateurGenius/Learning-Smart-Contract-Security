"""Proof agent that derives invariant templates from findings."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ralph_wiggum.scoring import collect_findings, score_findings
from ralph_wiggum.state import StateStore


@dataclass
class ProofAgent:
    """Generate Foundry-style invariant stubs from top findings."""

    state_store: StateStore
    artifacts_dir: Path
    top_n: int = 3

    def run(self) -> list[Path]:
        """Generate invariant files and persist proof metadata."""
        state = self.state_store.load()
        findings = score_findings(collect_findings(state))
        if not findings:
            state["proofs"] = {"status": "skipped", "reason": "no_findings", "artifacts": []}
            self.state_store.save(state)
            return []

        proofs_dir = self.artifacts_dir / "proofs"
        proofs_dir.mkdir(parents=True, exist_ok=True)

        written: list[Path] = []
        proof_entries: list[dict[str, Any]] = []
        for idx, item in enumerate(findings[: self.top_n], start=1):
            finding = item.get("finding", {})
            category = str(finding.get("category", "finding"))
            slug = category.replace(" ", "_").replace("/", "_").lower()
            file_path = proofs_dir / f"invariant_{idx}_{slug}.sol"
            invariant_name = f"invariant_{idx}_{slug}"
            description = str(finding.get("description", "invariant"))
            content = "\n".join(
                [
                    "// SPDX-License-Identifier: UNLICENSED",
                    "pragma solidity ^0.8.13;",
                    "",
                    f"// Invariant derived from finding: {description}",
                    "contract ProofInvariant {",
                    f"    function {invariant_name}() external view {{",
                    "        // TODO: encode property check.",
                    "    }",
                    "}",
                    "",
                ]
            )
            file_path.write_text(content)
            written.append(file_path)
            proof_entries.append(
                {
                    "path": str(file_path),
                    "source_tool": finding.get("source_tool", "unknown"),
                    "category": finding.get("category", "unknown"),
                    "description": description,
                }
            )

        state["proofs"] = {"status": "generated", "artifacts": [str(p) for p in written], "entries": proof_entries}
        self.state_store.save(state)
        return written
