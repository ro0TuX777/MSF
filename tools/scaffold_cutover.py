#!/usr/bin/env python3
"""Scaffold a cutover orchestration manifest for a feature.

Usage:
  python tools/scaffold_cutover.py --feature sentiment-analysis
"""

from __future__ import annotations

import argparse
import re
import json
import sys
import subprocess
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "templates" / "cutover" / "cutover_manifest.json.tmpl"


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Feature name must contain at least one alphanumeric character")
    return slug


def _snake(slug: str) -> str:
    return slug.replace("-", "_")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold cutover manifest")
    parser.add_argument("--feature", required=True, help="Feature name, e.g. sentiment-analysis")
    parser.add_argument("--output", default="", help="Output file path")
    parser.add_argument("--force", action="store_true", help="Overwrite output file if it exists")
    parser.add_argument("--source-dir", default="", help="Candidate source directory for risk profiling")
    parser.add_argument("--contract", default="", help="Path to API contract")
    args = parser.parse_args()

    feature_slug = _slugify(args.feature)
    feature_snake = _snake(feature_slug)
    service_name = f"{feature_slug}-service"
    flag_name = f"MFS_{feature_snake.upper()}_ROLLOUT_PERCENT"

    output_path = Path(args.output).resolve() if args.output else (ROOT / "docs" / "_generated" / f"{feature_snake}_cutover.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not args.force:
        raise FileExistsError(f"Output file already exists: {output_path}. Use --force to overwrite.")

    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))
    rendered = template.substitute(
        {
            "feature_slug": feature_slug,
            "service_name": service_name,
            "flag_name": flag_name,
        }
    )
    
    manifest_data = json.loads(rendered)
    manifest_data["risk_profile"] = {
        "data_sensitivity": "unknown",
        "governance_risk": "standard",
        "sensitive_domains": []
    }
    
    if args.source_dir:
        pr_path = ROOT / "docs" / "_generated" / f"{feature_snake}_protected_resources.json"
        cmd = [
            sys.executable, 
            str(ROOT / "tools" / "assess_candidate_risk.py"), 
            "--source-dir", args.source_dir, 
            "--output", str(pr_path)
        ]
        if args.contract:
            cmd.extend(["--contract", args.contract])
            
        print(f"Running risk assessment on {args.source_dir}...")
        res = subprocess.run(cmd, check=False)
        if res.returncode == 0 and pr_path.exists():
            pr_data = json.loads(pr_path.read_text(encoding="utf-8"))
            if "risk_profile" in pr_data:
                manifest_data["risk_profile"] = pr_data["risk_profile"]
                print("Injected risk_profile into cutover manifest.")

    output_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    print(f"Generated cutover manifest: {output_path}")
    print(f"Feature: {feature_slug}")
    print(f"Flag: {flag_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
