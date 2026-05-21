import os
from pathlib import Path
import pytest

DOCS_DIR = Path("docs")

def test_docs_exist():
    required_docs = [
        "operator_runbook.md",
        "sample_modernization_walkthrough.md",
        "ci_gate_matrix.md",
        "artifact_schema_reference.md",
        "failure_mode_guide.md",
        "pilot_readiness_checklist.md",
        "known_limitations.md",
        "example_migration_pack_structure.md"
    ]
    
    for doc in required_docs:
        assert (DOCS_DIR / doc).exists(), f"Missing required document: {doc}"

def test_operator_runbook_headings():
    content = (DOCS_DIR / "operator_runbook.md").read_text()
    assert "Candidate Discovery" in content
    assert "Closeout" in content
    # Look for mermaid diagram
    assert "```mermaid" in content

def test_sample_walkthrough_contents():
    content = (DOCS_DIR / "sample_modernization_walkthrough.md").read_text()
    # At least one concrete feature example
    assert "payments_cutover.json" in content or "payments_protected_resources.json" in content
    assert "parity_harness.py" in content
    assert "REQUIRE_APPROVAL" in content

def test_ci_gate_matrix_contents():
    content = (DOCS_DIR / "ci_gate_matrix.md").read_text()
    assert "parity_harness.py" in content
    assert "cutover_orchestrator.py" in content
    assert "halt" in content.lower() or "fail" in content.lower()

def test_artifact_schema_reference_contents():
    content = (DOCS_DIR / "artifact_schema_reference.md").read_text()
    assert "_governance_handoff.json" in content
    assert "_protected_resources.json" in content
    assert "msf.approval_packet.promote" in content
    assert "closeout_summary.json" in content
    assert "_forgeroot_policy_preview.yaml" in content

def test_failure_mode_guide_contents():
    content = (DOCS_DIR / "failure_mode_guide.md").read_text()
    assert "Symptom" in content
    assert "Likely Cause" in content
    assert "Inspection Point" in content
    assert "Expected State Event" in content
    assert "Operator Action" in content
    assert "Retry Safety" in content
    assert "Escalation" in content

def test_pilot_readiness_checklist_contents():
    content = (DOCS_DIR / "pilot_readiness_checklist.md").read_text()
    assert "Pilot Go/No-Go Decision" in content
    assert "Approver:" in content
    
def test_known_limitations_contents():
    content = (DOCS_DIR / "known_limitations.md").read_text()
    assert "Heuristic" in content
    assert "Shadow Parity" in content
    assert "Rollback" in content
    assert "Mock Governance" in content or "Adapter" in content
