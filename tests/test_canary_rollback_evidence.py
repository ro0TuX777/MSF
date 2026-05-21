import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.cutover_orchestrator import cmd_rollback, _load_state

def test_rollback_readiness_and_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        feature = "payment_processor"
        manifest_path = tmp_path / f"{feature}_cutover.json"
        
        manifest_data = {
            "feature": feature,
            "service": f"{feature}_v1",
            "stages": [
                {"name": "canary_10", "percent": 10, "rollback_command": "echo rollback10"}
            ],
            "integrations": {"governance": {"type": "mock"}}
        }
        manifest_path.write_text(json.dumps(manifest_data))
        
        state_path = manifest_path.with_suffix(".state.json")
        state = {"current_stage": "canary_10", "history": []}
        
        protected_resources_path = tmp_path / f"{feature}_protected_resources.json"
        protected_resources_path.write_text(json.dumps({
            "risk_profile": {
                "data_sensitivity": "high",
                "governance_risk": "requires_policy"
            }
        }))
        
        checklist_path = tmp_path / f"{feature}_rollback_checklist.json"
        checklist_path.write_text(json.dumps({
            "irreversible_mutations_occurred": False,
            "data_reconciled": False,
            "notes": "Still checking DB"
        }))
        
        # Test 1: Requires reconciliation (High sensitivity, no reconciliation)
        rc = cmd_rollback(manifest_path, manifest_data, state, True, checklist_path=str(checklist_path))
        assert rc == 1  # Should halt
        assert len(state["history"]) > 0
        last_event = state["history"][-1]
        assert last_event["action"] == "msf.rollback.halted_by_governance"
        admission_event = state["history"][-2]
        assert admission_event["action"] == "msf.governance_admission.block"
        
        # Test 2: Irreversible change detected
        checklist_path.write_text(json.dumps({
            "irreversible_mutations_occurred": True,
            "data_reconciled": False,
            "notes": "DB dropped"
        }))
        state["history"] = []
        rc = cmd_rollback(manifest_path, manifest_data, state, True, checklist_path=str(checklist_path))
        assert rc == 1  # Halts because mock requires_approval returns non-ALLOW effectively
        admission_event = state["history"][-2]
        assert admission_event["action"] == "msf.governance_admission.require_approval"
        
        # Test 3: Ready
        checklist_path.write_text(json.dumps({
            "irreversible_mutations_occurred": False,
            "data_reconciled": True,
            "notes": "All safe"
        }))
        state["history"] = []
        rc = cmd_rollback(manifest_path, manifest_data, state, True, checklist_path=str(checklist_path))
        assert rc == 0  # Should pass
        
        # Verify approval packet was created
        handoff_file = tmp_path / f"{feature}_rollback_governance_handoff.json"
        assert handoff_file.exists()
        handoff_data = json.loads(handoff_file.read_text())
        assert handoff_data["requested_action"]["action_type"] == "msf.approval_packet.rollback"
        assert handoff_data["requested_action"]["readiness_status"] == "READY"
        assert "state_history_hash" in handoff_data
