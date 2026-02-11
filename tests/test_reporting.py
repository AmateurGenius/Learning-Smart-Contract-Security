"""Tests for report generation."""
from __future__ import annotations

from pathlib import Path
from ralph_wiggum.reporting import ReportGenerator


def test_report_generator_writes_sections(tmp_path: Path) -> None:
    """Report generator should write standard sections even without LLM."""
    generator = ReportGenerator(artifacts_dir=tmp_path)
    state = {
        "static_scan": {
            "signals": {"reentrancy": 1},
            "evidence": [{"category": "reentrancy", "path": "file.sol"}],
        },
        "capabilities": {"executed": {"static_scan": {"status": "success"}}, "skipped": {}},
    }

    report_path = generator.write_report(state)

    content = report_path.read_text()
    assert "## Findings" in content
    assert "## Evidence" in content
    assert "## Recommendations" in content
    assert "## Ranked Findings" in content
    assert "## Capabilities Executed / Skipped" in content
    assert "static_scan" in content
    assert "## LLM Synthesis" in content
    assert "heuristic synthesis, not evidence" in content
