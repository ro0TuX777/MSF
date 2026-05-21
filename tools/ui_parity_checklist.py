#!/usr/bin/env python3
"""Run a structured UI parity checklist and emit pass/fail summary.

Usage:
  python tools/ui_parity_checklist.py --checklist tools/ui_parity_checklist_template.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

VALID_STATUS = {"pass", "fail", "na", "todo"}


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Checklist must be a JSON object")
    return payload


def _normalize_items(raw_items: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    items: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id", f"item_{idx}")).strip() or f"item_{idx}"
        description = str(raw.get("description", "")).strip()
        status = str(raw.get("status", "todo")).strip().lower()
        if status not in VALID_STATUS:
            status = "todo"
        critical = bool(raw.get("critical", False))
        notes = str(raw.get("notes", "")).strip()
        items.append(
            {
                "id": item_id,
                "description": description,
                "status": status,
                "critical": critical,
                "notes": notes,
            }
        )
    return items


def _summary(items: List[Dict[str, Any]], fail_on_todo: bool) -> Dict[str, Any]:
    counts = {"pass": 0, "fail": 0, "na": 0, "todo": 0}
    critical_fail = 0
    for item in items:
        st = item["status"]
        counts[st] = counts.get(st, 0) + 1
        if st == "fail" and item.get("critical"):
            critical_fail += 1

    total = len(items)
    pass_rate = (counts["pass"] / total * 100.0) if total else 0.0
    overall_ok = counts["fail"] == 0 and (counts["todo"] == 0 if fail_on_todo else True)

    return {
        "total": total,
        "pass": counts["pass"],
        "fail": counts["fail"],
        "na": counts["na"],
        "todo": counts["todo"],
        "critical_fail": critical_fail,
        "pass_rate": round(pass_rate, 2),
        "overall_ok": overall_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UI parity checklist and report pass/fail")
    parser.add_argument("--checklist", required=True, help="Path to checklist JSON")
    parser.add_argument("--fail-on-todo", action="store_true", help="Treat TODO items as failing")
    parser.add_argument("--output-json", default="", help="Optional JSON output path")
    args = parser.parse_args()

    checklist_path = Path(args.checklist).resolve()
    if not checklist_path.exists():
        raise FileNotFoundError(f"Checklist not found: {checklist_path}")

    payload = _load_json(checklist_path)
    feature = str(payload.get("feature", "unknown_feature"))
    environment = str(payload.get("environment", "unknown_env"))
    items = _normalize_items(payload.get("items", []))

    print(f"feature: {feature}")
    print(f"environment: {environment}")
    print(f"checklist: {checklist_path}")
    print("\nitems:")
    for item in items:
        critical_tag = " [critical]" if item.get("critical") else ""
        notes = f" | notes: {item['notes']}" if item.get("notes") else ""
        print(f"- {item['id']}: {item['status']}{critical_tag} | {item['description']}{notes}")

    summary = _summary(items, fail_on_todo=bool(args.fail_on_todo))

    print("\nsummary:")
    print(f"- total: {summary['total']}")
    print(f"- pass: {summary['pass']}")
    print(f"- fail: {summary['fail']}")
    print(f"- todo: {summary['todo']}")
    print(f"- na: {summary['na']}")
    print(f"- critical_fail: {summary['critical_fail']}")
    print(f"- pass_rate: {summary['pass_rate']}%")
    print(f"- overall: {'PASS' if summary['overall_ok'] else 'FAIL'}")

    output_payload = {
        "feature": feature,
        "environment": environment,
        "checklist": str(checklist_path),
        "items": items,
        "summary": summary,
    }

    if args.output_json:
        out_path = Path(args.output_json).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
        print(f"\nWrote: {out_path}")

    return 0 if summary["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
