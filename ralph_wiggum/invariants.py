"""Invariant validation for kernel state."""
from __future__ import annotations

from typing import Any


def validate_state(state: dict[str, Any]) -> list[str]:
    """Validate state invariants and return a list of error messages."""
    errors: list[str] = []
    _check_budget(state, errors)
    _check_escalation(state, errors)
    _check_findings(state, errors)
    _check_capabilities(state, errors)
    return errors


def _check_budget(state: dict[str, Any], errors: list[str]) -> None:
    budget = state.get("budget")
    if not isinstance(budget, dict):
        return
    spent = budget.get("spent")
    cap = budget.get("cap")
    last_spent = budget.get("last_spent", spent)
    if spent is None:
        return
    if last_spent is not None and spent < last_spent:
        errors.append("Budget spent decreased from previous value.")
    if cap is not None and spent > cap:
        errors.append("Budget spent exceeds budget cap.")
    budget["last_spent"] = spent


def _check_escalation(state: dict[str, Any], errors: list[str]) -> None:
    current = state.get("escalation_level")
    if current is None:
        return
    previous = state.get("escalation_previous", current)
    if current < previous and not state.get("escalation_reason"):
        errors.append("Escalation level decreased without justification.")
    state["escalation_previous"] = current


def _check_findings(state: dict[str, Any], errors: list[str]) -> None:
    findings = []
    if isinstance(state.get("findings"), list):
        findings.extend(state["findings"])
    static_findings = state.get("static_scan", {}).get("findings")
    if isinstance(static_findings, list):
        findings.extend(static_findings)

    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"Finding {idx} is not a mapping.")
            continue
        for field in ("source_tool", "artifact_paths", "confidence"):
            if field not in finding:
                errors.append(f"Finding {idx} missing provenance field: {field}.")


def _check_capabilities(state: dict[str, Any], errors: list[str]) -> None:
    capabilities = state.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append("Capabilities section missing from state.")
        return
    if "executed" not in capabilities or "skipped" not in capabilities:
        errors.append("Capabilities missing executed/skipped lists.")
        return
    for bucket in ("executed", "skipped"):
        entries = capabilities.get(bucket, [])
        if not isinstance(entries, list):
            errors.append(f"Capabilities {bucket} is not a list.")
            continue
        for entry in entries:
            if isinstance(entry, str):
                continue
            if not isinstance(entry, dict):
                errors.append(f"Capabilities {bucket} entry is not a mapping.")
                continue
            if "name" not in entry or "reason" not in entry:
                errors.append(f"Capabilities {bucket} entry missing name/reason.")
