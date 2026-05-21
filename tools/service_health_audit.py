#!/usr/bin/env python3
"""MFS service health and contract audit.

Usage:
  python tools/service_health_audit.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable

import requests


def _discover_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "registry" / "services.json").exists():
            return candidate
    raise FileNotFoundError("Could not locate framework root containing registry/services.json")


ROOT = _discover_root(Path(__file__).resolve().parent)
REGISTRY_PATH = ROOT / "registry" / "services.json"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validate_type(value: Any, expected: str) -> bool:
    if expected == "str":
        return isinstance(value, str)
    if expected == "list":
        return isinstance(value, list)
    if expected == "nullable_str":
        return value is None or isinstance(value, str)
    return False


def _iter_base_url_envs(service: Dict[str, Any]) -> Iterable[str]:
    envs = service.get("base_url_envs")
    if isinstance(envs, list):
        for env in envs:
            if isinstance(env, str) and env.strip():
                yield env.strip()

    legacy_env = service.get("base_url_env")
    if isinstance(legacy_env, str) and legacy_env.strip():
        yield legacy_env.strip()


def _resolve_base_url(service: Dict[str, Any]) -> str:
    default_base_url = str(service["default_base_url"]).rstrip("/")
    for env_name in _iter_base_url_envs(service):
        env_value = os.getenv(env_name)
        if env_value:
            return env_value.rstrip("/")
    return default_base_url


def main() -> int:
    registry = _load_json(REGISTRY_PATH)
    services = registry.get("services", [])
    failures = 0

    for svc in services:
        name = svc["name"]
        base_url = _resolve_base_url(svc)
        health_url = base_url + svc["health_path"]
        contract_url = base_url + svc["contract_path"]
        contract_file = ROOT / svc["contract_file"]
        contract = _load_json(contract_file)

        print(f"\n== {name} ==")
        try:
            health = requests.get(health_url, timeout=2.5)
            health.raise_for_status()
            print(f"[OK] health: {health_url}")
        except Exception as exc:
            print(f"[FAIL] health: {health_url} -> {exc}")
            failures += 1
            continue

        try:
            payload_resp = requests.get(contract_url, timeout=4.0)
            payload_resp.raise_for_status()
            payload = payload_resp.json()
            print(f"[OK] contract endpoint: {contract_url}")
        except Exception as exc:
            print(f"[FAIL] contract endpoint: {contract_url} -> {exc}")
            failures += 1
            continue

        required_fields = contract.get("required_fields", {})
        field_errors = []
        for field, expected in required_fields.items():
            if field not in payload:
                field_errors.append(f"missing field: {field}")
                continue
            if not _validate_type(payload[field], expected):
                field_errors.append(f"type mismatch: {field} expected {expected}, got {type(payload[field]).__name__}")

        allowed_status = set(contract.get("allowed_status", []))
        if payload.get("status") not in allowed_status:
            field_errors.append(f"invalid status: {payload.get('status')}")

        if payload.get("contract_version") != contract.get("contract_version"):
            field_errors.append(
                f"contract drift: expected {contract.get('contract_version')}, got {payload.get('contract_version')}"
            )

        if field_errors:
            failures += 1
            print("[FAIL] contract validation")
            for err in field_errors:
                print(f"  - {err}")
        else:
            print("[OK] contract validation")

    if failures:
        print(f"\nAudit completed with {failures} failure(s).")
        return 1
    print("\nAudit completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
