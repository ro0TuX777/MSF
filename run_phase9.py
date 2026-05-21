import json
import subprocess
import sys
import shutil
import re
from pathlib import Path

def run_cmd(cmd):
    print(f"\n--- Running: {' '.join(cmd)} ---")
    res = subprocess.run(cmd, check=False)
    return res.returncode

def validate_durable_receipt(receipt):
    if not receipt:
        raise ValueError("Receipt is missing or empty")
    if receipt.startswith("fr_receipt_stub_"):
        raise ValueError(f"Receipt is a deterministic stub, which is rejected in Phase 9: {receipt}")
    if not isinstance(receipt, str):
        raise ValueError(f"Receipt is not a string: {receipt}")
    print(f"  [PASS] Receipt is durable: {receipt}")

def check_state_file(state_path, expected_decision):
    if not state_path.exists():
        raise ValueError(f"State file {state_path} does not exist")
    with state_path.open("r", encoding="utf-8") as f:
        state = json.load(f)
        
    # Find the latest admission action
    admission_event = None
    for event in reversed(state.get("history", [])):
        if "msf.governance_admission." in event.get("action", ""):
            admission_event = event
            break
            
    if not admission_event:
        raise ValueError("No governance admission event found in state file")
        
    payload = admission_event.get("decision_payload", {})
    decision = payload.get("decision")
    receipt = payload.get("receipt_ref")
    
    assert decision == expected_decision, f"Expected {expected_decision}, got {decision}"
    validate_durable_receipt(receipt)
    print(f"  [PASS] State file verified. Decision: {decision}, Receipt: {receipt}")
    return receipt

def check_closeout_summary(closeout_path, expected_receipt):
    if not closeout_path.exists():
        raise ValueError(f"Closeout summary {closeout_path} does not exist")
    with closeout_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)
        
    receipt_found = False
    for event in summary.get("timeline", []):
        if expected_receipt in str(event):
            receipt_found = True
            break
            
    assert receipt_found, "Durable receipt was not found in closeout_summary.json"
    print("  [PASS] Closeout summary verified. Receipt propagates correctly.")

def main():
    workspace = Path(".")
    docs_gen = workspace / "docs" / "_generated"
    pack_dir = workspace / "pack"
    
    # ---------------------------------------------------------
    # SCENARIO A: Low-Risk ALLOW
    # ---------------------------------------------------------
    print("\n==================================================")
    print(">>> SCENARIO A: Low-Risk ALLOW (internal_metrics)")
    print("==================================================")
    
    # Generate fresh manifest
    run_cmd([
        sys.executable, "tools/scaffold_cutover.py", 
        "--feature", "internal_metrics", 
        "--source-dir", "legacy_apps/internal_metrics", 
        "--contract", "contracts/internal_v1.json", 
        "--force"
    ])
    
    manifest_a_path = docs_gen / "internal_metrics_cutover.json"
    manifest_a = json.loads(manifest_a_path.read_text())
    manifest_a["integrations"] = {
        "governance": {
            "type": "http",
            "url": "http://127.0.0.1:8081/api/v1/admit"
        }
    }
    manifest_a["shadow_log_dir"] = "shadow"
    manifest_a_path.write_text(json.dumps(manifest_a, indent=2))
    
    # Generate passing parity logs
    parity_log = workspace / "shadow" / "parity.jsonl"
    parity_log.parent.mkdir(exist_ok=True)
    with parity_log.open("w") as f:
        for _ in range(30):
            f.write(json.dumps({
                "method": "GET", 
                "path": "/api/health", 
                "match": True, 
                "mismatched_keys": [],
                "metadata": {"traffic_source": "internal"}
            }) + "\n")
            
    # Promote to canary_5
    rc = run_cmd([
        sys.executable, "tools/cutover_orchestrator.py", "promote",
        "--manifest", str(manifest_a_path),
        "--stage", "canary_5",
        "--execute"
    ])
    assert rc == 0, "Scenario A failed promotion"
    receipt_a = check_state_file(manifest_a_path.with_suffix(".state.json"), "ALLOW")
    
    # Advance all the way and build pack
    run_cmd([sys.executable, "tools/cutover_orchestrator.py", "promote", "--manifest", str(manifest_a_path), "--stage", "canary_25", "--execute"])
    run_cmd([sys.executable, "tools/cutover_orchestrator.py", "promote", "--manifest", str(manifest_a_path), "--stage", "full_100", "--execute"])
    
    for f in docs_gen.glob("*"):
        if f.is_file():
            shutil.copy(str(f), str(workspace / f.name.replace("internal-metrics", "internal_metrics")))
    
    # build_migration_pack relies on this specific filename in the root
    (workspace / "cutover_manifest.json").write_text(manifest_a_path.read_text())
            
    run_cmd([sys.executable, "tools/build_migration_pack.py", "--workspace", ".", "--output-dir", "pack"])
    check_closeout_summary(pack_dir / "closeout_summary.json", receipt_a)

    # ---------------------------------------------------------
    # SCENARIO B: High-Risk REQUIRE_APPROVAL
    # ---------------------------------------------------------
    print("\n==================================================")
    print(">>> SCENARIO B: High-Risk REQUIRE_APPROVAL")
    print("==================================================")
    
    manifest_b_path = docs_gen / "high_risk_cutover.json"
    manifest_b = json.loads(manifest_a_path.read_text())
    manifest_b["feature"] = "payments_module"
    manifest_b["risk_profile"] = {
        "data_sensitivity": "high",
        "governance_risk": "requires_policy",
        "sensitive_domains": ["payments", "pii"],
        "mutation_risk": "possible",
        "auth_required": True,
        "payment_touching": True,
        "pii_touching": True
    }
    # Create protected resources
    prot_res_path = docs_gen / "payments_module_protected_resources.json"
    prot_res_path.write_text(json.dumps({
        "endpoints": {
            "POST /api/payments": {
                "risk_category": "critical",
                "required_controls": ["strict_authorization", "operator_approval"]
            }
        }
    }))
    manifest_b_path.write_text(json.dumps(manifest_b, indent=2))
    
    # Reset state file
    state_b_path = manifest_b_path.with_suffix(".state.json")
    if state_b_path.exists():
        state_b_path.unlink()
        
    rc = run_cmd([
        sys.executable, "tools/cutover_orchestrator.py", "promote",
        "--manifest", str(manifest_b_path),
        "--stage", "canary_5",
        "--execute"
    ])
    assert rc != 0, "Scenario B incorrectly passed promotion!"
    receipt_b = check_state_file(state_b_path, "REQUIRE_APPROVAL")


    # ---------------------------------------------------------
    # SCENARIO C: Unsafe ESCALATE / BLOCK
    # ---------------------------------------------------------
    print("\n==================================================")
    print(">>> SCENARIO C: Unsafe ESCALATE/BLOCK (Irreversible)")
    print("==================================================")
    
    manifest_c_path = docs_gen / "unsafe_cutover.json"
    manifest_c = json.loads(manifest_a_path.read_text())
    manifest_c["feature"] = "unsafe_module"
    manifest_c_path.write_text(json.dumps(manifest_c, indent=2))
    
    state_c_path = manifest_c_path.with_suffix(".state.json")
    if state_c_path.exists():
        state_c_path.unlink()
        
    # We will invoke the rollback command to trigger the irreversible check
    # We fake an irreversible report
    readiness_path = docs_gen / "unsafe_module_rollback_readiness.json"
    readiness_path.write_text(json.dumps({
        "status": "IRREVERSIBLE_CHANGE_DETECTED",
        "irreversible_mutations_occurred": True,
        "data_reconciled": False
    }))
    
    # We need to monkeypatch or bypass the local MSF block for scenario C
    # Actually, if we use the rollback command in cutover_orchestrator, it sends the packet and asks for admission for rollback
    # The ForgeRoot stub should return BLOCK for this
    
    # We can just send a direct request to prove ForgeRoot's behavior, since MSF handles its own local blocking anyway.
    # The requirement is: "MSF’s responsibility is to supply realistic multi-scenario governance packets... run_phase9.py may construct scenario packets"
    import requests
    payload = {
        "schema_version": "msf.governance_handoff.v1",
        "service_surface": {"feature": "test"},
        "requested_action": {"action_type": "msf.approval_packet.rollback"},
        "risk_profile": {},
        "parity_summary": {"status": "PASS"},
        "rollback_readiness": {
            "status": "IRREVERSIBLE_CHANGE_DETECTED",
            "irreversible_mutations_occurred": True,
            "data_reconciled": False
        },
        "state_history_hash": "hash"
    }
    resp = requests.post("http://127.0.0.1:8081/api/v1/admit", json=payload)
    data = resp.json()
    assert data["decision"] in ["ESCALATE", "BLOCK"], f"Expected ESCALATE/BLOCK, got {data}"
    validate_durable_receipt(data["receipt_ref"])
    print(f"  [PASS] Scenario C handled correctly: {data['decision']}")
    
    print("\n==================================================")
    print("SUCCESS: Phase 9 multi-scenario testing verified.")
    print("==================================================")

if __name__ == "__main__":
    main()
