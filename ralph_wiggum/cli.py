"""Command-line interface for the Ralph Wiggum auditor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ralph_wiggum.kernel import Kernel
from ralph_wiggum.reporting import ReportGenerator
from ralph_wiggum.scoring import Scorer
from ralph_wiggum.state import StateStore
from ralph_wiggum.diff_review import DifferentialReview
from ralph_wiggum.workbench.workbench import Workbench


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the auditor."""
    parser = argparse.ArgumentParser(prog="ralph", description="Ralph Wiggum auditor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit a target path")
    audit_parser.add_argument("target_path", help="Path to a smart contract project")
    audit_parser.add_argument(
        "--offline-fixtures",
        action="store_true",
        help="Use offline HTTP fixtures for Solodit/LLM adapters",
    )

    replay_parser = subparsers.add_parser("replay", help="Replay a prior run")
    replay_parser.add_argument("run_path", help="Run directory or state.json path")
    replay_parser.add_argument(
        "--rerun-tools",
        action="store_true",
        help="Re-run tools during replay (default: no)",
    )
    replay_parser.add_argument(
        "--offline-fixtures",
        action="store_true",
        help="Use offline HTTP fixtures when rerunning tools",
    )

    score_parser = subparsers.add_parser("score", help="Score a prior run")
    score_parser.add_argument("run_path", help="Run directory or state.json path")

    trend_parser = subparsers.add_parser("trend", help="Track findings across runs")
    trend_parser.add_argument("runs_root", help="Root directory of run folders")

    entrypoints_parser = subparsers.add_parser("entrypoints", help="Analyze entry points")
    entrypoints_parser.add_argument("target_path", help="Path to a smart contract project")

    workbench_parser = subparsers.add_parser("workbench", help="Run workbench tasks")
    workbench_parser.add_argument("target_path", help="Path to a smart contract project")

    diff_parser = subparsers.add_parser("diff", help="Run differential review between refs")
    diff_parser.add_argument("base_ref", help="Base git ref")
    diff_parser.add_argument("head_ref", help="Head git ref")
    diff_parser.add_argument("--target", required=True, help="Target path within repo")

    return parser


def run_audit(target_path: str, offline_fixtures: bool = False) -> Path:
    """Run the placeholder audit workflow and write a report."""
    state_store = StateStore(Path("state.json"))
    kernel = Kernel(state_store=state_store, offline_fixtures=offline_fixtures)
    return kernel.run(target_path)


def run_replay(run_path: str, rerun_tools: bool = False, offline_fixtures: bool = False) -> Path:
    """Replay a previous run by regenerating the report."""
    state_path, artifacts_dir = resolve_run_paths(run_path)
    state_store = StateStore(state_path)
    state = state_store.load()
    if rerun_tools:
        target_path = state.get("target_path")
        if not target_path:
            raise RuntimeError("Replay requires target_path in state when rerun-tools is enabled")
        kernel = Kernel(
            state_store=state_store,
            artifacts_dir=artifacts_dir,
            offline_fixtures=offline_fixtures,
        )
        return kernel.run(target_path)

    replay_dir = artifacts_dir / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    report_path = ReportGenerator(replay_dir).write_report(state)
    summary_path = replay_dir / "replay_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "capabilities": state.get("capabilities", {"executed": {}, "skipped": {}}),
                "source_state": str(state_path),
            },
            indent=2,
        )
        + "\n"
    )
    state["replay"] = {
        "report_path": str(report_path),
        "summary_path": str(summary_path),
    }
    state_store.save(state)
    return report_path


def run_score(run_path: str) -> dict[str, Path]:
    """Compute a scoreboard for a previous run."""
    state_path, artifacts_dir = resolve_run_paths(run_path)
    state_store = StateStore(state_path)
    state = state_store.load()
    scorer = Scorer()
    scoreboard = scorer.build_scoreboard(state, run_root=artifacts_dir.parent)
    score_dir = artifacts_dir / "score"
    score_dir.mkdir(parents=True, exist_ok=True)
    json_path = score_dir / "scoreboard.json"
    md_path = score_dir / "scoreboard.md"
    json_path.write_text(json.dumps(scoreboard, indent=2) + "\n")
    md_path.write_text(scorer.format_scoreboard_markdown(scoreboard) + "\n")
    state["scoreboard"] = {
        "summary": scoreboard.get("summary", {}),
        "top_finding_ids": [entry["finding_id"] for entry in scoreboard.get("entries", [])[:3]],
        "artifact_paths": [str(json_path), str(md_path)],
    }
    state_store.save(state)
    return {"json": json_path, "md": md_path}


def run_trend(runs_root: str) -> dict[str, Path]:
    """Generate a trend report across multiple runs."""
    root_path = Path(runs_root)
    run_dirs = sorted([path for path in root_path.iterdir() if path.is_dir()])
    scorer = Scorer()
    trend_entries: list[dict[str, Any]] = []
    previous_scores: dict[str, dict[str, Any]] = {}
    previous_ids: set[str] = set()

    for run_dir in run_dirs:
        state_path = run_dir / "state.json"
        if not state_path.exists():
            continue
        state = StateStore(state_path).load()
        scoreboard = scorer.build_scoreboard(state, run_root=run_dir, previous_scores=previous_scores)
        entries = scoreboard.get("entries", [])
        current_ids = {entry["finding_id"] for entry in entries}
        regressed = [entry for entry in entries if entry.get("status") == "regressed"]
        regressed_sorted = sorted(regressed, key=lambda item: (-item["score_total"], item["finding_id"]))
        trend_entries.append(
            {
                "run": run_dir.name,
                "summary": {
                    "new": len(current_ids - previous_ids),
                    "resolved": len(previous_ids - current_ids),
                    "regressed": len(regressed),
                },
                "budget": state.get("budget", {}),
                "top_regressed": [
                    {
                        "finding_id": entry["finding_id"],
                        "title": entry["title"],
                        "score_total": entry["score_total"],
                    }
                    for entry in regressed_sorted[:3]
                ],
            }
        )
        previous_scores = {entry["finding_id"]: entry for entry in entries}
        previous_ids = current_ids

    trend_dir = root_path / "artifacts" / "trend"
    trend_dir.mkdir(parents=True, exist_ok=True)
    json_path = trend_dir / "trend.json"
    md_path = trend_dir / "trend.md"
    trend_payload = {"runs": trend_entries}
    json_path.write_text(json.dumps(trend_payload, indent=2) + "\n")
    md_path.write_text(_format_trend_markdown(trend_entries) + "\n")
    return {"json": json_path, "md": md_path}


def _format_trend_markdown(entries: list[dict[str, Any]]) -> str:
    lines = ["# Ralph Wiggum Trend Report", "", "## Findings Over Time"]
    for entry in entries:
        summary = entry["summary"]
        lines.append(
            f"- {entry['run']}: new={summary['new']} resolved={summary['resolved']} regressed={summary['regressed']}"
        )
    if not entries:
        lines.append("- No runs found.")

    lines.extend(["", "## Top Regressed Findings"])
    for entry in entries:
        if not entry["top_regressed"]:
            continue
        lines.append(f"- {entry['run']}:")
        for finding in entry["top_regressed"]:
            lines.append(
                f"  - {finding['finding_id']}: {finding['title']} (score {finding['score_total']})"
            )
    return "\n".join(lines)


def run_entrypoints(target_path: str) -> Path:
    """Run the entry point analyzer and write workbench artifacts."""
    state_store = StateStore(Path("state.json"))
    workbench = Workbench(state_store=state_store, artifacts_dir=Path("artifacts"))
    workbench.run_entrypoints(target_path)
    return Path("artifacts") / "workbench" / "entrypoints.json"


def run_workbench(target_path: str) -> dict[str, str]:
    """Run all workbench tasks and return artifact paths."""
    state_store = StateStore(Path("state.json"))
    workbench = Workbench(state_store=state_store, artifacts_dir=Path("artifacts"))
    workbench.run_all(target_path)
    return {
        "entrypoints": str(Path("artifacts") / "workbench" / "entrypoints.json"),
        "secure_contracts": str(Path("artifacts") / "workbench" / "secure_contracts.json"),
    }


def run_diff_review(base_ref: str, head_ref: str, target_path: str) -> dict[str, str]:
    """Run differential review and return artifact paths."""
    state_store = StateStore(Path("state.json"))
    review = DifferentialReview(state_store=state_store, artifacts_dir=Path("artifacts"), repo_path=Path("."))
    review.run(base_ref, head_ref, target_path)
    return {
        "changed_files": str(Path("artifacts") / "diff" / "changed_files.json"),
        "delta_report": str(Path("artifacts") / "diff" / "delta_report.json"),
        "delta_report_md": str(Path("artifacts") / "diff" / "delta_report.md"),
    }


def resolve_run_paths(run_path: str) -> tuple[Path, Path]:
    """Resolve state.json and artifacts directory from a run path."""
    candidate = Path(run_path)
    if candidate.is_dir():
        state_path = candidate / "state.json"
        artifacts_dir = candidate / "artifacts"
    else:
        state_path = candidate
        artifacts_dir = candidate.parent / "artifacts"
    return state_path, artifacts_dir


def main() -> int:
    """Entry point for the ralph CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "audit":
        run_audit(args.target_path, offline_fixtures=args.offline_fixtures)
        return 0
    if args.command == "replay":
        run_replay(
            args.run_path,
            rerun_tools=args.rerun_tools,
            offline_fixtures=args.offline_fixtures,
        )
        return 0
    if args.command == "score":
        output = run_score(args.run_path)
        print(output["md"].read_text())
        return 0
    if args.command == "trend":
        output = run_trend(args.runs_root)
        print(output["md"].read_text())
        return 0
    if args.command == "entrypoints":
        run_entrypoints(args.target_path)
        return 0
    if args.command == "workbench":
        run_workbench(args.target_path)
        return 0
    if args.command == "diff":
        run_diff_review(args.base_ref, args.head_ref, args.target)
        return 0

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
