"""Tests for replay, scoreboards, and trend reporting."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ralph_wiggum.cli import run_replay, run_score, run_trend
from ralph_wiggum.scoring import Scorer


def _prepare_run(tmp_path: Path, name: str) -> Path:
    fixture_root = Path(__file__).parent / "fixtures" / "runs" / name
    run_dir = tmp_path / name
    shutil.copytree(fixture_root, run_dir)
    return run_dir


def test_replay_writes_summary(tmp_path: Path) -> None:
    """Replay should regenerate the report and summary without rerunning tools."""
    run_dir = _prepare_run(tmp_path, "run_a")
    report_path = run_replay(str(run_dir))
    replay_dir = run_dir / "artifacts" / "replay"
    summary_path = replay_dir / "replay_summary.json"

    assert report_path.exists()
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert "static_scan" in summary["capabilities"]["executed"]


def test_scoreboard_output_is_deterministic(tmp_path: Path) -> None:
    """Scoreboard artifacts should be deterministic for a fixed run."""
    run_dir = _prepare_run(tmp_path, "run_a")
    output = run_score(str(run_dir))
    json_path = output["json"]
    md_path = output["md"]

    snapshot_json = Path(__file__).parent / "fixtures" / "snapshots" / "scoreboard_run_a.json"
    snapshot_md = Path(__file__).parent / "fixtures" / "snapshots" / "scoreboard_run_a.md"

    assert json.loads(json_path.read_text()) == json.loads(snapshot_json.read_text())
    assert md_path.read_text().strip() == snapshot_md.read_text().strip()

    output_repeat = run_score(str(run_dir))
    assert output_repeat["json"].read_text() == json_path.read_text()
    assert output_repeat["md"].read_text() == md_path.read_text()


def test_finding_id_stability(tmp_path: Path) -> None:
    """Finding IDs should be stable across runs for the same finding."""
    run_a = _prepare_run(tmp_path, "run_a")
    run_b = _prepare_run(tmp_path, "run_b")

    scorer = Scorer()
    state_a = json.loads((run_a / "state.json").read_text())
    state_b = json.loads((run_b / "state.json").read_text())
    score_a = scorer.build_scoreboard(state_a, run_root=run_a)
    score_b = scorer.build_scoreboard(state_b, run_root=run_b)

    a_ids = {entry["finding_id"] for entry in score_a["entries"]}
    b_ids = {entry["finding_id"] for entry in score_b["entries"]}

    assert a_ids.intersection(b_ids)


def test_trend_report(tmp_path: Path) -> None:
    """Trend reports should classify new/resolved/regressed deterministically."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    shutil.copytree(Path(__file__).parent / "fixtures" / "runs" / "run_a", runs_root / "run_a")
    shutil.copytree(Path(__file__).parent / "fixtures" / "runs" / "run_b", runs_root / "run_b")

    output = run_trend(str(runs_root))
    trend_json = json.loads(output["json"].read_text())
    trend_md = output["md"].read_text()

    assert trend_json["runs"][0]["summary"] == {"new": 2, "resolved": 0, "regressed": 0}
    assert trend_json["runs"][1]["summary"] == {"new": 0, "resolved": 1, "regressed": 1}
    assert "Top Regressed Findings" in trend_md
