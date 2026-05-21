#!/usr/bin/env python3
"""Evaluate Rollback Readiness
Combines automated risk scans with manual checklists to determine if a rollback is safe.
"""

import argparse
import json
import sys
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser(description="Rollback Readiness Gate")
    parser.add_argument("--protected-resources", help="Path to protected_resources.json")
    parser.add_argument("--checklist", help="Path to manual rollback checklist JSON")
    parser.add_argument("--output", required=True, help="Path to output readiness result JSON")
    args = parser.parse_args()

    protected_resources = {}
    if args.protected_resources:
        pr_path = Path(args.protected_resources).resolve()
        if pr_path.exists():
            try:
                protected_resources = json.loads(pr_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    checklist = {}
    if args.checklist:
        cl_path = Path(args.checklist).resolve()
        if cl_path.exists():
            try:
                checklist = json.loads(cl_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    risk_profile = protected_resources.get("risk_profile", {})
    data_sensitivity = risk_profile.get("data_sensitivity", "unknown")
    
    irreversible = checklist.get("irreversible_mutations_occurred", False)
    reconciled = checklist.get("data_reconciled", False)
    
    unresolved_risks = []
    
    if irreversible:
        status = "IRREVERSIBLE_CHANGE_DETECTED"
        unresolved_risks.append("Manual checklist marked irreversible mutations occurred.")
    elif data_sensitivity == "high":
        if not args.checklist:
            status = "INSUFFICIENT_EVIDENCE"
            unresolved_risks.append("High sensitivity service requires a manual rollback checklist.")
        elif not reconciled:
            status = "REQUIRES_RECONCILIATION"
            unresolved_risks.append("High sensitivity service has unreconciled data mutations.")
        else:
            status = "READY"
    elif data_sensitivity == "medium":
        if not reconciled:
            status = "READY_WITH_WARNINGS"
            unresolved_risks.append("Medium sensitivity service rolled back without explicit reconciliation.")
        else:
            status = "READY"
    else:
        status = "READY"
        
    result = {
        "status": status,
        "unresolved_risks": unresolved_risks,
        "notes": checklist.get("notes", "")
    }
    
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
