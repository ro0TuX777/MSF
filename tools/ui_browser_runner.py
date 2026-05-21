#!/usr/bin/env python3
"""Run browser-level UI parity checks from JSON spec (Playwright).

Requires:
- pip install playwright
- playwright install
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Spec must be a JSON object")
    return payload


def _normalize_steps(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run browser-level UI parity checks with Playwright")
    parser.add_argument("--spec", required=True, help="Path to browser spec JSON")
    parser.add_argument("--output-json", default="", help="Optional output JSON")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    spec = _load_json(spec_path)
    base_url = str(spec.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("Spec requires base_url")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is not available. Install with: pip install playwright && playwright install"
        ) from exc

    suite_name = str(spec.get("name", "ui_browser_parity"))
    headless = bool(spec.get("headless", True))
    default_timeout_ms = int(spec.get("default_timeout_ms", 8000))

    checks = spec.get("checks", [])
    if not isinstance(checks, list) or not checks:
        raise ValueError("Spec requires non-empty checks list")

    results: List[Dict[str, Any]] = []

    print(f"suite: {suite_name}")
    print(f"spec: {spec_path}")
    print(f"checks: {len(checks)}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(default_timeout_ms)

        for check in checks:
            if not isinstance(check, dict):
                continue
            name = str(check.get("name", "unnamed_check"))
            path = str(check.get("path", "/")).strip()
            url = str(check.get("url", "")).strip() or f"{base_url}{path}"
            steps = _normalize_steps(check.get("steps", []))

            item = {"name": name, "url": url, "ok": False, "errors": []}
            print(f"- RUN: {name} ({url})")

            try:
                page.goto(url)
                for step in steps:
                    action = str(step.get("action", "")).strip().lower()
                    selector = str(step.get("selector", "")).strip()
                    value = step.get("value", "")
                    text = str(step.get("text", "")).strip()
                    timeout_ms = int(step.get("timeout_ms", default_timeout_ms))

                    if action == "click":
                        if not selector:
                            raise ValueError("click step requires selector")
                        page.locator(selector).click(timeout=timeout_ms)
                    elif action == "fill":
                        if not selector:
                            raise ValueError("fill step requires selector")
                        page.locator(selector).fill(str(value), timeout=timeout_ms)
                    elif action == "wait_for_selector":
                        if not selector:
                            raise ValueError("wait_for_selector step requires selector")
                        page.locator(selector).wait_for(timeout=timeout_ms)
                    elif action == "expect_selector":
                        if not selector:
                            raise ValueError("expect_selector step requires selector")
                        count = page.locator(selector).count()
                        if count <= 0:
                            raise AssertionError(f"selector not found: {selector}")
                    elif action == "expect_text":
                        content = page.content()
                        if text not in content:
                            raise AssertionError(f"text not found: {text}")
                    elif action == "wait_ms":
                        page.wait_for_timeout(int(value) if str(value).strip() else 500)
                    else:
                        raise ValueError(f"unsupported action: {action}")

                item["ok"] = True
                print(f"  PASS: {name}")
            except Exception as exc:
                item["ok"] = False
                item["errors"].append(str(exc))
                print(f"  FAIL: {name} -> {exc}")

            results.append(item)

        context.close()
        browser.close()

    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed
    overall_ok = failed == 0

    print("\nsummary:")
    print(f"- passed: {passed}")
    print(f"- failed: {failed}")
    print(f"- overall: {'PASS' if overall_ok else 'FAIL'}")

    report = {
        "suite": suite_name,
        "spec": str(spec_path),
        "passed": passed,
        "failed": failed,
        "overall_ok": overall_ok,
        "results": results,
    }

    if args.output_json:
        out_path = Path(args.output_json).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote: {out_path}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
