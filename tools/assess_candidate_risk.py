#!/usr/bin/env python3
"""Assess Candidate Risk
Statically analyzes a candidate codebase and API contract to determine protected resources
and sensitive domains.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

HEURISTICS = {
    "auth": ["login", "authenticate", "oauth", "jwt", "session", "password", "sign_in"],
    "payments": ["stripe", "checkout", "credit_card", "payment", "billing", "invoice", "transaction"],
    "identity": ["user", "profile", "account", "identity", "ssn"],
    "permissions": ["role", "rbac", "permission", "authorize", "grant", "admin"],
    "credentials": ["secret", "token", "api_key", "keypair", "credential"],
    "pii": ["email", "phone", "address", "dob", "birth", "social_security"]
}

def scan_file(path: Path) -> Set[str]:
    found_domains = set()
    try:
        content = path.read_text(encoding="utf-8").lower()
        for domain, keywords in HEURISTICS.items():
            if any(kw in content for kw in keywords):
                found_domains.add(domain)
    except Exception:
        pass
    return found_domains

def scan_directory(target_dir: Path) -> Set[str]:
    found_domains = set()
    for ext in [".py", ".js", ".ts", ".go", ".java", ".rb", ".json", ".sql", ".md"]:
        for path in target_dir.rglob(f"*{ext}"):
            if any(part.startswith(".") or part in ["node_modules", "venv", "__pycache__"] for part in path.parts):
                continue
            found_domains.update(scan_file(path))
    return found_domains

def analyze_endpoint(method: str, path: str, global_domains: Set[str]) -> Dict[str, Any]:
    url_lower = path.lower()
    endpoint_domains = set()
    for domain, keywords in HEURISTICS.items():
        if any(kw in url_lower for kw in keywords):
            endpoint_domains.add(domain)
            
    is_mutating = method.upper() in ["POST", "PUT", "PATCH", "DELETE"]
    
    if "auth" in endpoint_domains or "payments" in endpoint_domains or "permissions" in endpoint_domains:
        risk = "critical"
    elif "pii" in endpoint_domains or "identity" in endpoint_domains:
        risk = "high"
    elif is_mutating:
        risk = "medium"
    else:
        risk = "low"
        
    return {
        "risk_level": risk,
        "domains": list(endpoint_domains)
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Candidate Risk Profile")
    parser.add_argument("--source-dir", required=True, help="Directory containing candidate source")
    parser.add_argument("--contract", help="Path to service contract JSON (e.g. feature_v1.json)")
    parser.add_argument("--output", required=True, help="Path to write protected_resources.json")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    out_path = Path(args.output).resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        print(f"Error: Source directory not found: {source_dir}", file=sys.stderr)
        return 1

    domains = scan_directory(source_dir)
    
    endpoints_risk = {}
    if args.contract:
        contract_path = Path(args.contract).resolve()
        if contract_path.exists():
            try:
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                for method, path_dict in contract.get("endpoints", {}).items():
                    for path in path_dict.keys():
                        ep_key = f"{method.upper()} {path}"
                        endpoints_risk[ep_key] = analyze_endpoint(method, path, domains)
            except Exception as e:
                print(f"Warning: Failed to parse contract {contract_path}: {e}", file=sys.stderr)

    is_high_risk = any(d in domains for d in ["auth", "payments", "permissions", "pii"])
    is_medium_risk = "identity" in domains or "credentials" in domains
    
    data_sensitivity = "high" if is_high_risk else ("medium" if is_medium_risk else "low")
    governance_risk = "requires_policy" if data_sensitivity in ["high", "medium"] else "standard"

    manifest = {
        "schema_version": "msf.protected_resources.v1",
        "risk_profile": {
            "data_sensitivity": data_sensitivity,
            "governance_risk": governance_risk,
            "sensitive_domains": list(domains)
        },
        "endpoints": endpoints_risk
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps(manifest, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
