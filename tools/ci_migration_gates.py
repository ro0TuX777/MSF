#!/usr/bin/env python3
"""Run CI migration gates for MFS adoption.

Gates covered:
- contract sanity checks
- service health audit
- container build check
- optional container image vulnerability scan (Trivy)
- optional UI parity checklist and smoke tests
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class GateResult:
    name: str
    ok: bool
    details: str = ""


def _run(cmd: List[str], *, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return int(proc.returncode), out.strip()


def _check_contract_sanity(contract_dir: Path) -> GateResult:
    required_top = {"service_name", "contract_version", "endpoint", "required_fields", "allowed_status"}
    required_status = {"healthy", "degraded", "unavailable"}

    if not contract_dir.exists():
        return GateResult("contract_sanity", False, f"missing contract directory: {contract_dir}")

    bad: List[str] = []
    files = sorted(contract_dir.glob("*.json"))
    if not files:
        return GateResult("contract_sanity", False, f"no contract files found in {contract_dir}")

    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            bad.append(f"{file.name}: invalid JSON ({exc})")
            continue

        missing = [k for k in required_top if k not in payload]
        if missing:
            bad.append(f"{file.name}: missing keys {missing}")
            continue

        if not isinstance(payload.get("required_fields"), dict):
            bad.append(f"{file.name}: required_fields must be object")
        if not isinstance(payload.get("allowed_status"), list):
            bad.append(f"{file.name}: allowed_status must be list")
            continue

        statuses = {s for s in payload.get("allowed_status", []) if isinstance(s, str)}
        missing_status = sorted(required_status - statuses)
        if missing_status:
            bad.append(f"{file.name}: allowed_status missing {missing_status}")

    if bad:
        return GateResult("contract_sanity", False, " | ".join(bad))
    return GateResult("contract_sanity", True, f"validated {len(files)} contract files")


def _health_audit() -> GateResult:
    rc, out = _run([sys.executable, "tools/service_health_audit.py"])
    return GateResult("health_audit", rc == 0, out)


def _compose_build(compose_file: Path, services: List[str]) -> GateResult:
    cmd = ["docker", "compose", "-f", str(compose_file), "build", *services]
    rc, out = _run(cmd)
    return GateResult("container_build", rc == 0, out)


def _scan_images_trivy(images: List[str]) -> GateResult:
    trivy = shutil.which("trivy")
    if not trivy:
        return GateResult("container_scan", False, "trivy binary not found in PATH")

    failures: List[str] = []
    for image in images:
        rc, out = _run([trivy, "image", "--severity", "HIGH,CRITICAL", "--exit-code", "1", image])
        if rc != 0:
            failures.append(f"{image}: vulnerabilities found or scan error ({out[:300]})")
    if failures:
        return GateResult("container_scan", False, " | ".join(failures))
    return GateResult("container_scan", True, f"scanned {len(images)} images")


def _ui_parity(checklist: Path, fail_on_todo: bool) -> GateResult:
    cmd = [sys.executable, "tools/ui_parity_checklist.py", "--checklist", str(checklist)]
    if fail_on_todo:
        cmd.append("--fail-on-todo")
    rc, out = _run(cmd)
    return GateResult("ui_parity", rc == 0, out)


def _ui_smoke(spec: Path) -> GateResult:
    rc, out = _run([sys.executable, "tools/ui_smoke_runner.py", "--spec", str(spec)])
    return GateResult("ui_smoke", rc == 0, out)


def _ui_browser(spec: Path) -> GateResult:
    rc, out = _run([sys.executable, "tools/ui_browser_runner.py", "--spec", str(spec)])
    return GateResult("ui_browser", rc == 0, out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CI migration gates")
    parser.add_argument("--contract-dir", default="contracts", help="Contract directory")
    parser.add_argument("--run-health-audit", action="store_true", help="Run service health audit")
    parser.add_argument("--run-container-build", action="store_true", help="Run docker compose build")
    parser.add_argument("--compose-file", default="docker-compose.yml", help="Compose file for build gate")
    parser.add_argument("--services", default="", help="Comma-separated compose services for build gate")
    parser.add_argument("--run-container-scan", action="store_true", help="Run Trivy image scan")
    parser.add_argument("--scan-images", default="", help="Comma-separated built image names for Trivy scan")
    parser.add_argument("--ui-checklist", default="", help="Optional UI parity checklist JSON")
    parser.add_argument("--ui-checklist-fail-on-todo", action="store_true", help="Treat TODO as fail in UI parity")
    parser.add_argument("--ui-smoke-spec", default="", help="Optional UI smoke JSON spec")
    parser.add_argument("--ui-browser-spec", default="", help="Optional browser journey JSON spec")
    args = parser.parse_args()

    results: List[GateResult] = []

    contract_dir = (ROOT / args.contract_dir).resolve() if not Path(args.contract_dir).is_absolute() else Path(args.contract_dir)
    results.append(_check_contract_sanity(contract_dir))

    if args.run_health_audit:
        results.append(_health_audit())

    if args.run_container_build:
        compose_path = (ROOT / args.compose_file).resolve() if not Path(args.compose_file).is_absolute() else Path(args.compose_file)
        if not compose_path.exists():
            results.append(GateResult("container_build", False, f"compose file missing: {compose_path}"))
        else:
            services = [s.strip() for s in args.services.split(",") if s.strip()]
            results.append(_compose_build(compose_path, services))

    if args.run_container_scan:
        images = [i.strip() for i in args.scan_images.split(",") if i.strip()]
        if not images:
            results.append(GateResult("container_scan", False, "--scan-images is required when --run-container-scan is set"))
        else:
            results.append(_scan_images_trivy(images))

    if args.ui_checklist.strip():
        checklist = Path(args.ui_checklist)
        if not checklist.is_absolute():
            checklist = (ROOT / checklist).resolve()
        if not checklist.exists():
            results.append(GateResult("ui_parity", False, f"checklist not found: {checklist}"))
        else:
            results.append(_ui_parity(checklist, args.ui_checklist_fail_on_todo))

    if args.ui_smoke_spec.strip():
        spec = Path(args.ui_smoke_spec)
        if not spec.is_absolute():
            spec = (ROOT / spec).resolve()
        if not spec.exists():
            results.append(GateResult("ui_smoke", False, f"smoke spec not found: {spec}"))
        else:
            results.append(_ui_smoke(spec))

    if args.ui_browser_spec.strip():
        spec = Path(args.ui_browser_spec)
        if not spec.is_absolute():
            spec = (ROOT / spec).resolve()
        if not spec.exists():
            results.append(GateResult("ui_browser", False, f"browser spec not found: {spec}"))
        else:
            results.append(_ui_browser(spec))

    print("migration_gates_summary:")
    failed = 0
    for item in results:
        status = "PASS" if item.ok else "FAIL"
        print(f"- {status}: {item.name}")
        if item.details:
            print(f"  details: {item.details[:1200]}")
        if not item.ok:
            failed += 1

    print(f"\nresult: {'PASS' if failed == 0 else 'FAIL'} ({len(results) - failed}/{len(results)} gates passed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
