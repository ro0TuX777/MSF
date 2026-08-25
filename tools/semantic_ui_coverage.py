#!/usr/bin/env python3
"""Validate live semantic UI coverage against an approved MSF contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.semantic_retrofit import discover_runtime
    from tools.semantic_ui_validator import load_json
except ModuleNotFoundError:
    from semantic_retrofit import discover_runtime
    from semantic_ui_validator import load_json


def validate_coverage(report: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    contract_ids = set(contract.get("controls", {}))
    rendered_ids = {candidate["semantic_id"] for candidate in report.get("candidates", []) if candidate.get("semantic_id")}
    errors: list[str] = []
    for target in sorted(contract_ids - rendered_ids):
        errors.append(f"missing_rendered_control: {target}")
    for target in sorted(rendered_ids - contract_ids):
        errors.append(f"uncontracted_rendered_control: {target}")
    for candidate in report.get("candidates", []):
        target = candidate.get("semantic_id")
        if target in contract_ids:
            runtime_state = candidate.get("runtime", {}).get("state")
            if runtime_state not in contract["controls"][target].get("states", []):
                errors.append(f"invalid_runtime_state: {target}={runtime_state!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check rendered MSF semantic UI coverage")
    parser.add_argument("--url", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    contract = load_json(Path(args.contract))
    errors = validate_coverage(discover_runtime(args.url, contract), contract)
    if errors:
        print("FAIL")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
