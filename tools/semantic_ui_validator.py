#!/usr/bin/env python3
"""Validate semantic UI journeys against an MSF UI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"input", "select", "toggle", "button", "tab", "disclosure", "region"}
ALLOWED_ACTIONS = {"set", "clear", "focus", "select", "toggle", "click", "wait", "expect"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def validate(contract: dict[str, Any], journey: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "msf.semantic_ui_contract.v1":
        errors.append("contract_invalid: unsupported schema_version")
    if not isinstance(contract.get("app"), str) or not contract["app"]:
        errors.append("contract_invalid: app must be a non-empty string")
    elements = contract.get("controls")
    if not isinstance(elements, dict) or not elements:
        errors.append("contract_invalid: controls must be a non-empty object")

    for target, definition in elements.items():
        if not isinstance(target, str) or not isinstance(definition, dict):
            errors.append(f"contract_invalid: malformed element {target!r}")
            continue
        element_type = definition.get("type")
        if element_type not in ALLOWED_TYPES:
            errors.append(f"contract_invalid: {target} has unsupported type {element_type!r}")
        for action in definition.get("actions", []):
            if action not in ALLOWED_ACTIONS:
                errors.append(f"contract_invalid: {target} has unsupported action {action!r}")
        if not isinstance(definition.get("states"), list) or not definition["states"]:
            errors.append(f"contract_invalid: {target} must define states")

    if not isinstance(journey.get("journey_id"), str) or not journey["journey_id"]:
        errors.append("journey_invalid: journey_id must be a non-empty string")
    steps = journey.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("journey_invalid: steps must be a non-empty list")
        return errors

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"journey_invalid: step {index} is not an object")
            continue
        action = step.get("action")
        target = step.get("target")
        if action not in ALLOWED_ACTIONS:
            errors.append(f"journey_invalid: step {index} has unsupported action {action!r}")
            continue
        if not isinstance(target, str) or target not in elements:
            errors.append(f"journey_invalid: step {index} target_not_in_contract: {target!r}")
            continue
        definition = elements[target]
        if action not in {"wait", "expect"} and action not in definition.get("actions", []):
            errors.append(f"journey_invalid: step {index} action_not_allowed: {action} on {target}")
        if action in {"wait", "expect"}:
            state = step.get("state")
            if state not in definition.get("states", []):
                errors.append(f"journey_invalid: step {index} state_not_declared: {state!r} on {target}")
        if action in {"set", "select"} and "value" not in step:
            errors.append(f"journey_invalid: step {index} {action} requires value")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate semantic UI journeys against an MSF contract")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--journey", required=True)
    args = parser.parse_args()
    errors = validate(load_json(Path(args.contract)), load_json(Path(args.journey)))
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
