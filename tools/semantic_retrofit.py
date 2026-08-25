#!/usr/bin/env python3
"""Discover and review MSF semantic retrofit candidates in a rendered page."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

try:
    from tools.semantic_ui_validator import load_json
except ModuleNotFoundError:
    from semantic_ui_validator import load_json


_RUNTIME_SCRIPT = r"""
(() => {
  window.__msfRetrofit = {events: []};
  const meaningful = 'button,input,select,textarea,[role="tab"],[role="status"],[aria-expanded]';
  const labelFor = (element) => {
    if (element.getAttribute('aria-label')) return element.getAttribute('aria-label');
    if (element.id) {
      const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (label) return label.textContent.trim();
    }
    return (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  };
  const record = (event, action, element, value) => {
    const target = element.closest('[data-msf-id]');
    window.__msfRetrofit.events.push({
      event, action, msf_id: target ? target.dataset.msfId : null,
      label: labelFor(element), value: value === undefined ? null : value,
      state: target ? (target.dataset.msfState || null) : null
    });
  };
  document.addEventListener('input', (event) => {
    if (event.target.matches('input[type="text"],textarea')) record('input', 'set', event.target, event.target.value);
  }, true);
  document.addEventListener('change', (event) => {
    if (event.target.matches('select')) record('change', 'select', event.target, event.target.value);
    else if (event.target.matches('input[type="checkbox"]')) record('change', 'toggle', event.target, event.target.checked ? 'checked' : 'unchecked');
  }, true);
  document.addEventListener('click', (event) => {
    const element = event.target.closest(meaningful);
    if (!element || element.matches('input[type="checkbox"]')) return;
    record('click', element.matches('[aria-expanded]') ? 'toggle' : 'click', element);
  }, true);
    const collectInventory = () => window.__msfRetrofit.inventory = [...document.querySelectorAll('button,input,select,textarea,[role="tab"],[role="status"],[aria-expanded],[data-msf-id]')].map((element) => ({
    msf_id: element.dataset.msfId || null,
    tag: element.tagName.toLowerCase(),
    type: element.getAttribute('type'),
    role: element.getAttribute('role'),
    label: labelFor(element),
    state: element.dataset.msfState || null,
    visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
    enabled: !('disabled' in element) || !element.disabled,
    options: element.tagName.toLowerCase() === 'select' ? [...element.options].map((option) => option.value) : [],
    aria_expanded: element.getAttribute('aria-expanded')
    }));
    window.__msfRetrofit.refresh = collectInventory;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', collectInventory);
    else collectInventory();
})();
"""


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def propose_id(label: str, context: str = "") -> str:
    """Return a reviewable ID proposal; this never claims approval or edits application code."""
    context_id = "/".join(_slug(part) for part in context.split("/") if _slug(part))
    parts = [part for part in (context_id, _slug(label)) if part]
    return "/".join(parts[-2:]) or "review/unnamed-control"


def discover_runtime(
    url: str,
    contract: dict[str, Any] | None = None,
    interaction: Callable[[Any], None] | None = None,
    *,
    headless: bool = True,
) -> dict[str, Any]:
    """Inspect rendered controls and optionally observe a supplied browser interaction."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is required for retrofit discovery") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.add_init_script(_RUNTIME_SCRIPT)
        page.goto(url)
        if interaction:
            interaction(page)
        page.evaluate("window.__msfRetrofit.refresh()")
        observed = page.evaluate("window.__msfRetrofit")
        browser.close()

    controls = (contract or {}).get("controls", {})
    candidates: list[dict[str, Any]] = []
    for item in observed.get("inventory", []):
        target = item.get("msf_id")
        definition = controls.get(target) if target else None
        candidate = {
            "semantic_id": target,
            "label": item.get("label", ""),
            "control_type": item.get("role") or item.get("type") or item.get("tag"),
            "runtime": {
                "state": item.get("state"),
                "visible": item.get("visible"),
                "enabled": item.get("enabled"),
                "options": item.get("options", []),
            },
            "contract": {
                "status": "matched" if definition else ("missing_identity" if not target else "unknown_target"),
                "actions": definition.get("actions", []) if definition else [],
                "states": definition.get("states", []) if definition else [],
            },
        }
        if not target:
            candidate["proposed_semantic_id"] = propose_id(item.get("label", ""), "review")
            candidate["approval"] = "required"
        candidates.append(candidate)

    events: list[dict[str, Any]] = []
    for event in observed.get("events", []):
        target = event.get("msf_id")
        definition = controls.get(target, {})
        value = event.get("value")
        events.append({
            "event": event.get("event"),
            "action": event.get("action"),
            "semantic_id": target,
            "state": event.get("state"),
            "value": "[REDACTED]" if definition.get("sensitive") and value is not None else value,
            "diagnostic": None if target else "missing_semantic_id",
        })

    return {
        "schema_version": "msf.semantic_retrofit_report.v1",
        "report_id": str(uuid.uuid4()),
        "url": url,
        "candidates": candidates,
        "observed_events": events,
        "review_required": any(candidate["contract"]["status"] != "matched" for candidate in candidates),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a rendered page for MSF retrofit candidates")
    parser.add_argument("--url", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = discover_runtime(args.url, load_json(Path(args.contract)), headless=True)
    rendered = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
