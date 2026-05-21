import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

def test_risk_profiling_and_policy_preview():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # Create non-sensitive service
        ns_dir = tmp_path / "nonsensitive_service"
        ns_dir.mkdir()
        (ns_dir / "app.py").write_text("def get_info(): return 'hello'")
        
        ns_contract_path = tmp_path / "ns_contract.json"
        ns_contract_path.write_text(json.dumps({
            "endpoints": {
                "GET": {"/api/info": {}}
            }
        }))
        
        ns_output = tmp_path / "ns_protected_resources.json"
        
        subprocess.run([
            sys.executable, "tools/assess_candidate_risk.py",
            "--source-dir", str(ns_dir),
            "--contract", str(ns_contract_path),
            "--output", str(ns_output)
        ], check=True)
        
        ns_manifest = json.loads(ns_output.read_text())
        assert ns_manifest["risk_profile"]["data_sensitivity"] == "low"
        assert ns_manifest["risk_profile"]["governance_risk"] == "standard"
        assert len(ns_manifest["risk_profile"]["sensitive_domains"]) == 0
        assert ns_manifest["endpoints"]["GET /api/info"]["risk_level"] == "low"
        
        ns_policy_output = tmp_path / "ns_policy.yaml"
        subprocess.run([
            sys.executable, "tools/preview_forgeroot_policy.py",
            "--feature", "nonsensitive",
            "--manifest", str(ns_output),
            "--output", str(ns_policy_output)
        ], check=True)
        ns_yaml = ns_policy_output.read_text()
        assert "dataSensitivity: low" in ns_yaml
        assert "governanceRisk: standard" in ns_yaml
        assert "requires: authentication" not in ns_yaml

        # Create sensitive service
        s_dir = tmp_path / "sensitive_service"
        s_dir.mkdir()
        (s_dir / "app.py").write_text("def checkout(): charge_credit_card()\ndef profile(): get_user()")
        
        s_contract_path = tmp_path / "s_contract.json"
        s_contract_path.write_text(json.dumps({
            "endpoints": {
                "POST": {"/api/payment": {}},
                "GET": {"/api/user/profile": {}}
            }
        }))
        
        s_output = tmp_path / "s_protected_resources.json"
        
        subprocess.run([
            sys.executable, "tools/assess_candidate_risk.py",
            "--source-dir", str(s_dir),
            "--contract", str(s_contract_path),
            "--output", str(s_output)
        ], check=True)
        
        s_manifest = json.loads(s_output.read_text())
        assert s_manifest["risk_profile"]["data_sensitivity"] == "high"
        assert s_manifest["risk_profile"]["governance_risk"] == "requires_policy"
        assert "payments" in s_manifest["risk_profile"]["sensitive_domains"]
        assert "identity" in s_manifest["risk_profile"]["sensitive_domains"]
        
        assert s_manifest["endpoints"]["POST /api/payment"]["risk_level"] == "critical"
        assert "payments" in s_manifest["endpoints"]["POST /api/payment"]["domains"]
        assert s_manifest["endpoints"]["GET /api/user/profile"]["risk_level"] == "high"
        
        s_policy_output = tmp_path / "s_policy.yaml"
        subprocess.run([
            sys.executable, "tools/preview_forgeroot_policy.py",
            "--feature", "sensitive",
            "--manifest", str(s_output),
            "--output", str(s_policy_output)
        ], check=True)
        s_yaml = s_policy_output.read_text()
        assert "dataSensitivity: high" in s_yaml
        assert "governanceRisk: requires_policy" in s_yaml
        assert "- payments" in s_yaml
        assert "endpoint: \"POST /api/payment\"" in s_yaml
        assert "riskLevel: critical" in s_yaml
        assert "- strict_authorization" in s_yaml
