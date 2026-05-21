#!/usr/bin/env python3
"""Preview ForgeRoot Policy
Generates a ForgeRoot-compatible YAML policy preview based on the assessed candidate risk and protected resources manifest.
"""

import argparse
import json
import sys
from pathlib import Path

def generate_policy(feature: str, manifest: dict) -> str:
    lines = []
    lines.append("apiVersion: forgeroot.msf/v1alpha1")
    lines.append("kind: ProtectedResourcePolicy")
    lines.append("metadata:")
    lines.append(f"  name: {feature}-policy")
    lines.append(f"  description: Automatically generated policy preview for {feature}")
    
    risk_profile = manifest.get("risk_profile", {})
    lines.append("spec:")
    lines.append(f"  dataSensitivity: {risk_profile.get('data_sensitivity', 'unknown')}")
    lines.append(f"  governanceRisk: {risk_profile.get('governance_risk', 'unknown')}")
    
    domains = risk_profile.get("sensitive_domains", [])
    if domains:
        lines.append("  sensitiveDomains:")
        for d in sorted(domains):
            lines.append(f"    - {d}")
            
    endpoints = manifest.get("endpoints", {})
    if endpoints:
        lines.append("  rules:")
        for ep, ep_data in sorted(endpoints.items()):
            lines.append(f"    - endpoint: \"{ep}\"")
            lines.append(f"      riskLevel: {ep_data.get('risk_level', 'unknown')}")
            ep_domains = ep_data.get("domains", [])
            if ep_domains:
                lines.append(f"      domains: [{', '.join(ep_domains)}]")
            
            if ep_data.get('risk_level') in ['critical', 'high']:
                lines.append("      requires:")
                lines.append("        - authentication")
                if "permissions" in ep_domains or "payments" in ep_domains:
                    lines.append("        - strict_authorization")
    
    return "\n".join(lines)

def main() -> int:
    parser = argparse.ArgumentParser(description="Preview ForgeRoot Policy")
    parser.add_argument("--feature", required=True, help="Feature name")
    parser.add_argument("--manifest", required=True, help="Path to protected_resources.json")
    parser.add_argument("--output", required=True, help="Path to write policy YAML")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.output).resolve()

    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading manifest: {e}", file=sys.stderr)
        return 1

    yaml_str = generate_policy(args.feature, manifest)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_str, encoding="utf-8")
    
    print(yaml_str)
    return 0

if __name__ == "__main__":
    sys.exit(main())
