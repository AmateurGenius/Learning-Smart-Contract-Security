"""Scoring helpers for ranking findings and generating scoreboards."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ScoreWeights:
    """Configurable weights for scoring findings."""

    severity: dict[str, int]
    confidence: dict[str, int]
    evidence: int = 2
    repro: int = 1
    missing_evidence_penalty: int = 1
    skipped_capability_penalty: int = 1


DEFAULT_WEIGHTS = ScoreWeights(
    severity={"critical": 5, "high": 4, "medium": 2, "low": 1},
    confidence={"high": 3, "medium": 2, "low": 1},
)


def collect_findings(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect findings from state in a stable order."""
    findings: list[dict[str, Any]] = []
    if isinstance(state.get("findings"), list):
        findings.extend(state["findings"])
    static_findings = state.get("static_scan", {}).get("findings")
    if isinstance(static_findings, list):
        findings.extend(static_findings)
    return findings


def score_findings(
    findings: Iterable[dict[str, Any]],
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> list[dict[str, Any]]:
    """Compute scores for findings with deterministic ranking."""
    scored: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        severity = _normalize_level(finding.get("severity") or finding.get("impact"))
        confidence = _normalize_level(finding.get("confidence"))
        evidence_score = _evidence_strength(finding, weights)
        severity_score = weights.severity.get(severity, 0)
        confidence_score = weights.confidence.get(confidence, 0)
        total = evidence_score + severity_score + confidence_score
        scored.append(
            {
                "score": total,
                "severity": severity or "unknown",
                "confidence": confidence or "unknown",
                "source_tool": finding.get("source_tool", "unknown"),
                "category": finding.get("category", "unknown"),
                "description": finding.get("description", ""),
                "finding": finding,
            }
        )

    return sorted(scored, key=_score_sort_key)


def format_ranked_findings(scored: Iterable[dict[str, Any]]) -> str:
    """Format scored findings as a Markdown table."""
    rows = [
        "| Rank | Score | Severity | Confidence | Tool | Category | Description |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for idx, item in enumerate(scored, start=1):
        rows.append(
            "| {rank} | {score} | {severity} | {confidence} | {tool} | {category} | {description} |".format(
                rank=idx,
                score=item.get("score", 0),
                severity=item.get("severity", "unknown"),
                confidence=item.get("confidence", "unknown"),
                tool=item.get("source_tool", "unknown"),
                category=item.get("category", "unknown"),
                description=_truncate(item.get("description", "")),
            )
        )
    if len(rows) == 2:
        rows.append("| - | 0 | - | - | - | - | No findings scored. |")
    return "\n".join(rows)


@dataclass
class Scorer:
    """Generate deterministic scoreboards and trend summaries."""

    weights: ScoreWeights = DEFAULT_WEIGHTS
    skipped_capabilities: tuple[str, ...] = (
        "static_scan",
        "graph_analysis",
        "fuzz_agent",
        "proof_agent",
    )

    def build_scoreboard(
        self,
        state: dict[str, Any],
        run_root: Path,
        previous_scores: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a scoreboard payload for a single run."""
        findings = collect_findings(state)
        capabilities = state.get("capabilities", {"executed": [], "skipped": []})
        skipped_names = {
            entry.get("name")
            for entry in capabilities.get("skipped", [])
            if isinstance(entry, dict)
        }
        skipped_any = bool(skipped_names.intersection(self.skipped_capabilities))

        entries: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            entry = self._score_finding(
                finding,
                run_root=run_root,
                skipped_any=skipped_any,
                previous_scores=previous_scores,
            )
            entries.append(entry)

        entries = sorted(entries, key=lambda item: (-item["score_total"], item["finding_id"]))
        summary = {
            "total_findings": len(entries),
            "high_confidence": sum(1 for entry in entries if entry["confidence"] == "high"),
        }
        return {
            "summary": summary,
            "capabilities": capabilities,
            "entries": entries,
        }

    def format_scoreboard_markdown(self, scoreboard: dict[str, Any]) -> str:
        """Render scoreboard to deterministic Markdown."""
        lines = [
            "# Ralph Wiggum Scoreboard",
            "",
            "## Capabilities Executed / Skipped",
            f"- Executed: {self._format_capabilities(scoreboard.get('capabilities', {}).get('executed', [])) or 'None'}",
            f"- Skipped: {self._format_capabilities(scoreboard.get('capabilities', {}).get('skipped', [])) or 'None'}",
            "",
            "## Findings",
            "| Rank | Score | Status | Severity | Confidence | Evidence | Reproducible | Category | Title | Finding ID |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]

        entries = scoreboard.get("entries", [])
        if not entries:
            lines.append("| - | 0 | unknown | - | - | low | false | - | No findings | - |")
            return "\n".join(lines)

        for idx, entry in enumerate(entries, start=1):
            lines.append(
                "| {rank} | {score} | {status} | {severity} | {confidence} | {evidence} | {repro} | {category} | {title} | {finding_id} |".format(
                    rank=idx,
                    score=entry.get("score_total", 0),
                    status=entry.get("status", "unknown"),
                    severity=entry.get("severity", "unknown"),
                    confidence=entry.get("confidence", "unknown"),
                    evidence=entry.get("evidence_strength", "low"),
                    repro=str(entry.get("reproducible", False)).lower(),
                    category=entry.get("category", "unknown"),
                    title=_truncate(entry.get("title", "")),
                    finding_id=entry.get("finding_id", ""),
                )
            )
        return "\n".join(lines)

    def _score_finding(
        self,
        finding: dict[str, Any],
        run_root: Path,
        skipped_any: bool,
        previous_scores: dict[str, dict[str, Any]] | None,
    ) -> dict[str, Any]:
        title = self._finding_title(finding)
        category = str(finding.get("category", "unknown"))
        severity = _normalize_level(finding.get("severity") or finding.get("impact"))
        if not severity:
            severity = self._heuristic_severity(category)
        confidence = _normalize_level(finding.get("confidence"))
        if not confidence:
            confidence = "unknown"

        evidence_points, evidence_strength = self._evidence_strength(
            finding,
            run_root=run_root,
            skipped_any=skipped_any,
        )
        reproducible = self._is_reproducible(finding)
        repro_points = 1 if reproducible else 0
        severity_score = self.weights.severity.get(severity, 0)
        confidence_score = self.weights.confidence.get(confidence, 0)
        score_total = severity_score + confidence_score + evidence_points + repro_points

        finding_id = self.finding_id(finding, title=title, category=category)
        status = "unknown"
        if previous_scores is not None:
            previous = previous_scores.get(finding_id)
            if previous is None:
                status = "new"
            elif score_total > previous.get("score_total", 0):
                status = "regressed"
            else:
                status = "unchanged"

        return {
            "finding_id": finding_id,
            "title": title,
            "category": category,
            "severity": severity or "unknown",
            "confidence": confidence or "unknown",
            "evidence_strength": evidence_strength,
            "evidence_points": evidence_points,
            "reproducible": reproducible,
            "status": status,
            "score_total": score_total,
            "source_tool": finding.get("source_tool", "unknown"),
            "artifact_paths": finding.get("artifact_paths", []),
        }

    def finding_id(self, finding: dict[str, Any], title: str | None = None, category: str | None = None) -> str:
        """Generate a stable finding ID."""
        title_value = title or self._finding_title(finding)
        category_value = category or str(finding.get("category", "unknown"))
        location = self._finding_location(finding)
        raw = f"{title_value}|{category_value}|{location}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def _finding_title(self, finding: dict[str, Any]) -> str:
        return str(
            finding.get("title")
            or finding.get("description")
            or finding.get("check")
            or finding.get("category")
            or "finding"
        )

    def _finding_location(self, finding: dict[str, Any]) -> str:
        if finding.get("path"):
            return f"{finding.get('path')}:{finding.get('lines') or finding.get('line') or ''}"
        artifact_paths = finding.get("artifact_paths") or []
        if artifact_paths:
            return str(artifact_paths[0])
        return ""

    def _heuristic_severity(self, category: str) -> str:
        category_lower = category.lower()
        if "reentrancy" in category_lower or "dangerous" in category_lower:
            return "high"
        if "unchecked" in category_lower:
            return "medium"
        if "fuzz" in category_lower:
            return "medium"
        return "low"

    def _is_reproducible(self, finding: dict[str, Any]) -> bool:
        return bool(finding.get("repro") or finding.get("repro_steps") or finding.get("repro_path"))

    def _evidence_strength(
        self,
        finding: dict[str, Any],
        run_root: Path,
        skipped_any: bool,
    ) -> tuple[int, str]:
        evidence_points = 0
        has_provenance = bool(finding.get("source_tool"))
        artifact_paths = finding.get("artifact_paths") or []
        artifacts_valid = self._artifact_paths_valid(artifact_paths, run_root)
        if has_provenance and artifacts_valid:
            evidence_points += self.weights.evidence
        if not has_provenance or not artifacts_valid:
            evidence_points -= self.weights.missing_evidence_penalty
        if self._is_reproducible(finding):
            evidence_points += self.weights.repro
        if skipped_any:
            evidence_points -= self.weights.skipped_capability_penalty

        if evidence_points >= 3:
            evidence_strength = "high"
        elif evidence_points >= 1:
            evidence_strength = "medium"
        else:
            evidence_strength = "low"
        return evidence_points, evidence_strength

    def _artifact_paths_valid(self, artifact_paths: Iterable[str], run_root: Path) -> bool:
        for artifact in artifact_paths:
            path = Path(artifact)
            if not path.is_absolute():
                path = run_root / path
            if path.exists():
                return True
        return False

    def _format_capabilities(self, entries: list[Any]) -> str:
        formatted: list[str] = []
        for entry in entries:
            if isinstance(entry, str):
                formatted.append(entry)
                continue
            if isinstance(entry, dict):
                name = entry.get("name", "unknown")
                reason = entry.get("reason", "unknown")
                formatted.append(f"{name} ({reason})")
        return ", ".join(formatted)


def _normalize_level(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _evidence_strength(finding: dict[str, Any], weights: ScoreWeights) -> int:
    score = 0
    if finding.get("source_tool") and finding.get("artifact_paths"):
        score += weights.evidence
    if finding.get("repro") or finding.get("repro_steps") or finding.get("repro_path"):
        score += weights.repro
    return score


def _score_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str, str, str]:
    return (
        -int(item.get("score", 0)),
        -_severity_weight(item.get("severity")),
        -_confidence_weight(item.get("confidence")),
        str(item.get("source_tool", "")),
        str(item.get("category", "")),
        str(item.get("description", "")),
    )


def _severity_weight(level: Any) -> int:
    level_str = _normalize_level(level)
    return DEFAULT_WEIGHTS.severity.get(level_str, 0)


def _confidence_weight(level: Any) -> int:
    level_str = _normalize_level(level)
    return DEFAULT_WEIGHTS.confidence.get(level_str, 0)


def _truncate(value: Any, limit: int = 80) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
