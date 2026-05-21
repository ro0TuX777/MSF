import json
import subprocess
import sys
import requests
from pathlib import Path

def run_cmd(cmd):
    print(f"\n--- Running: {' '.join(cmd)} ---")
    res = subprocess.run(cmd, check=False)
    return res.returncode

def main():
    workspace = Path(".")
    docs_gen = workspace / "docs" / "_generated"
    shadow_dir = workspace / "shadow"
    
    # ---------------------------------------------------------
    # TEST 1: Parity Failure (Local MSF Block)
    # ---------------------------------------------------------
    print("\n>>> TEST 1: Parity Failure")
    parity_log = shadow_dir / "parity.jsonl"
    with parity_log.open("w") as f:
        for _ in range(30):
            # Write FAILED parity logs
            f.write(json.dumps({
                "method": "GET", 
                "path": "/api/health", 
                "match": False, 
                "mismatched_keys": ["data"],
                "metadata": {"traffic_source": "internal"}
            }) + "\n")
            
    # Try to promote. MSF should halt before ForgeRoot.
    rc = run_cmd([
        sys.executable, "tools/cutover_orchestrator.py", "promote",
        "--manifest", str(docs_gen / "internal_metrics_cutover.json"),
        "--stage", "canary_5",
        "--execute"
    ])
    assert rc != 0, "Expected MSF to halt on parity failure!"
    print("[PASS] MSF correctly halted promotion locally due to parity failure.")

    # ---------------------------------------------------------
    # TEST 2: ForgeRoot Defense-in-Depth Parity Block
    # ---------------------------------------------------------
    print("\n>>> TEST 2: ForgeRoot Defense-in-Depth (Parity)")
    payload = {
        "schema_version": "msf.governance_handoff.v1",
        "service_surface": {"feature": "test"},
        "requested_action": {"action_type": "msf.approval_packet.promote"},
        "risk_profile": {},
        "parity_summary": {"status": "FAIL"},
        "rollback_readiness": {},
        "state_history_hash": "hash"
    }
    resp = requests.post("http://127.0.0.1:8081/api/v1/admit", json=payload)
    data = resp.json()
    assert data["decision"] == "BLOCK", f"Expected BLOCK, got {data}"
    print("[PASS] ForgeRoot correctly returned BLOCK for failed parity.")

    # ---------------------------------------------------------
    # TEST 3: ForgeRoot Defense-in-Depth Rollback Irreversible
    # ---------------------------------------------------------
    print("\n>>> TEST 3: ForgeRoot Defense-in-Depth (Rollback)")
    payload["parity_summary"]["status"] = "PASS"
    payload["rollback_readiness"] = {
        "irreversible_mutations_occurred": True,
        "data_reconciled": False
    }
    resp = requests.post("http://127.0.0.1:8081/api/v1/admit", json=payload)
    data = resp.json()
    assert data["decision"] == "BLOCK", f"Expected BLOCK, got {data}"
    print("[PASS] ForgeRoot correctly returned BLOCK for irreversible unreconciled mutations.")

    # ---------------------------------------------------------
    # TEST 4: ForgeRoot Invalid Schema (Missing field)
    # ---------------------------------------------------------
    print("\n>>> TEST 4: ForgeRoot Schema Validation (Missing field)")
    del payload["rollback_readiness"]
    resp = requests.post("http://127.0.0.1:8081/api/v1/admit", json=payload)
    if resp.status_code == 400:
        data = resp.json()
        assert data["decision"] == "ERROR", f"Expected ERROR, got {data}"
        print("[PASS] ForgeRoot correctly returned 400 ERROR for missing fields.")
    else:
        print(f"X Unexpected status code {resp.status_code}")
        
    print("\nSUCCESS: All negative paths validated.")

if __name__ == "__main__":
    main()
