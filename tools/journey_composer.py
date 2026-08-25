#!/usr/bin/env python3
"""Compose canonical MSF semantic journeys from a UI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.semantic_ui_validator import load_json
except ModuleNotFoundError:
    from semantic_ui_validator import load_json


class JourneyComposer:
    """Small contract-driven authoring surface for canonical journey objects."""

    def __init__(self, contract: dict[str, Any]):
        if contract.get("schema_version") != "msf.semantic_ui_contract.v1":
            raise ValueError("Unsupported semantic UI contract")
        controls = contract.get("controls")
        if not isinstance(controls, dict) or not controls:
            raise ValueError("Contract controls must be a non-empty object")
        self._controls = controls

    @classmethod
    def from_path(cls, path: Path) -> "JourneyComposer":
        return cls(load_json(path))

    def targets(self) -> list[str]:
        return sorted(self._controls)

    def actions_for(self, target: str) -> list[str]:
        return self._definition(target).get("actions", [])

    def states_for(self, target: str, operation: str) -> list[str]:
        if operation not in {"wait", "expect"}:
            return []
        return self._definition(target).get("states", [])

    def add_step(
        self,
        steps: list[dict[str, Any]],
        action: str,
        target: str,
        *,
        value: Any = None,
        state: str | None = None,
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        definition = self._definition(target)
        if action not in {"set", "clear", "focus", "select", "toggle", "click", "wait", "expect"}:
            raise ValueError(f"Unsupported action: {action}")
        if action not in {"wait", "expect"} and action not in definition.get("actions", []):
            raise ValueError(f"Action {action!r} is not permitted for {target!r}")
        if action in {"wait", "expect"} and state not in definition.get("states", []):
            raise ValueError(f"State {state!r} is not valid for {target!r}")
        if action in {"set", "select"} and value is None:
            raise ValueError(f"Action {action!r} requires a value")

        step: dict[str, Any] = {"action": action, "target": target}
        if action in {"set", "select"}:
            step["value"] = value
        if action in {"wait", "expect"}:
            step["state"] = state
        if action == "wait" and timeout_ms is not None:
            step["timeout_ms"] = timeout_ms
        steps.append(step)
        return steps

    def compose(self, journey_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        if not journey_id:
            raise ValueError("journey_id must be non-empty")
        return {"journey_id": journey_id, "steps": steps}

    def _definition(self, target: str) -> dict[str, Any]:
        if target not in self._controls:
            raise ValueError(f"Unknown semantic target: {target}")
        definition = self._controls[target]
        if not isinstance(definition, dict):
            raise ValueError(f"Malformed control definition: {target}")
        return definition


def parse_step(raw: str) -> dict[str, Any]:
    try:
        step = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("--step must be a canonical JSON step object") from exc
    if not isinstance(step, dict):
        raise ValueError("--step must be a JSON object")
    return step


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose a canonical MSF semantic journey")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--journey-id", default="")
    parser.add_argument("--step", action="append", default=[], help="Canonical JSON step object; repeat to order steps")
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    composer = JourneyComposer.from_path(Path(args.contract))
    if args.list_targets:
        for target in composer.targets():
            print(json.dumps({"target": target, "actions": composer.actions_for(target), "states": composer.states_for(target, "expect")}))
        return 0
    if not args.journey_id:
        parser.error("--journey-id is required unless --list-targets is used")

    steps: list[dict[str, Any]] = []
    for raw_step in args.step:
        candidate = parse_step(raw_step)
        composer.add_step(
            steps,
            candidate.get("action"),
            candidate.get("target"),
            value=candidate.get("value"),
            state=candidate.get("state"),
            timeout_ms=candidate.get("timeout_ms"),
        )
    journey = composer.compose(args.journey_id, steps)
    rendered = json.dumps(journey, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
