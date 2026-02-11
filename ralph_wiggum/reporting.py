"""Report generation helpers for the Ralph Wiggum auditor."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ralph_wiggum.scoring import collect_findings, format_ranked_findings, score_findings


@dataclass
class ReportGenerator:
    """Generate audit reports from stored state."""

    artifacts_dir: Path

    def write_report(self, state: dict[str, Any]) -> Path:
        """Write the report markdown and return its path."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.artifacts_dir / "report.md"

        llm_summary = state.get("llm_synthesis") or {"status": "unavailable", "summary": None}

        findings = state.get("static_scan", {}).get("signals", {})
        evidence = state.get("static_scan", {}).get("evidence", [])
        recommendations = self._recommendations(findings)
        capabilities = state.get("capabilities", {"executed": {}, "skipped": {}})
        invariant_errors = state.get("invariant_errors", [])
        ranked_findings = format_ranked_findings(score_findings(collect_findings(state)))

        lines = ["# Ralph Wiggum Audit Report", "", "## Findings"]
        if findings:
            for key, value in findings.items():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- No findings captured.")

        lines.extend(["", "## Evidence"])
        if evidence:
            for item in evidence:
                path = item.get("path") or "unknown"
                lines.append(f"- {item.get('category', 'unknown')} at {path}")
        else:
            lines.append("- No evidence captured.")

        lines.extend(["", "## Recommendations"])
        if recommendations:
            lines.extend([f"- {rec}" for rec in recommendations])
        else:
            lines.append("- No recommendations available.")

        lines.extend(["", "## Ranked Findings", ranked_findings])

        lines.extend(["", "## Capabilities Executed / Skipped"])
        executed = capabilities.get("executed", {})
        skipped = capabilities.get("skipped", {})
        lines.append(f"- Executed: {self._format_capabilities(executed) or 'None'}")
        lines.append(f"- Skipped: {self._format_capabilities(skipped) or 'None'}")

        lines.extend(["", "## LLM Synthesis", "_This section is heuristic synthesis, not evidence._"])
        if llm_summary.get("summary"):
            lines.append(llm_summary["summary"])
        elif llm_summary.get("status") == "error":
            error = llm_summary.get("error", "unknown error")
            lines.append(f"- LLM synthesis failed: {error}")
        else:
            lines.append("- LLM synthesis unavailable.")

        if invariant_errors:
            lines.extend(["", "## Errors"])
            lines.extend([f"- {error}" for error in invariant_errors])

        report_path.write_text("\n".join(lines) + "\n")
        return report_path

    def _recommendations(self, findings: dict[str, Any]) -> list[str]:
        """Generate placeholder recommendations based on findings."""
        recommendations = []
        if findings.get("reentrancy"):
            recommendations.append("Review reentrancy guards and external call ordering.")
        if findings.get("unchecked_return"):
            recommendations.append("Handle return values from external calls.")
        if findings.get("delegatecall"):
            recommendations.append("Audit delegatecall usage for storage safety.")
        return recommendations

    def _format_capabilities(self, entries: Any) -> str:
        """Format capability entries with reasons."""
        if isinstance(entries, dict):
            formatted = []
            for name in sorted(entries.keys()):
                payload = entries[name]
                if isinstance(payload, dict):
                    reason = payload.get("reason") or payload.get("status", "unknown")
                    formatted.append(f"{name} ({reason})")
                else:
                    formatted.append(str(name))
            return ", ".join(formatted)
        return ""
