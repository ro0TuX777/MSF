#!/usr/bin/env python3
"""Discover and review MSF semantic retrofit candidates in a rendered page."""

from __future__ import annotations

import argparse
import difflib
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


_SOURCE_CONTROL_PATTERN = re.compile(
    r"<(?P<tag>button|input|select|textarea)(?P<attrs>[^>]*?)(?:/?>)",
    re.IGNORECASE | re.DOTALL,
)
_SOURCE_ATTRIBUTE_PATTERN = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)


def _source_attributes(raw_attributes: str) -> dict[str, str]:
    return {
        match.group("name").lower(): re.sub(r"\s+", " ", match.group("value")).strip()
        for match in _SOURCE_ATTRIBUTE_PATTERN.finditer(raw_attributes)
    }


def infer_source_evidence(tag: str, attributes: dict[str, str], contract_states: list[str]) -> dict[str, Any]:
    """Infer conservative actions, handlers, and states from source evidence."""
    control_type = attributes.get("role") or attributes.get("type") or tag.lower()
    actions = {"click"} if tag.lower() == "button" else set()
    if tag.lower() == "select":
        actions.add("select")
    if tag.lower() == "textarea" or attributes.get("type") in {"text", "email", "number", "password"}:
        actions.add("set")
    if attributes.get("type") == "checkbox":
        actions = {"toggle"}
    if attributes.get("aria-expanded") is not None:
        actions.add("toggle")
    handler_values = [value for name, value in attributes.items() if name.startswith("on") and name != "once"]
    state_values = []
    if attributes.get("data-msf-state"):
        state_values.append(attributes["data-msf-state"])
    if attributes.get("aria-expanded"):
        state_values.append("expanded" if attributes["aria-expanded"].lower() == "true" else "collapsed")
    if attributes.get("disabled") is not None:
        state_values.append("disabled")
    return {
        "control_type": control_type,
        "actions": sorted(actions),
        "handler_hints": sorted(set(handler_values)),
        "state_hints": sorted(set(state_values)),
        "contract_state_candidates": contract_states,
        "confidence": "high" if handler_values or attributes.get("data-msf-state") else "low",
    }


def discover_source(source_dir: str | Path, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inventory source controls and return evidence for human review."""
    root = Path(source_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Source directory does not exist: {root}")

    controls = (contract or {}).get("controls", {})
    candidates: list[dict[str, Any]] = []
    extensions = {".html", ".htm", ".jsx", ".tsx", ".vue"}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.suffix.lower() in extensions):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _SOURCE_CONTROL_PATTERN.finditer(text):
            attributes = _source_attributes(match.group("attrs"))
            line = text.count("\n", 0, match.start()) + 1
            semantic_id = attributes.get("data-msf-id")
            label = attributes.get("aria-label") or attributes.get("name") or ""
            if not label and match.group("tag").lower() == "button":
                closing_tag = re.search(r"</button\s*>", text[match.end():], re.IGNORECASE)
                if closing_tag:
                    button_text = text[match.end():match.end() + closing_tag.start()]
                    label = re.sub(r"<[^>]+>", " ", button_text)
                    label = re.sub(r"\s+", " ", label).strip()
            if not label:
                label = attributes.get("value", "") if match.group("tag").lower() in {"button", "input"} else ""
            if not label:
                label = attributes.get("id", "")
            handler_hints = sorted(name for name in attributes if name.startswith("on") and name != "once")
            state_hints = sorted(
                name for name in attributes if name in {"data-msf-state", "aria-expanded", "disabled"}
            )
            definition = controls.get(semantic_id) if semantic_id else None
            inferred = infer_source_evidence(
                match.group("tag"), attributes, definition.get("states", []) if definition else []
            )
            candidate = {
                "source": {"file": str(path.relative_to(root)), "line": line},
                "source_span": {"start": match.start(), "end": match.end()},
                "semantic_id": semantic_id,
                "label": label,
                "control_type": inferred["control_type"],
                "evidence": {
                    "dom_id": attributes.get("id"),
                    "handler_hints": handler_hints,
                    "state_hints": state_hints,
                    "handler_values": inferred["handler_hints"],
                    "inferred_actions": inferred["actions"],
                    "inferred_states": inferred["state_hints"],
                    "contract_state_candidates": inferred["contract_state_candidates"],
                    "confidence": inferred["confidence"],
                },
                "contract": {
                    "status": "matched" if definition else ("missing_identity" if not semantic_id else "unknown_target"),
                    "actions": definition.get("actions", []) if definition else [],
                    "states": definition.get("states", []) if definition else [],
                },
            }
            if not semantic_id:
                candidate["proposed_semantic_id"] = propose_id(label, "review")
                candidate["approval"] = "required"
            candidates.append(candidate)

    return {
        "schema_version": "msf.semantic_source_report.v1",
        "source_dir": str(root),
        "candidates": candidates,
        "review_required": any(item["contract"]["status"] != "matched" for item in candidates),
    }


def build_instrumentation_plan(
    report: dict[str, Any], approvals: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    """Build an auditable source instrumentation plan from explicit approvals."""
    approvals = approvals or {}
    source_report = report.get("source", report)
    changes: list[dict[str, Any]] = []
    for candidate in source_report.get("candidates", []):
        source = candidate["source"]
        key = f"{source['file']}:{source['line']}"
        approval = approvals.get(key, {})
        semantic_id = candidate.get("semantic_id") or approval.get("semantic_id")
        if not semantic_id:
            continue
        attributes: dict[str, str] = {}
        if not candidate.get("semantic_id"):
            attributes["data-msf-id"] = semantic_id
        state = approval.get("state")
        if state and "data-msf-state" not in candidate["evidence"].get("state_hints", []):
            attributes["data-msf-state"] = state
        if attributes:
            changes.append({
                "file": source["file"],
                "line": source["line"],
                "source_span": candidate["source_span"],
                "attributes": attributes,
                "approved": True,
            })
    return {"schema_version": "msf.semantic_instrumentation_plan.v1", "changes": changes}


def apply_instrumentation_plan(
    source_dir: str | Path, plan: dict[str, Any], *, dry_run: bool = True
) -> str:
    """Render or apply an approved plan; dry-run returns a unified diff."""
    root = Path(source_dir).resolve()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for change in plan.get("changes", []):
        if not change.get("approved"):
            continue
        grouped.setdefault(change["file"], []).append(change)
    diffs: list[str] = []
    for relative, changes in grouped.items():
        path = root / relative
        original = path.read_text(encoding="utf-8")
        updated = original
        for change in sorted(changes, key=lambda item: item["source_span"]["start"], reverse=True):
            span = change["source_span"]
            opening_tag = updated[span["start"]:span["end"]]
            insertion = "".join(f' {name}="{value}"' for name, value in change["attributes"].items())
            updated = updated[:span["end"] - 1] + insertion + updated[span["end"] - 1:]
            if not opening_tag:
                raise ValueError(f"empty source span for {relative}:{change['line']}")
        if updated != original:
            diffs.extend(difflib.unified_diff(
                original.splitlines(keepends=True), updated.splitlines(keepends=True),
                fromfile=relative, tofile=relative,
            ))
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
    return "".join(diffs)


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
    parser.add_argument("--url", help="Rendered application URL")
    parser.add_argument("--source-dir", help="Source directory to inventory")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--approval", help="JSON approvals keyed by relative-file:line")
    parser.add_argument("--patch", help="Write the generated unified diff to this path")
    parser.add_argument("--apply", action="store_true", help="Apply approved instrumentation changes")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.url and not args.source_dir:
        parser.error("one of --url or --source-dir is required")
    contract = load_json(Path(args.contract))
    reports = []
    if args.url:
        reports.append(discover_runtime(args.url, contract, headless=True))
    if args.source_dir:
        reports.append(discover_source(args.source_dir, contract))
    report = reports[0] if len(reports) == 1 else {
        "schema_version": "msf.semantic_retrofit_report.v1",
        "runtime": reports[0],
        "source": reports[1],
        "review_required": reports[0]["review_required"] or reports[1]["review_required"],
    }
    if args.approval:
        approvals = load_json(Path(args.approval))
        plan = build_instrumentation_plan(report, approvals.get("approvals", approvals))
        report["instrumentation_plan"] = plan
        if not args.source_dir:
            parser.error("--approval requires --source-dir")
        diff = apply_instrumentation_plan(args.source_dir, plan, dry_run=not args.apply)
        if args.patch:
            Path(args.patch).write_text(diff, encoding="utf-8")
        report["instrumentation_diff"] = diff
    rendered = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
