# Ralph Wiggum

Ralph Wiggum is a Python 3.11-ready skeleton for an autonomous multi-agent smart contract auditor. The project is intentionally lightweight and ships placeholder modules with docstrings only so teams can fill in the operational logic later.

## Features (Planned)
- Kernel loop for orchestrating agent execution.
- Budget tracking and kill switch controls.
- State persistence via `state.json`.
- Escalation router with levels 0-3.
- Agents:
  - StaticScan (Slither wrapper)
  - GraphAnalysis (from Slither JSON)
  - SoloditBooster (stub client)
  - LLMSynthesis (OpenAI-compatible vLLM adapter)
- CLI: `ralph audit <target_path>` writes output to `artifacts/report.md`.

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
# Optional: install dev tooling (pytest)
pip install -e ".[dev]"
# Optional: install graph tooling (networkx)
pip install -e ".[graph]"
python -m ralph_wiggum.cli audit ./contracts
```

## Replay, Score, and Trend
```bash
# Regenerate a report from a prior run (offline by default)
python -m ralph_wiggum.cli replay ./runs/run_a

# Generate a scoreboard for a run
python -m ralph_wiggum.cli score ./runs/run_a

# Track regressions across multiple runs
python -m ralph_wiggum.cli trend ./runs
```

## Repository Layout
```
artifacts/
ralph_wiggum/
  agents/
tests/
state.json
```

## Notes
This repository is scaffolding only. The modules include docstrings to guide implementation without committing to specific logic yet.
