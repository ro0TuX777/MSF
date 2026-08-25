#!/usr/bin/env python3
"""Execute MSF semantic UI journeys in a real Chromium page."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.semantic_ui_validator import load_json, validate
except ModuleNotFoundError:
    from semantic_ui_validator import load_json, validate


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def target_locator(page: Any, target: str) -> Any:
    return page.locator(f'[data-msf-id="{target}"]')


def wait_for_state(locator: Any, expected: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if locator.get_attribute("data-msf-state") == expected:
            return
        time.sleep(0.025)
    observed = locator.get_attribute("data-msf-state")
    raise AssertionError(f"unexpected_state: expected {expected!r}, observed {observed!r}")


def execute(
    journey: dict[str, Any], contract: dict[str, Any], url: str,
    output: Path | None = None, headless: bool = True,
    session_id: str | None = None, run_id: str | None = None,
    runtime_values: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    errors = validate(contract, journey)
    if errors:
        raise ValueError("Journey rejected by contract:\n" + "\n".join(errors))

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is required for browser execution") from exc

    events: list[dict[str, Any]] = []
    runtime_values = runtime_values or {}
    session_id = session_id or str(uuid.uuid4())
    run_id = run_id or str(uuid.uuid4())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url)
        for index, step in enumerate(journey["steps"]):
            action = step["action"]
            target = step["target"]
            locator = target_locator(page, target)
            event: dict[str, Any] = {
                "schema_version": "msf.semantic_event.v1",
                "event": "semantic_ui_step",
                "timestamp": now(),
                "session_id": session_id,
                "run_id": run_id,
                "journey_id": journey["journey_id"],
                "step_index": index,
                "requested": {key: ("[REDACTED]" if key == "value" and contract["controls"][target].get("sensitive") else value) for key, value in step.items() if key != "timeout_ms"},
                "resolved": {"msf_id": target, "count": locator.count()},
                "observed": {},
                "resulting_state": None,
                "result": "failed",
            }
            try:
                if locator.count() != 1:
                    raise AssertionError(f"target_not_found: {target}")
                if action == "set":
                    value = step["value"]
                    if isinstance(value, str) and value.startswith("${runtime:") and value.endswith("}"):
                        key = value[10:-1]
                        if key not in runtime_values:
                            raise ValueError(f"missing_runtime_value: {key}")
                        value = runtime_values[key]
                    locator.fill(str(value))
                elif action == "clear":
                    locator.fill("")
                elif action == "focus":
                    locator.focus()
                elif action == "select":
                    locator.select_option(str(step["value"]))
                elif action in {"toggle", "click"}:
                    locator.click()
                elif action == "wait":
                    timeout_ms = int(step.get("timeout_ms", 8000))
                    locator.wait_for(state="attached", timeout=timeout_ms)
                    wait_for_state(locator, step["state"], timeout_ms)
                elif action == "expect":
                    observed = locator.get_attribute("data-msf-state")
                    if observed != step["state"]:
                        raise AssertionError(f"unexpected_state: expected {step['state']!r}, observed {observed!r}")
                else:
                    raise ValueError(f"unsupported action: {action}")
                event["observed"] = {"state": locator.get_attribute("data-msf-state")}
                event["resulting_state"] = event["observed"]["state"]
                event["result"] = "passed"
            except Exception as exc:
                event["error"] = str(exc)
            events.append(event)
            if event["result"] != "passed":
                break
        browser.close()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute an MSF semantic UI journey in Chromium")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--journey", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    events = execute(
        load_json(Path(args.journey)),
        load_json(Path(args.contract)),
        args.url,
        Path(args.output_jsonl) if args.output_jsonl else None,
        headless=not args.headed,
    )
    passed = len(events) > 0 and all(event["result"] == "passed" for event in events)
    print(f"journey: {args.journey}")
    print(f"steps: {len(events)}")
    print(f"overall: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
