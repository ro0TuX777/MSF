#!/usr/bin/env python3
"""Run HTTP smoke assertions from a JSON spec.

Usage:
  python tools/ui_smoke_runner.py --spec tools/ui_smoke_spec_template.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Spec must be a JSON object")
    return payload


def _json_path_get(payload: Any, path: str) -> Tuple[bool, Any]:
    cur = payload
    for token in path.split("."):
        token = token.strip()
        if not token:
            return False, None
        if isinstance(cur, dict) and token in cur:
            cur = cur[token]
            continue
        if isinstance(cur, list):
            try:
                idx = int(token)
            except ValueError:
                return False, None
            if idx < 0 or idx >= len(cur):
                return False, None
            cur = cur[idx]
            continue
        return False, None
    return True, cur


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _run_check(base_url: str, default_timeout: float, default_headers: Dict[str, str], check: Dict[str, Any]) -> Dict[str, Any]:
    name = str(check.get("name", "unnamed_check"))
    method = str(check.get("method", "GET")).upper()
    path = str(check.get("path", "")).strip()
    url = str(check.get("url", "")).strip() or f"{base_url.rstrip('/')}{path}"
    timeout_s = float(check.get("timeout_s", default_timeout))

    headers = dict(default_headers)
    extra_headers = check.get("headers", {})
    if isinstance(extra_headers, dict):
        for k, v in extra_headers.items():
            if isinstance(k, str):
                headers[k] = str(v)

    req_json = check.get("json")

    result: Dict[str, Any] = {
        "name": name,
        "method": method,
        "url": url,
        "ok": False,
        "assertions": [],
        "error": None,
        "status_code": None,
    }

    try:
        if method == "POST":
            resp = requests.post(url, headers=headers, json=req_json if isinstance(req_json, dict) else {}, timeout=timeout_s)
        else:
            resp = requests.get(url, headers=headers, timeout=timeout_s)
        result["status_code"] = resp.status_code

        errors: List[str] = []

        expect_status = check.get("expect_status")
        if expect_status is not None:
            expected = int(expect_status)
            if resp.status_code != expected:
                errors.append(f"status expected {expected}, got {resp.status_code}")

        expect_status_in = check.get("expect_status_in")
        if expect_status_in is not None:
            allowed = [int(x) for x in _as_list(expect_status_in)]
            if resp.status_code not in allowed:
                errors.append(f"status expected in {allowed}, got {resp.status_code}")

        body_text = resp.text or ""
        for token in _as_list(check.get("contains")):
            token_str = str(token)
            if token_str not in body_text:
                errors.append(f"body missing token: {token_str}")

        for token in _as_list(check.get("not_contains")):
            token_str = str(token)
            if token_str and token_str in body_text:
                errors.append(f"body unexpectedly contains token: {token_str}")

        expect_json_paths = check.get("expect_json_paths", {})
        expect_json_has_paths = _as_list(check.get("expect_json_has_paths"))
        parsed_json: Any = None
        if expect_json_paths or expect_json_has_paths:
            try:
                parsed_json = resp.json()
            except Exception:
                errors.append("response is not valid JSON")

        if isinstance(expect_json_paths, dict) and parsed_json is not None:
            for path_key, expected_val in expect_json_paths.items():
                ok, actual = _json_path_get(parsed_json, str(path_key))
                if not ok:
                    errors.append(f"missing JSON path: {path_key}")
                    continue
                if actual != expected_val:
                    errors.append(f"JSON path {path_key} expected {expected_val!r}, got {actual!r}")

        if parsed_json is not None:
            for path_key in expect_json_has_paths:
                ok, _ = _json_path_get(parsed_json, str(path_key))
                if not ok:
                    errors.append(f"missing JSON path: {path_key}")

        result["assertions"] = errors
        result["ok"] = len(errors) == 0
    except Exception as exc:
        result["error"] = str(exc)
        result["ok"] = False

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP smoke assertions from JSON spec")
    parser.add_argument("--spec", required=True, help="Path to JSON smoke spec")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    spec = _load_json(spec_path)
    name = str(spec.get("name", "ui_smoke"))
    base_url = str(spec.get("base_url", "")).strip()
    if not base_url and not any(isinstance(c, dict) and str(c.get("url", "")).strip() for c in spec.get("checks", [])):
        raise ValueError("Spec must provide base_url or absolute url per check")

    default_timeout = float(spec.get("default_timeout_s", 5.0))
    default_headers = spec.get("default_headers", {}) if isinstance(spec.get("default_headers", {}), dict) else {}
    checks = spec.get("checks", [])
    if not isinstance(checks, list) or not checks:
        raise ValueError("Spec must include non-empty 'checks' list")

    print(f"suite: {name}")
    print(f"spec: {spec_path}")
    print(f"checks: {len(checks)}")

    results: List[Dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        item = _run_check(base_url, default_timeout, default_headers, check)
        results.append(item)
        status = "PASS" if item["ok"] else "FAIL"
        print(f"- {status}: {item['name']} ({item['method']} {item['url']})")
        if item.get("status_code") is not None:
            print(f"  status_code: {item['status_code']}")
        if item.get("error"):
            print(f"  error: {item['error']}")
        for assertion in item.get("assertions", []):
            print(f"  assertion: {assertion}")

    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed
    overall_ok = failed == 0

    print("\nsummary:")
    print(f"- passed: {passed}")
    print(f"- failed: {failed}")
    print(f"- overall: {'PASS' if overall_ok else 'FAIL'}")

    out_payload = {
        "suite": name,
        "spec": str(spec_path),
        "passed": passed,
        "failed": failed,
        "overall_ok": overall_ok,
        "results": results,
    }

    if args.output_json:
        out_path = Path(args.output_json).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
        print(f"\nWrote: {out_path}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
