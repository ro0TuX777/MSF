import json
import tempfile
from pathlib import Path
from unittest import mock
import pytest
import sys
import os

# Ensure tools can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.cutover_orchestrator import _generate_governance_handoff_packet, cmd_promote, _load_state
from tools.governance_adapters.mock_forgeroot import MockForgeRootAdapter
from tools.governance_adapters.http_forgeroot import HttpForgeRootAdapter

@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # Create mock artifacts
        docs_dir = tmp_path / "docs" / "_generated"
        docs_dir.mkdir(parents=True)
        
        manifest_path = docs_dir / "billing_cutover.json"
        manifest_data = {
            "feature": "billing",
            "service": "billing_service_v1",
            "stages": [
                {"name": "canary_10", "percent": 10, "deploy_command": "echo 'deploying'", "verify_command": "echo 'verifying'"}
            ],
            "risk_profile": {
                "data_sensitivity": "low",
                "governance_risk": "standard"
            },
            "integrations": {
                "governance": {
                    "type": "mock"
                }
            }
        }
        manifest_path.write_text(json.dumps(manifest_data))
        
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        contract_path = contracts_dir / "billing_v1.json"
        contract_path.write_text("{}")
        
        registry_dir = tmp_path / "registry"
        registry_dir.mkdir()
        registry_path = registry_dir / "services.json"
        registry_path.write_text("{}")
        
        yield tmp_path, manifest_path, manifest_data

def test_handoff_packet_generated(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    state = {}
    packet = _generate_governance_handoff_packet(manifest_data, manifest_path, "canary_10", state)
    
    assert packet["feature"] == "billing"
    assert packet["service_id"] == "billing_service_v1"
    assert "contract_path" in packet["generated_artifacts"]
    assert "cutover_manifest_path" in packet["generated_artifacts"]
    assert packet["requested_action"]["proposed_stage"] == "canary_10"
    assert "contract_sha256" in packet["artifact_hashes"]

def run_mock_promote(tmp_path, manifest_path, manifest_data, decision="ALLOW", force_allow_sensitive=False):
    if decision:
        manifest_data["governance_action_overrides"] = {"mock_decision": decision, "force_allow_sensitive": force_allow_sensitive}
    
    state = _load_state(manifest_path.with_suffix(".state.json"))
    
    rc = cmd_promote(
        manifest_path=manifest_path,
        manifest=manifest_data,
        state=state,
        stage_name="canary_10",
        execute=True,
        ui_checklist="",
        ui_smoke_spec="",
        ui_browser_spec="",
        ui_checklist_fail_on_todo=False
    )
    
    return rc, state

def test_allow_permits_promotion(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="ALLOW")
    assert rc == 0
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.governance_admission.allow" in events
    
def test_block_halts_promotion(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="BLOCK")
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.governance_admission.block" in events
    assert "msf.promotion.halted_by_governance" in events

def test_require_approval_halts_promotion(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="REQUIRE_APPROVAL")
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.governance_admission.require_approval" in events
    assert "msf.promotion.halted_by_governance" in events

def test_adapter_failure_fails_closed(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    # Force an unknown decision to trigger ERROR
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="UNKNOWN_BLAH")
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.governance_admission.error" in events
    assert "msf.promotion.halted_by_governance" in events

def test_sensitive_candidate_blocks_promotion(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    manifest_data["risk_profile"] = {
        "data_sensitivity": "high",
        "governance_risk": "requires_policy"
    }
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="ALLOW", force_allow_sensitive=False)
    # The mock adapter blocks sensitive candidates without policy
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.governance_admission.block" in events
    assert "msf.promotion.halted_by_governance" in events

def test_backward_compatibility(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    
    # Dry run should pass without invoking full governance logic
    state = _load_state(manifest_path.with_suffix(".state.json"))
    rc = cmd_promote(
        manifest_path=manifest_path,
        manifest=manifest_data,
        state=state,
        stage_name="canary_10",
        execute=False,
        ui_checklist="",
        ui_smoke_spec="",
        ui_browser_spec="",
        ui_checklist_fail_on_todo=False
    )
    assert rc == 0

def test_missing_or_invalid_adapter_mode_halts(temp_workspace):
    tmp_path, manifest_path, manifest_data = temp_workspace
    
    # Missing governance type
    manifest_data["integrations"] = {}
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="ALLOW")
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.promotion.halted_by_governance" in events
    
    # Invalid governance type
    manifest_data["integrations"] = {"governance": {"type": "invalid_type"}}
    rc, state = run_mock_promote(tmp_path, manifest_path, manifest_data, decision="ALLOW")
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.promotion.halted_by_governance" in events

