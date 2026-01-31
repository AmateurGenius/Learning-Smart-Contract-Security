"""Concurrency helper for running independent tool runners deterministically."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class ToolJob:
    """Represents an independent tool execution job."""

    name: str
    runner: Callable[[], "ToolResult"]


@dataclass
class ToolResult:
    """Represents the output from a tool execution."""

    name: str
    artifacts: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    payload: Any | None = None


class RunnerPool:
    """Runs tool jobs sequentially or in parallel with deterministic merging."""

    def __init__(self, parallel: bool = False, max_workers: int | None = None) -> None:
        self.parallel = parallel
        self.max_workers = max_workers

    def run(self, jobs: Iterable[ToolJob]) -> list[ToolResult]:
        """Execute jobs and return results sorted by name."""
        job_list = list(jobs)
        if not self.parallel or len(job_list) <= 1:
            results = [job.runner() for job in job_list]
            return sorted(results, key=lambda result: result.name)

        results: list[ToolResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(job.runner): job.name for job in job_list}
            for future in as_completed(future_map):
                result = future.result()
                results.append(result)

        return sorted(results, key=lambda result: result.name)

    @staticmethod
    def merge_artifacts(results: Iterable[ToolResult]) -> list[str]:
        """Return a deterministic, sorted list of artifacts."""
        artifacts = {artifact for result in results for artifact in result.artifacts}
        return sorted(artifacts)

    @staticmethod
    def merge_findings(results: Iterable[ToolResult]) -> list[dict[str, Any]]:
        """Return a deterministic, sorted list of findings."""
        findings: list[dict[str, Any]] = []
        for result in results:
            findings.extend(result.findings)
        return sorted(findings, key=RunnerPool._finding_sort_key)

    @staticmethod
    def _finding_sort_key(finding: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
        """Generate a deterministic sort key for findings."""
        return (
            str(finding.get("source_tool", "")),
            str(finding.get("category", "")),
            str(finding.get("check", "")),
            str(finding.get("description", "")),
            str(finding.get("path", "")),
            str(finding.get("lines", "")),
        )
