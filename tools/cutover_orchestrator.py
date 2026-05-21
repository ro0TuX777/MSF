#!/usr/bin/env python3
"""Cutover orchestration CLI for MFS feature rollout.

Usage examples:
  python tools/cutover_orchestrator.py plan --manifest docs/_generated/feature_cutover.json
  python tools/cutover_orchestrator.py promote --manifest docs/_generated/feature_cutover.json --stage canary_5
  python tools/cutover_orchestrator.py promote --manifest docs/_generated/feature_cutover.json --stage canary_5 --execute
  python tools/cutover_orchestrator.py rollback --manifest docs/_generated/feature_cutover.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import requests
import hashlib

try:
    from governance_adapters.mock_forgeroot import MockForgeRootAdapter
    from governance_adapters.http_forgeroot import HttpForgeRootAdapter
except ImportError:
    from tools.governance_adapters.mock_forgeroot import MockForgeRootAdapter
    from tools.governance_adapters.http_forgeroot import HttpForgeRootAdapter


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be JSON object: {path}")
    return payload


def _state_path(manifest_path: Path, override: str) -> Path:
    if override.strip():
        return Path(override).resolve()
    return manifest_path.with_suffix(".state.json")


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "current_stage": None,
            "history": [],
            "updated_at": None,
        }
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {"current_stage": None, "history": [], "updated_at": None}
    payload.setdefault("current_stage", None)
    payload.setdefault("history", [])
    payload.setdefault("updated_at", None)
    return payload


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _stages(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = manifest.get("stages", [])
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            out.append(item)
    return out


def _find_stage(manifest: Dict[str, Any], stage_name: str) -> Dict[str, Any] | None:
    for stage in _stages(manifest):
        if stage.get("name") == stage_name:
            return stage
    return None


def _run_command(cmd: str, *, execute: bool) -> int:
    if not cmd.strip():
        print("  command: <none>")
        return 0
    print(f"  command: {cmd}")
    if not execute:
        print("  result: dry-run (not executed)")
        return 0
    result = subprocess.run(cmd, shell=True, check=False)
    print(f"  result: exit_code={result.returncode}")
    return int(result.returncode)


def _integration_config(manifest: Dict[str, Any]) -> Dict[str, Any]:
    raw = manifest.get("integrations", {})
    return raw if isinstance(raw, dict) else {}


def _json_path_get(payload: Any, path: str) -> tuple[bool, Any]:
    current = payload
    for token in path.split("."):
        key = token.strip()
        if not key:
            return False, None
        if isinstance(current, dict) and key in current:
            current = current[key]
            continue
        if isinstance(current, list):
            try:
                idx = int(key)
            except ValueError:
                return False, None
            if idx < 0 or idx >= len(current):
                return False, None
            current = current[idx]
            continue
        return False, None
    return True, current


def _http_hook(name: str, cfg: Dict[str, Any], payload: Dict[str, Any], *, execute: bool) -> tuple[bool, Dict[str, Any]]:
    url = str(cfg.get("url", "")).strip()
    method = str(cfg.get("method", "POST")).strip().upper()
    timeout_s = float(cfg.get("timeout_s", 5))
    headers = cfg.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}
    expected = cfg.get("expect_status", 200)
    try:
        expected_code = int(expected)
    except Exception:
        expected_code = 200

    event = {
        "integration": name,
        "type": "http_hook",
        "url": url,
        "method": method,
        "expected_status": expected_code,
        "executed": execute,
        "ok": False,
        "status_code": None,
        "error": None,
        "skipped": False,
    }
    if not url:
        event["skipped"] = True
        event["ok"] = True
        event["error"] = "disabled_missing_url"
        return True, event

    print(f"integration[{name}] {method} {url}")
    if not execute:
        event["ok"] = True
        return True, event

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=timeout_s)
        else:
            resp = requests.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload, timeout=timeout_s)
        event["status_code"] = resp.status_code
        event["ok"] = resp.status_code == expected_code
        if not event["ok"]:
            event["error"] = f"unexpected_status_{resp.status_code}"
        return bool(event["ok"]), event
    except Exception as exc:
        event["error"] = str(exc)
        return False, event


def _integration_health_check(cfg: Dict[str, Any], *, execute: bool) -> tuple[bool, Dict[str, Any]]:
    url = str(cfg.get("url", "")).strip()
    timeout_s = float(cfg.get("timeout_s", 5))
    expected = cfg.get("expect_status", 200)
    try:
        expected_code = int(expected)
    except Exception:
        expected_code = 200

    event = {
        "integration": "health_check",
        "type": "http_health_check",
        "url": url,
        "expected_status": expected_code,
        "executed": execute,
        "ok": False,
        "status_code": None,
        "error": None,
        "skipped": False,
    }
    if not url:
        event["skipped"] = True
        event["ok"] = True
        event["error"] = "disabled_missing_url"
        return True, event

    print(f"integration[health_check] GET {url}")
    if not execute:
        event["ok"] = True
        return True, event

    try:
        resp = requests.get(url, timeout=timeout_s)
        event["status_code"] = resp.status_code
        event["ok"] = resp.status_code == expected_code
        if not event["ok"]:
            event["error"] = f"unexpected_status_{resp.status_code}"
        return bool(event["ok"]), event
    except Exception as exc:
        event["error"] = str(exc)
        return False, event


def _set_local_env_flag(adapter_cfg: Dict[str, Any], percent: int, *, execute: bool) -> tuple[bool, Dict[str, Any]]:
    env_file = Path(str(adapter_cfg.get("env_file", ".env"))).resolve()
    flag_key = str(adapter_cfg.get("flag_key", "")).strip()
    event = {
        "integration": "flag_provider",
        "adapter": "local_env_flag",
        "env_file": str(env_file),
        "flag_key": flag_key,
        "percent": percent,
        "executed": execute,
        "ok": False,
        "error": None,
        "skipped": False,
    }
    if not flag_key:
        event["error"] = "missing_flag_key"
        return False, event
    if not execute:
        event["ok"] = True
        return True, event

    lines: List[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8-sig").splitlines()
    replaced = False
    out_lines: List[str] = []
    for line in lines:
        if line.strip().startswith(f"{flag_key}="):
            out_lines.append(f"{flag_key}={percent}")
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        out_lines.append(f"{flag_key}={percent}")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    event["ok"] = True
    return True, event


def _run_adapter_command(cmd: List[str], *, execute: bool, adapter_name: str) -> tuple[bool, Dict[str, Any]]:
    event = {
        "integration": adapter_name,
        "command": cmd,
        "executed": execute,
        "ok": False,
        "exit_code": None,
        "error": None,
    }
    print(f"integration[{adapter_name}] {' '.join(cmd)}")
    if not execute:
        event["ok"] = True
        return True, event
    try:
        proc = subprocess.run(cmd, check=False)
        event["exit_code"] = int(proc.returncode)
        event["ok"] = proc.returncode == 0
        if not event["ok"]:
            event["error"] = f"exit_code_{proc.returncode}"
        return bool(event["ok"]), event
    except Exception as exc:
        event["error"] = str(exc)
        return False, event


def _run_flag_provider_adapter(integrations: Dict[str, Any], percent: int, *, execute: bool) -> tuple[bool, Dict[str, Any] | None]:
    provider = integrations.get("flag_provider", {})
    if not isinstance(provider, dict):
        return True, None
    adapter_type = str(provider.get("type", "")).strip().lower()
    if not adapter_type:
        return True, None
    if adapter_type == "local_env_flag":
        return _set_local_env_flag(provider, percent, execute=execute)
    if adapter_type == "argo_rollouts":
        rollout = str(provider.get("rollout", "")).strip()
        namespace = str(provider.get("namespace", "")).strip()
        if not rollout:
            return False, {"integration": "flag_provider", "adapter": adapter_type, "ok": False, "error": "missing_rollout"}
        cmd = ["kubectl", "argo", "rollouts", "set", "weight", rollout, str(percent)]
        if namespace:
            cmd.extend(["-n", namespace])
        return _run_adapter_command(cmd, execute=execute, adapter_name="flag_provider")
    return False, {"integration": "flag_provider", "adapter": adapter_type, "ok": False, "error": "unsupported_adapter"}


def _run_deploy_provider_adapter(integrations: Dict[str, Any], *, execute: bool) -> tuple[bool, Dict[str, Any] | None]:
    provider = integrations.get("deploy_provider", {})
    if not isinstance(provider, dict):
        return True, None
    adapter_type = str(provider.get("type", "")).strip().lower()
    if not adapter_type:
        return True, None
    if adapter_type == "docker_compose":
        compose_file = str(provider.get("compose_file", "docker-compose.yml")).strip()
        services = provider.get("services", [])
        if not isinstance(services, list):
            services = []
        cmd = ["docker", "compose", "-f", compose_file, "up", "-d", *[str(s) for s in services if str(s).strip()]]
        return _run_adapter_command(cmd, execute=execute, adapter_name="deploy_provider")
    if adapter_type == "argo_rollouts":
        rollout = str(provider.get("rollout", "")).strip()
        namespace = str(provider.get("namespace", "")).strip()
        image = str(provider.get("image", "")).strip()
        if not rollout:
            return False, {"integration": "deploy_provider", "adapter": adapter_type, "ok": False, "error": "missing_rollout"}
        cmd = ["kubectl", "argo", "rollouts", "promote", rollout]
        if namespace:
            cmd.extend(["-n", namespace])
        if image:
            cmd.extend(["--to-revision", image])
        return _run_adapter_command(cmd, execute=execute, adapter_name="deploy_provider")
    return False, {"integration": "deploy_provider", "adapter": adapter_type, "ok": False, "error": "unsupported_adapter"}


def _evaluate_slo_policy(manifest: Dict[str, Any], *, execute: bool) -> tuple[bool, Dict[str, Any] | None]:
    integrations = _integration_config(manifest)
    policy = integrations.get("slo_policy", {})
    if not isinstance(policy, dict):
        return True, None
    url = str(policy.get("health_url", "")).strip()
    if not url:
        return True, None

    event = {
        "integration": "slo_policy",
        "health_url": url,
        "executed": execute,
        "ok": False,
        "breaches": [],
        "observed": {},
        "error": None,
        "skipped": False,
    }
    if not execute:
        event["ok"] = True
        return True, event

    try:
        resp = requests.get(url, timeout=float(policy.get("timeout_s", 5)))
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("SLO health response must be JSON object")

        latency_path = str(policy.get("latency_json_path", "metrics.latency_p95_ms")).strip()
        error_path = str(policy.get("error_rate_json_path", "metrics.error_rate_pct")).strip()
        ok_lat, lat_val = _json_path_get(payload, latency_path)
        ok_err, err_val = _json_path_get(payload, error_path)
        event["observed"] = {
            "latency_p95_ms": lat_val if ok_lat else None,
            "error_rate_pct": err_val if ok_err else None,
        }

        max_latency = policy.get("max_latency_p95_ms")
        max_error = policy.get("max_error_rate_pct")
        breaches: List[str] = []
        if max_latency is not None and ok_lat:
            try:
                if float(lat_val) > float(max_latency):
                    breaches.append(f"latency_p95_ms>{max_latency}")
            except Exception:
                breaches.append("invalid_latency_value")
        if max_error is not None and ok_err:
            try:
                if float(err_val) > float(max_error):
                    breaches.append(f"error_rate_pct>{max_error}")
            except Exception:
                breaches.append("invalid_error_rate_value")

        event["breaches"] = breaches
        event["ok"] = len(breaches) == 0
        return bool(event["ok"]), event
    except Exception as exc:
        event["error"] = str(exc)
        return False, event


def _record(state: Dict[str, Any], event: Dict[str, Any]) -> None:
    history = state.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        state["history"] = history
    history.append(event)
    state["updated_at"] = _now_iso()


def _gate_config_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    gates = manifest.get("gates", {})
    if not isinstance(gates, dict):
        return {}
    return gates


def _run_pre_promote_gates(
    manifest: Dict[str, Any],
    *,
    checklist_path: str,
    smoke_spec_path: str,
    browser_spec_path: str,
    fail_on_todo: bool,
) -> tuple[bool, List[Dict[str, Any]]]:
    gates = _gate_config_from_manifest(manifest)
    checklist = checklist_path.strip() or str(gates.get("ui_parity_checklist", "")).strip()
    smoke_spec = smoke_spec_path.strip() or str(gates.get("ui_smoke_spec", "")).strip()
    browser_spec = browser_spec_path.strip() or str(gates.get("ui_browser_spec", "")).strip()

    fail_on_todo_effective = (
        fail_on_todo
        if fail_on_todo
        else bool(gates.get("ui_checklist_fail_on_todo", False))
    )

    results: List[Dict[str, Any]] = []

    if checklist:
        cmd = [sys.executable, "tools/ui_parity_checklist.py", "--checklist", checklist]
        if fail_on_todo_effective:
            cmd.append("--fail-on-todo")
        print(f"pre-gate checklist: {' '.join(cmd)}")
        res = subprocess.run(cmd, check=False)
        results.append({"gate": "ui_parity_checklist", "command": cmd, "exit_code": int(res.returncode)})

    if smoke_spec:
        cmd = [sys.executable, "tools/ui_smoke_runner.py", "--spec", smoke_spec]
        print(f"pre-gate smoke: {' '.join(cmd)}")
        res = subprocess.run(cmd, check=False)
        results.append({"gate": "ui_smoke_runner", "command": cmd, "exit_code": int(res.returncode)})

    if browser_spec:
        cmd = [sys.executable, "tools/ui_browser_runner.py", "--spec", browser_spec]
        print(f"pre-gate browser: {' '.join(cmd)}")
        res = subprocess.run(cmd, check=False)
        results.append({"gate": "ui_browser_runner", "command": cmd, "exit_code": int(res.returncode)})

    ok = all(item.get("exit_code", 1) == 0 for item in results) if results else True
    return ok, results


def cmd_plan(manifest: Dict[str, Any]) -> int:
    print(f"feature: {manifest.get('feature', '<unknown>')}")
    print(f"service: {manifest.get('service', '<unknown>')}")
    flag = manifest.get("flag", {}) if isinstance(manifest.get("flag"), dict) else {}
    print(f"flag: {flag.get('name', '<none>')} (mode={flag.get('mode', 'percentage')})")
    print("\nstages:")
    for idx, stage in enumerate(_stages(manifest), start=1):
        print(f"{idx}. {stage.get('name')} (percent={stage.get('percent', '?')})")
        print(f"   deploy: {stage.get('deploy_command', '')}")
        print(f"   verify: {stage.get('verify_command', '')}")
        print(f"   rollback: {stage.get('rollback_command', '')}")
    if manifest.get("global_rollback_command"):
        print(f"\nglobal_rollback_command: {manifest.get('global_rollback_command')}")
    gates = _gate_config_from_manifest(manifest)
    if gates:
        print("\npre-promote gates:")
        print(f"- ui_parity_checklist: {gates.get('ui_parity_checklist', '')}")
        print(f"- ui_smoke_spec: {gates.get('ui_smoke_spec', '')}")
        print(f"- ui_browser_spec: {gates.get('ui_browser_spec', '')}")
        print(f"- ui_checklist_fail_on_todo: {bool(gates.get('ui_checklist_fail_on_todo', False))}")
    integrations = _integration_config(manifest)
    if integrations:
        print("\nintegrations:")
        flag_hook = integrations.get("flag_hook", {}) if isinstance(integrations.get("flag_hook"), dict) else {}
        deploy_hook = integrations.get("deploy_hook", {}) if isinstance(integrations.get("deploy_hook"), dict) else {}
        rollback_hook = integrations.get("rollback_hook", {}) if isinstance(integrations.get("rollback_hook"), dict) else {}
        health_check = integrations.get("health_check", {}) if isinstance(integrations.get("health_check"), dict) else {}
        if flag_hook:
            print(f"- flag_hook: {flag_hook.get('method', 'POST')} {flag_hook.get('url', '')}")
        if deploy_hook:
            print(f"- deploy_hook: {deploy_hook.get('method', 'POST')} {deploy_hook.get('url', '')}")
        if rollback_hook:
            print(f"- rollback_hook: {rollback_hook.get('method', 'POST')} {rollback_hook.get('url', '')}")
        if health_check:
            print(f"- health_check: GET {health_check.get('url', '')} expect={health_check.get('expect_status', 200)}")
        flag_provider = integrations.get("flag_provider", {}) if isinstance(integrations.get("flag_provider"), dict) else {}
        deploy_provider = integrations.get("deploy_provider", {}) if isinstance(integrations.get("deploy_provider"), dict) else {}
        slo_policy = integrations.get("slo_policy", {}) if isinstance(integrations.get("slo_policy"), dict) else {}
        if flag_provider:
            print(f"- flag_provider: {flag_provider.get('type', '')}")
        if deploy_provider:
            print(f"- deploy_provider: {deploy_provider.get('type', '')}")
        if slo_policy:
            print(
                f"- slo_policy: health_url={slo_policy.get('health_url', '')} "
                f"max_latency_p95_ms={slo_policy.get('max_latency_p95_ms', '')} "
                f"max_error_rate_pct={slo_policy.get('max_error_rate_pct', '')}"
            )
    return 0


def cmd_status(manifest: Dict[str, Any], state: Dict[str, Any]) -> int:
    print(f"feature: {manifest.get('feature', '<unknown>')}")
    print(f"current_stage: {state.get('current_stage')}")
    print(f"updated_at: {state.get('updated_at')}")
    history = state.get("history", []) if isinstance(state.get("history"), list) else []
    print(f"history_events: {len(history)}")
    for event in history[-5:]:
        if isinstance(event, dict):
            print(f"- {event.get('timestamp')} {event.get('action')} stage={event.get('stage')} ok={event.get('ok')}")
    return 0


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read())
    return h.hexdigest()

def _generate_governance_handoff_packet(manifest: Dict[str, Any], manifest_path: Path, stage_name: str, state: Dict[str, Any], action: str = "promote", parity_report: Dict[str, Any] = None, readiness_report: Dict[str, Any] = None) -> Dict[str, Any]:
    feature = manifest.get("feature", "unknown")
    service = manifest.get("service", f"{feature}_service_v1")
    
    # Try to find artifacts relative to the manifest if possible, otherwise use standard paths
    root_dir = manifest_path.parent.parent.parent
    contract_path = root_dir / f"contracts/{feature}_v1.json"
    registry_path = root_dir / "registry/services.json"
    
    protected_resources_path = manifest_path.parent / f"{feature}_protected_resources.json"
    protected_resources = {}
    if protected_resources_path.exists():
        try:
            with protected_resources_path.open("r", encoding="utf-8") as f:
                protected_resources = json.load(f)
        except Exception:
            pass
            
    risk_profile = manifest.get("risk_profile", {})
    if protected_resources:
        risk_profile = {**risk_profile, **protected_resources.get("risk_profile", {})}
        if "endpoints" in protected_resources:
            risk_profile["protected_endpoints"] = protected_resources["endpoints"]
    if action == "promote" and stage_name.startswith("full_"):
        action_type = "msf.approval_packet.final_cutover"
    elif action == "promote":
        action_type = "msf.approval_packet.promote"
    elif action == "rollback":
        action_type = "msf.approval_packet.rollback"
    else:
        action_type = f"msf.approval_packet.{action}"
        
    requested_action = {
        "action_type": action_type,
        "target_resource": f"service:{service}",
        "stage": stage_name
    }
    if readiness_report:
        requested_action["readiness_status"] = readiness_report.get("status")
        requested_action["unresolved_risks"] = readiness_report.get("unresolved_risks")

    return {
        "schema_version": "msf.governance_handoff.v1",
        "framework": "MSF",
        "feature": feature,
        "service_id": service,
        "cutover_id": f"{feature}_cutover_{_now_iso().split('T')[0].replace('-','')}",
        "stage": "pre_promote",
        "timestamp": _now_iso(),
        "host_app": {
            "name": manifest.get("host_app_name", "legacy_host"),
            "language": manifest.get("host_language", "unknown")
        },
        "generated_artifacts": {
            "contract_path": str(contract_path),
            "service_registry_path": str(registry_path),
            "cutover_manifest_path": str(manifest_path),
            "state_path": str(manifest_path.with_suffix(".state.json"))
        },
        "service_surface": manifest.get("service_surface", {}),
        "risk_profile": risk_profile,
        "parity_summary": parity_report if parity_report else {},
        "rollback_readiness": readiness_report if readiness_report else {},
        "requested_action": {
            **requested_action,
            **manifest.get("governance_action_overrides", {})
        },
        "artifact_hashes": {
            "contract_sha256": _sha256_file(contract_path),
            "service_registry_sha256": _sha256_file(registry_path),
            "cutover_manifest_sha256": _sha256_file(manifest_path)
        },
        "state_history_hash": str(hash(json.dumps(state.get("history", []), sort_keys=True)))
    }

def cmd_promote(
    manifest_path: Path,
    manifest: Dict[str, Any],
    state: Dict[str, Any],
    stage_name: str,
    execute: bool,
    *,
    ui_checklist: str,
    ui_smoke_spec: str,
    ui_browser_spec: str,
    ui_checklist_fail_on_todo: bool,
) -> int:
    stage = _find_stage(manifest, stage_name)
    if stage is None:
        raise ValueError(f"Stage not found: {stage_name}")

    print(f"promote stage: {stage_name}")
    print(f"target_percent: {stage.get('percent', '?')}")

    gates_ok, gate_results = _run_pre_promote_gates(
        manifest,
        checklist_path=ui_checklist,
        smoke_spec_path=ui_smoke_spec,
        browser_spec_path=ui_browser_spec,
        fail_on_todo=ui_checklist_fail_on_todo,
    )
    if gate_results:
        print(f"pre-gates result: {'ok' if gates_ok else 'failed'}")
    if not gates_ok:
        _record(
            state,
            {
                "timestamp": _now_iso(),
                "action": "promote",
                "stage": stage_name,
                "ok": False,
                "blocked_by_gates": True,
                "gate_results": gate_results,
                "executed": execute,
            },
        )
        print("promotion_result: blocked_by_pre_gates")
        return 1

    feature = manifest.get("feature", "unknown")
    parity_log_dir = manifest.get("shadow_log_dir", "")
    parity_report = None
    if parity_log_dir:
        log_path = Path(parity_log_dir) / "parity.jsonl"
        report_path = manifest_path.parent / f"{feature}_parity_report.json"
        
        if not log_path.exists():
            print("promotion_result: halted_by_parity (missing log)")
            _record(state, {"timestamp": _now_iso(), "action": "msf.promotion.halted_by_parity", "reason": "parity_log_missing"})
            return 1
            
        print("parity_handshake: evaluating parity logs...")
        cmd = [sys.executable, "tools/parity_harness.py", "--log-file", str(log_path), "--output", str(report_path)]
        res = subprocess.run(cmd, check=False)
        
        if report_path.exists():
            with report_path.open("r", encoding="utf-8") as f:
                parity_report = json.load(f)
                
        if res.returncode != 0:
            print("promotion_result: halted_by_parity (threshold not met or insufficient samples)")
            _record(state, {"timestamp": _now_iso(), "action": "msf.promotion.halted_by_parity", "reason": "parity_check_failed"})
            return 1

    print("governance_handshake: Generating approval packet...")
    handoff_packet = _generate_governance_handoff_packet(manifest, manifest_path, stage_name, state, action="promote", parity_report=parity_report)
    
    handoff_file = manifest_path.parent / f"{feature}_governance_handoff.json"
    if execute:
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        with handoff_file.open("w", encoding="utf-8") as f:
            json.dump(handoff_packet, f, indent=2)
            f.write("\n")
    
    _record(state, {
        "timestamp": _now_iso(),
        "action": "msf.governance_handoff.generated",
        "stage": stage_name,
        "handoff_file": str(handoff_file)
    })
    
    integrations = _integration_config(manifest)
    gov_cfg = integrations.get("governance", {})
    adapter_type = gov_cfg.get("type", "").strip().lower()

    if adapter_type == "disabled":
        adapter = None
        decision_payload = {"decision": "ALLOW", "reason": "Governance explicitly disabled"}
    elif adapter_type == "http":
        adapter = HttpForgeRootAdapter(url=gov_cfg.get("url", ""), timeout_s=float(gov_cfg.get("timeout_s", 10.0)))
    elif adapter_type == "mock":
        adapter = MockForgeRootAdapter(default_decision="ALLOW")
    else:
        print(f"promotion_result: halted_by_governance (invalid adapter mode: '{adapter_type}')")
        _record(state, {
            "timestamp": _now_iso(),
            "action": "msf.promotion.halted_by_governance",
            "stage": stage_name,
            "reason": f"Invalid or missing governance adapter type: '{adapter_type}'. Must be mock, http, or disabled.",
            "executed": execute
        })
        return 1
        
    print("governance_handshake: Submitting to ForgeRoot admission adapter...")
    if execute:
        _record(state, {
            "timestamp": _now_iso(),
            "action": "msf.governance_handoff.submitted",
            "stage": stage_name,
        })
        if adapter:
            decision_payload = adapter.admit_cutover_promotion(handoff_packet)
    else:
        decision_payload = {"decision": "ALLOW", "reason": "Dry run"}
        
    decision = decision_payload.get("decision", "ERROR")
    print(f"governance_decision: {decision} ({decision_payload.get('reason', '')})")
    
    state_event = {
        "timestamp": _now_iso(),
        "action": f"msf.governance_admission.{decision.lower()}",
        "stage": stage_name,
        "decision_payload": decision_payload,
        "executed": execute,
        "ok": decision == "ALLOW"
    }
    _record(state, state_event)
    
    if decision != "ALLOW":
        _record(state, {
            "timestamp": _now_iso(),
            "action": "msf.promotion.halted_by_governance",
            "stage": stage_name,
            "executed": execute
        })
        print("promotion_result: halted_by_governance")
        return 1

    integrations = _integration_config(manifest)
    integration_results: List[Dict[str, Any]] = []
    percent = int(stage.get("percent", 0)) if str(stage.get("percent", "")).strip() else 0

    flag_ok, flag_event = _run_flag_provider_adapter(integrations, percent=percent, execute=execute)
    if flag_event:
        integration_results.append(flag_event)
    if not flag_ok:
        _record(
            state,
            {
                "timestamp": _now_iso(),
                "action": "promote",
                "stage": stage_name,
                "ok": False,
                "blocked_by_integration": True,
                "integration_results": integration_results,
                "executed": execute,
            },
        )
        print("promotion_result: blocked_by_integration")
        return 1

    deploy_provider_ok, deploy_provider_event = _run_deploy_provider_adapter(integrations, execute=execute)
    if deploy_provider_event:
        integration_results.append(deploy_provider_event)
    if not deploy_provider_ok:
        _record(
            state,
            {
                "timestamp": _now_iso(),
                "action": "promote",
                "stage": stage_name,
                "ok": False,
                "blocked_by_integration": True,
                "integration_results": integration_results,
                "executed": execute,
            },
        )
        print("promotion_result: blocked_by_integration")
        return 1

    if isinstance(integrations.get("flag_hook"), dict):
        ok, event = _http_hook(
            "flag_hook",
            integrations["flag_hook"],
            {
                "feature": manifest.get("feature"),
                "service": manifest.get("service"),
                "stage": stage_name,
                "percent": stage.get("percent"),
                "action": "promote",
            },
            execute=execute,
        )
        integration_results.append(event)
        if not ok:
            _record(
                state,
                {
                    "timestamp": _now_iso(),
                    "action": "promote",
                    "stage": stage_name,
                    "ok": False,
                    "blocked_by_integration": True,
                    "integration_results": integration_results,
                    "executed": execute,
                },
            )
            print("promotion_result: blocked_by_integration")
            return 1

    if isinstance(integrations.get("deploy_hook"), dict):
        ok, event = _http_hook(
            "deploy_hook",
            integrations["deploy_hook"],
            {
                "feature": manifest.get("feature"),
                "service": manifest.get("service"),
                "stage": stage_name,
                "percent": stage.get("percent"),
                "action": "deploy",
            },
            execute=execute,
        )
        integration_results.append(event)
        if not ok:
            _record(
                state,
                {
                    "timestamp": _now_iso(),
                    "action": "promote",
                    "stage": stage_name,
                    "ok": False,
                    "blocked_by_integration": True,
                    "integration_results": integration_results,
                    "executed": execute,
                },
            )
            print("promotion_result: blocked_by_integration")
            return 1

    deploy_rc = _run_command(str(stage.get("deploy_command", "")), execute=execute)
    verify_rc = _run_command(str(stage.get("verify_command", "")), execute=execute)

    ok = deploy_rc == 0 and verify_rc == 0
    if ok and isinstance(integrations.get("health_check"), dict):
        hc_ok, hc_event = _integration_health_check(integrations["health_check"], execute=execute)
        integration_results.append(hc_event)
        ok = ok and hc_ok
    if ok:
        slo_ok, slo_event = _evaluate_slo_policy(manifest, execute=execute)
        if slo_event:
            integration_results.append(slo_event)
        ok = ok and slo_ok
    if ok:
        state["current_stage"] = stage_name

    _record(
        state,
        {
            "timestamp": _now_iso(),
            "action": "promote",
            "stage": stage_name,
            "ok": ok,
            "deploy_exit_code": deploy_rc,
            "verify_exit_code": verify_rc,
            "gate_results": gate_results,
            "integration_results": integration_results,
            "executed": execute,
        },
    )

    print(f"promotion_result: {'ok' if ok else 'failed'}")
    return 0 if ok else 1


def cmd_rollback(manifest_path: Path, manifest: Dict[str, Any], state: Dict[str, Any], execute: bool, checklist_path: str = "") -> int:
    current = state.get("current_stage")
    stage = _find_stage(manifest, current) if isinstance(current, str) else None

    rollback_cmd = ""
    stage_name = current if isinstance(current, str) else "unknown"
    if stage and str(stage.get("rollback_command", "")).strip():
        rollback_cmd = str(stage.get("rollback_command", "")).strip()
    else:
        rollback_cmd = str(manifest.get("global_rollback_command", "")).strip()

    print(f"rollback_from_stage: {stage_name}")
    
    # 1. Rollback Readiness Gate
    feature = manifest.get("feature", "unknown")
    protected_resources_path = manifest_path.parent / f"{feature}_protected_resources.json"
    readiness_report_path = manifest_path.parent / f"{feature}_rollback_readiness.json"
    readiness_report = None
    
    print("rollback_readiness: evaluating...")
    cmd = [
        sys.executable, "tools/rollback_readiness_gate.py",
        "--output", str(readiness_report_path)
    ]
    if protected_resources_path.exists():
        cmd.extend(["--protected-resources", str(protected_resources_path)])
    if checklist_path:
        cmd.extend(["--checklist", checklist_path])
        
    res = subprocess.run(cmd, check=False)
    if readiness_report_path.exists():
        with readiness_report_path.open("r", encoding="utf-8") as f:
            readiness_report = json.load(f)
            
    if readiness_report:
        status = readiness_report.get("status")
        print(f"rollback_readiness_status: {status}")
        
    # 2. Governance Admission for Rollback
    print("governance_handshake: Generating approval packet...")
    handoff_packet = _generate_governance_handoff_packet(manifest, manifest_path, stage_name, state, action="rollback", readiness_report=readiness_report)
    
    handoff_file = manifest_path.parent / f"{feature}_rollback_governance_handoff.json"
    if execute:
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        with handoff_file.open("w", encoding="utf-8") as f:
            json.dump(handoff_packet, f, indent=2)
            f.write("\n")
            
    _record(state, {
        "timestamp": _now_iso(),
        "action": "msf.governance_handoff.generated",
        "stage": stage_name,
        "handoff_file": str(handoff_file),
        "handoff_hash": hash(json.dumps(handoff_packet, sort_keys=True))
    })
    
    integrations = _integration_config(manifest)
    gov_cfg = integrations.get("governance", {})
    adapter_type = gov_cfg.get("type", "").strip().lower()

    if adapter_type == "disabled":
        adapter = None
        decision_payload = {"decision": "ALLOW", "reason": "Governance explicitly disabled"}
    elif adapter_type == "http":
        adapter = HttpForgeRootAdapter(url=gov_cfg.get("url", ""), timeout_s=float(gov_cfg.get("timeout_s", 10.0)))
    elif adapter_type == "mock":
        # Simulate ForgeRoot behavior based on readiness status
        if readiness_report and readiness_report.get("status") in ["REQUIRES_RECONCILIATION", "INSUFFICIENT_EVIDENCE"]:
            decision_payload = {"decision": "BLOCK", "reason": "Insufficient evidence or unreconciled data."}
        elif readiness_report and readiness_report.get("status") == "IRREVERSIBLE_CHANGE_DETECTED":
            decision_payload = {"decision": "REQUIRE_APPROVAL", "reason": "Irreversible change detected, requires manual escalation."}
        else:
            decision_payload = {"decision": "ALLOW", "reason": "Mock ALLOW"}
        adapter = MockForgeRootAdapter(default_decision=decision_payload["decision"])
        
    else:
        print(f"rollback_result: halted_by_governance (invalid adapter mode: '{adapter_type}')")
        _record(state, {
            "timestamp": _now_iso(),
            "action": "msf.rollback.halted_by_governance",
            "stage": stage_name,
            "reason": f"Invalid governance adapter type: '{adapter_type}'"
        })
        return 1
        
    print("governance_handshake: Submitting to ForgeRoot admission adapter...")
    if execute:
        _record(state, {
            "timestamp": _now_iso(),
            "action": "msf.governance_handoff.submitted",
            "stage": stage_name,
        })
        if adapter:
            if adapter_type == "mock":
                # Mock already computed
                pass
            else:
                decision_payload = adapter.admit_cutover_promotion(handoff_packet)
    else:
        decision_payload = {"decision": "ALLOW", "reason": "Dry run"}
        
    decision = decision_payload.get("decision", "ERROR")
    print(f"governance_decision: {decision} ({decision_payload.get('reason', '')})")
    
    state_event = {
        "timestamp": _now_iso(),
        "action": f"msf.governance_admission.{decision.lower()}",
        "stage": stage_name,
        "decision_payload": decision_payload,
        "executed": execute,
        "ok": decision == "ALLOW"
    }
    _record(state, state_event)
    
    if decision != "ALLOW":
        _record(state, {
            "timestamp": _now_iso(),
            "action": "msf.rollback.halted_by_governance",
            "stage": stage_name,
            "executed": execute
        })
        print("rollback_result: halted_by_governance")
        return 1

    integration_results: List[Dict[str, Any]] = []
    integ_ok = True
    flag_provider = integrations.get("flag_provider", {})
    if isinstance(flag_provider, dict) and str(flag_provider.get("type", "")).strip().lower() == "local_env_flag":
        reset_ok, reset_event = _set_local_env_flag(flag_provider, 0, execute=execute)
        integration_results.append(reset_event)
        integ_ok = integ_ok and reset_ok
    if isinstance(integrations.get("rollback_hook"), dict):
        hook_ok, hook_event = _http_hook(
            "rollback_hook",
            integrations["rollback_hook"],
            {
                "feature": manifest.get("feature"),
                "service": manifest.get("service"),
                "stage": stage_name,
                "action": "rollback",
            },
            execute=execute,
        )
        integration_results.append(hook_event)
        integ_ok = integ_ok and hook_ok

    rc = _run_command(rollback_cmd, execute=execute)
    ok = rc == 0 and integ_ok

    if ok:
        state["current_stage"] = None

    _record(
        state,
        {
            "timestamp": _now_iso(),
            "action": "rollback",
            "stage": stage_name,
            "ok": ok,
            "rollback_exit_code": rc,
            "integration_results": integration_results,
            "executed": execute,
        },
    )

    print(f"rollback_result: {'ok' if ok else 'failed'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Cutover orchestration CLI")
    parser.add_argument("action", choices=["plan", "status", "promote", "rollback"], help="Action to run")
    parser.add_argument("--manifest", required=True, help="Path to cutover manifest JSON")
    parser.add_argument("--state", default="", help="Optional custom state file path")
    parser.add_argument("--stage", default="", help="Stage name for promote action")
    parser.add_argument("--execute", action="store_true", help="Execute commands (default is dry-run)")
    parser.add_argument("--ui-checklist", default="", help="Optional checklist path for pre-promote gate")
    parser.add_argument("--ui-smoke-spec", default="", help="Optional smoke spec path for pre-promote gate")
    parser.add_argument("--ui-browser-spec", default="", help="Optional browser journey spec path for pre-promote gate")
    parser.add_argument(
        "--ui-checklist-fail-on-todo",
        action="store_true",
        help="When running checklist gate, treat TODO as failing",
    )
    parser.add_argument("--rollback-checklist", default="", help="Optional checklist path for rollback gate")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    manifest = _load_json(manifest_path)

    state_path = _state_path(manifest_path, args.state)
    state = _load_state(state_path)

    if args.action == "plan":
        return cmd_plan(manifest)
    if args.action == "status":
        return cmd_status(manifest, state)
    if args.action == "promote":
        if not args.stage.strip():
            raise ValueError("--stage is required for promote action")
        rc = cmd_promote(
            manifest_path,
            manifest,
            state,
            args.stage.strip(),
            execute=args.execute,
            ui_checklist=args.ui_checklist,
            ui_smoke_spec=args.ui_smoke_spec,
            ui_browser_spec=args.ui_browser_spec,
            ui_checklist_fail_on_todo=bool(args.ui_checklist_fail_on_todo),
        )
        _save_state(state_path, state)
        print(f"state_file: {state_path}")
        return rc
    if args.action == "rollback":
        rc = cmd_rollback(manifest_path, manifest, state, execute=args.execute, checklist_path=args.rollback_checklist)
        _save_state(state_path, state)
        print(f"state_file: {state_path}")
        return rc
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
