from pathlib import Path

from tools.semantic_retrofit import (
    apply_instrumentation_plan,
    build_instrumentation_plan,
    discover_runtime,
    discover_source,
    propose_id,
)
from tools.semantic_ui_coverage import validate_coverage
from tools.semantic_ui_validator import load_json


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "semantic_ui_demo"
CONTRACT = load_json(DEMO / "demo_ui_contract.json")
URL = (DEMO / "webapp" / "index.html").resolve().as_uri()


def test_runtime_discovery_matches_contract_and_reports_rendered_state():
    report = discover_runtime(URL, CONTRACT)
    assert report["schema_version"] == "msf.semantic_retrofit_report.v1"
    assert report["review_required"] is False
    assert validate_coverage(report, CONTRACT) == []
    save = next(item for item in report["candidates"] if item["semantic_id"] == "customer/form/save")
    assert save["control_type"] == "button"
    assert save["runtime"] == {"state": "enabled", "visible": True, "enabled": True, "options": []}


def test_runtime_discovery_observes_real_semantic_events_and_states():
    report = discover_runtime(
        URL,
        CONTRACT,
        lambda page: (
            page.locator('[data-msf-id="customer/form/name"]').fill("Jane Smith"),
            page.locator('[data-msf-id="customer/form/type"]').select_option("business"),
            page.locator('[data-msf-id="customer/form/notifications"]').check(),
            page.locator('[data-msf-id="customer/form/save"]').click(),
            page.wait_for_timeout(600),
        ),
    )
    assert [event["action"] for event in report["observed_events"]] == ["set", "select", "toggle", "click"]
    assert report["observed_events"][0]["value"] == "[REDACTED]"
    assert report["observed_events"][-1]["state"] == "enabled"
    status = next(item for item in report["candidates"] if item["semantic_id"] == "customer/form/status")
    assert status["runtime"]["state"] == "saved"


def test_missing_identity_gets_reviewable_proposal_and_diagnostic():
    report = discover_runtime(
        URL,
        CONTRACT,
        lambda page: (
            page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button id=plain>Save invoice</button>')"),
            page.locator("#plain").click(),
        ),
    )
    candidate = next(item for item in report["candidates"] if item["semantic_id"] is None and item["label"] == "Save invoice")
    assert candidate["approval"] == "required"
    assert candidate["proposed_semantic_id"] == "review/save-invoice"
    assert report["observed_events"][-1]["diagnostic"] == "missing_semantic_id"


def test_unknown_identity_and_invalid_state_are_coverage_failures():
    report = discover_runtime(
        URL,
        CONTRACT,
        lambda page: (
            page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button data-msf-id=invoice/search/submit>Search</button>')"),
            page.locator('[data-msf-id="invoice/search/submit"]').click(),
        ),
    )
    errors = validate_coverage(report, CONTRACT)
    assert "uncontracted_rendered_control: invoice/search/submit" in errors

    changed = dict(CONTRACT)
    changed["controls"] = dict(CONTRACT["controls"])
    changed["controls"]["customer/form/status"] = dict(CONTRACT["controls"]["customer/form/status"])
    changed["controls"]["customer/form/status"]["states"] = ["ready"]
    invalid = discover_runtime(
        URL,
        changed,
        lambda page: page.locator('[data-msf-id="customer/form/status"]').evaluate("element => element.dataset.msfState = 'bogus'"),
    )
    assert "invalid_runtime_state: customer/form/status='bogus'" in validate_coverage(invalid, changed)


def test_id_proposals_are_deterministic_and_domain_reviewable():
    assert propose_id("Submit invoice", "invoice/search") == "invoice/search/submit-invoice"
    assert propose_id("", "invoice") == "invoice"


def test_source_discovery_reports_evidence_and_reviewable_proposals(tmp_path):
    source = tmp_path / "CustomerForm.tsx"
    source.write_text(
        '<button id="saveCustomerBtn" onClick="saveCustomer">Save customer</button>\n'
        '<input name="customerName" aria-label="Customer name" />\n',
        encoding="utf-8",
    )

    report = discover_source(tmp_path, CONTRACT)

    assert report["schema_version"] == "msf.semantic_source_report.v1"
    save = report["candidates"][0]
    assert save["source"] == {"file": "CustomerForm.tsx", "line": 1}
    assert save["label"] == "Save customer"
    assert save["evidence"]["handler_hints"] == ["onclick"]
    name = report["candidates"][1]
    assert name["proposed_semantic_id"] == "review/customer-name"
    assert name["approval"] == "required"
    assert report["review_required"] is True


def test_approved_instrumentation_is_dry_run_then_applyable(tmp_path):
    source = tmp_path / "form.html"
    source.write_text('<button id="save">Save customer</button>\n', encoding="utf-8")
    report = discover_source(tmp_path, CONTRACT)
    approvals = {"form.html:1": {"semantic_id": "customer/form/save", "state": "enabled"}}

    plan = build_instrumentation_plan(report, approvals)
    assert plan["schema_version"] == "msf.semantic_instrumentation_plan.v1"
    diff = apply_instrumentation_plan(tmp_path, plan)
    assert 'data-msf-id="customer/form/save"' in diff
    assert 'data-msf-state="enabled"' in diff
    assert 'data-msf-id' not in source.read_text(encoding="utf-8")

    apply_instrumentation_plan(tmp_path, plan, dry_run=False)
    instrumented = source.read_text(encoding="utf-8")
    assert 'data-msf-id="customer/form/save"' in instrumented
    assert 'data-msf-state="enabled"' in instrumented