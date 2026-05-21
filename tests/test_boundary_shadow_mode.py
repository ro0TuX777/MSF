import json
import tempfile
import sys
import os
import subprocess
from pathlib import Path
from unittest import mock
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from boundary_sdk.client import BoundaryClient, BoundaryConfig
from tools.cutover_orchestrator import cmd_promote, _load_state

@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        docs_dir = tmp_path / "docs" / "_generated"
        docs_dir.mkdir(parents=True)
        
        shadow_log_dir = tmp_path / "shadow"
        shadow_log_dir.mkdir()
        
        manifest_path = docs_dir / "billing_cutover.json"
        manifest_data = {
            "feature": "billing",
            "service": "billing_service_v1",
            "stages": [
                {"name": "canary_10", "percent": 10}
            ],
            "shadow_log_dir": str(shadow_log_dir),
            "integrations": {"governance": {"type": "mock"}}
        }
        manifest_path.write_text(json.dumps(manifest_data))
        
        yield tmp_path, manifest_path, manifest_data, shadow_log_dir

def test_shadow_mode_returns_legacy_and_logs(temp_workspace):
    tmp_path, _, _, log_dir = temp_workspace
    cfg = BoundaryConfig(base_url="http://fake", shadow_mode=True, shadow_log_dir=str(log_dir))
    client = BoundaryClient(cfg)
    
    def fallback(err):
        return {"amount": 100, "status": "healthy"}
        
    with mock.patch('requests.get') as mock_get:
        mock_resp = mock.Mock()
        mock_resp.json.return_value = {"amount": 100}
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        
        res = client.request_json("GET", "/api/v1/billing", fallback=fallback)
        
        # 1. Shadow mode returns legacy response
        assert res["amount"] == 100
        assert res["source"] == "local_fallback"
        
        # 3. parity.jsonl event is written
        log_file = log_dir / "parity.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().splitlines()
        event = json.loads(lines[0])
        assert event["match"] is True
        assert "timestamp" in event
        assert event["path"] == "/api/v1/billing"

def test_shadow_service_failure_does_not_disrupt_legacy(temp_workspace):
    tmp_path, _, _, log_dir = temp_workspace
    cfg = BoundaryConfig(base_url="http://fake", shadow_mode=True, shadow_log_dir=str(log_dir), retries=0)
    client = BoundaryClient(cfg)
    
    def fallback(err):
        return {"amount": 100}
        
    with mock.patch('requests.get', side_effect=Exception("Timeout")):
        res = client.request_json("GET", "/api/v1/billing", fallback=fallback)
        
        # 2. Shadow failure does not disrupt
        assert res["amount"] == 100
        
        log_file = log_dir / "parity.jsonl"
        event = json.loads(log_file.read_text().splitlines()[0])
        assert event["match"] is False
        assert event["remote_status"] == "unavailable"

def test_mutating_operation_not_shadowed_unless_safe(temp_workspace):
    tmp_path, _, _, log_dir = temp_workspace
    cfg = BoundaryConfig(base_url="http://fake", shadow_mode=True, shadow_log_dir=str(log_dir))
    client = BoundaryClient(cfg)
    
    def fallback(err):
        return {"id": "123"}
        
    with mock.patch('requests.post') as mock_post:
        res = client.request_json("POST", "/api/v1/billing", fallback=fallback)
        # 12. Mutating op not shadow-executed
        mock_post.assert_not_called()
        assert not (log_dir / "parity.jsonl").exists()
        
        # Execute with shadow_safe_write
        mock_resp = mock.Mock()
        mock_resp.json.return_value = {"id": "123"}
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp
        
        res = client.request_json("POST", "/api/v1/billing", fallback=fallback, shadow_safe_write=True)
        mock_post.assert_called_once()
        assert (log_dir / "parity.jsonl").exists()

def generate_parity_logs(log_dir, count, match=True, method="GET", path="/api/v1/billing"):
    log_file = log_dir / "parity.jsonl"
    with log_file.open("a") as f:
        for _ in range(count):
            event = {"method": method, "path": path, "match": match, "mismatched_keys": [] if match else ["amount"]}
            f.write(json.dumps(event) + "\n")

def test_parity_harness_evaluations(temp_workspace):
    tmp_path, _, _, log_dir = temp_workspace
    report_path = log_dir / "report.json"
    harness_cmd = [sys.executable, "tools/parity_harness.py", "--log-file", str(log_dir / "parity.jsonl"), "--output", str(report_path)]
    
    # 8. Low sample count fails
    generate_parity_logs(log_dir, 10, match=True)
    res = subprocess.run(harness_cmd, capture_output=True)
    assert res.returncode != 0
    
    # 4. Parity harness passes when threshold met
    (log_dir / "parity.jsonl").unlink()
    generate_parity_logs(log_dir, 30, match=True)
    res = subprocess.run(harness_cmd, capture_output=True)
    assert res.returncode == 0
    
    # 5. Fails when threshold not met
    generate_parity_logs(log_dir, 2, match=False) # Total 32, 30 matches (93.7%) - below 95% for read_nonsensitive
    res = subprocess.run(harness_cmd, capture_output=True)
    assert res.returncode != 0
    
    # 6. Critical endpoint mismatch blocks
    (log_dir / "parity.jsonl").unlink()
    generate_parity_logs(log_dir, 30, match=True, path="/api/v1/auth") # Auth is critical (100%)
    generate_parity_logs(log_dir, 1, match=False, path="/api/v1/auth") # 1 mismatch should block
    res = subprocess.run(harness_cmd, capture_output=True)
    assert res.returncode != 0
    report = json.loads(report_path.read_text())
    assert report["endpoints"]["GET /api/v1/auth"]["criticality"] == "critical"

def run_promote(manifest_path, manifest_data):
    state = _load_state(manifest_path.with_suffix(".state.json"))
    manifest_path.write_text(json.dumps(manifest_data))
    return cmd_promote(manifest_path, manifest_data, state, "canary_10", True, ui_checklist="", ui_smoke_spec="", ui_browser_spec="", ui_checklist_fail_on_todo=False), state

def test_cutover_gate_passes_when_parity_passes(temp_workspace):
    tmp_path, manifest_path, manifest_data, log_dir = temp_workspace
    generate_parity_logs(log_dir, 30, match=True)
    
    # 9. Gate passes
    rc, state = run_promote(manifest_path, manifest_data)
    assert rc == 0
    
    # 11. Governance handoff includes parity summary
    handoff_file = manifest_path.parent / "billing_governance_handoff.json"
    handoff = json.loads(handoff_file.read_text())
    assert "parity_status" in handoff["service_surface"]
    assert handoff["service_surface"]["parity_status"]["status"] == "PASS"

def test_cutover_gate_halts_when_parity_fails(temp_workspace):
    tmp_path, manifest_path, manifest_data, log_dir = temp_workspace
    generate_parity_logs(log_dir, 30, match=True)
    generate_parity_logs(log_dir, 1, match=False, path="/api/v1/auth") # Critical mismatch
    
    # 10. Gate halts
    rc, state = run_promote(manifest_path, manifest_data)
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.promotion.halted_by_parity" in events

def test_missing_parity_log_blocks_promotion(temp_workspace):
    tmp_path, manifest_path, manifest_data, log_dir = temp_workspace
    # 7. Missing parity log blocks
    rc, state = run_promote(manifest_path, manifest_data)
    assert rc == 1
    events = [e["action"] for e in state.get("history", [])]
    assert "msf.promotion.halted_by_parity" in events
