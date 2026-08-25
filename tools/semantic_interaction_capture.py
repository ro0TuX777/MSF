#!/usr/bin/env python3
"""Capture meaningful MSF interactions into the canonical journey object."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Callable

try:
    from tools.semantic_ui_validator import load_json
except ModuleNotFoundError:
    from semantic_ui_validator import load_json


_CAPTURE_SCRIPT = r"""
(() => {
    const contractActions = __CONTRACT_ACTIONS__;
  window.__msfCapture = { events: [], diagnostics: [] };
  const capture = (event, action, element, value) => {
    const target = element.closest('[data-msf-id]');
    if (!target) {
      window.__msfCapture.diagnostics.push({type: 'missing_semantic_id', event});
      return;
    }
    window.__msfCapture.events.push({
      action, target: target.dataset.msfId,
      value: value === undefined ? null : value,
      state: target.dataset.msfState || null,
      tag: target.tagName.toLowerCase(),
      input_type: target.type || null
    });
  };
  document.addEventListener('input', (event) => {
    if (event.target.matches('input[type="text"], textarea')) capture(event.type, 'set', event.target, event.target.value);
  }, true);
  document.addEventListener('change', (event) => {
    if (event.target.matches('select')) capture(event.type, 'select', event.target, event.target.value);
    else if (event.target.matches('input[type="checkbox"]')) capture(event.type, 'toggle', event.target, event.target.checked ? 'checked' : 'unchecked');
  }, true);
  document.addEventListener('click', (event) => {
    const element = event.target.closest('[data-msf-id]');
        const candidate = event.target.closest('button, [role="tab"], input[type="checkbox"]');
        if (!candidate) return;
        if (!element) {
            window.__msfCapture.diagnostics.push({type: 'missing_semantic_id', event: event.type});
            return;
        }
        if (element.matches('input[type="checkbox"]')) return;
        const permitted = contractActions[element.dataset.msfId] || [];
        if (permitted.includes('toggle')) capture(event.type, 'toggle', element);
        else if (permitted.includes('click')) capture(event.type, 'click', element);
        else if (!permitted.length) capture(event.type, 'click', element);
  }, true);
})();
"""


def _normalize(raw_events: list[dict[str, Any]], contract: dict[str, Any], diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controls = contract["controls"]
    steps: list[dict[str, Any]] = []
    for raw in raw_events:
        target = raw["target"]
        definition = controls.get(target)
        if definition is None:
            diagnostics.append({"type": "unknown_contract_target", "target": target})
        elif raw["action"] not in definition.get("actions", []):
            diagnostics.append({"type": "action_not_permitted", "target": target, "action": raw["action"]})
            continue

        step: dict[str, Any] = {"action": raw["action"], "target": target}
        if raw["action"] in {"set", "select"}:
            sensitive = bool(definition and definition.get("sensitive"))
            step["value"] = f"${{runtime:{target}}}" if sensitive else raw["value"]
        elif raw["action"] == "toggle":
            step["value"] = raw["value"]

        if steps and step["action"] == "set" and steps[-1]["action"] == "set" and steps[-1]["target"] == target:
            steps[-1] = step
        elif steps and step["action"] == "select" and steps[-1] == step:
            continue
        else:
            steps.append(step)
    return steps


def capture_workflow(
    url: str,
    contract: dict[str, Any],
    interaction: Callable[[Any], None],
    journey_id: str,
    *,
    debug: bool = False,
    output: Path | None = None,
    headless: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Capture one browser interaction session; raw sensitive values never leave the page."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is required for semantic capture") from exc

    diagnostics: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        contract_actions = {
            target: definition.get("actions", [])
            for target, definition in contract["controls"].items()
        }
        page.add_init_script(_CAPTURE_SCRIPT.replace("__CONTRACT_ACTIONS__", json.dumps(contract_actions)))
        page.goto(url)
        interaction(page)
        captured = page.evaluate("window.__msfCapture")
        browser.close()

    diagnostics.extend(captured.get("diagnostics", []))
    steps = _normalize(captured.get("events", []), contract, diagnostics)
    journey = {
        "journey_id": journey_id,
        "origin": "captured",
        "capture_session_id": str(uuid.uuid4()),
        "steps": steps,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(journey, indent=2) + "\n", encoding="utf-8")
    if debug:
        return journey, diagnostics
    return journey, []


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture semantic interactions from an MSF-instrumented page")
    parser.add_argument("--url", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--journey-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--headed", action="store_true", help="Open a browser for a human interaction session")
    args = parser.parse_args()
    journey, diagnostics = capture_workflow(
        args.url,
        load_json(Path(args.contract)),
        lambda page: input("Perform semantic interactions in the browser, then press Enter here: "),
        args.journey_id,
        debug=True,
        output=Path(args.output),
        headless=not args.headed,
    )
    print(json.dumps({"journey": journey, "diagnostics": diagnostics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
