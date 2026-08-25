import json
from pathlib import Path

import pytest

from tools.journey_composer import JourneyComposer
from tools.journey_event_validator import validate_events
from tools.reference_browser_executor import execute
from tools.semantic_interaction_capture import capture_workflow
from tools.semantic_ui_validator import load_json, validate

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "semantic_ui_demo"
CONTRACT = load_json(DEMO / "demo_ui_contract.json")
URL = (DEMO / "webapp" / "index.html").resolve().as_uri()


def capture(journey_id, interaction, debug=True):
    return capture_workflow(URL, CONTRACT, interaction, journey_id, debug=debug)


def test_captured_happy_path_is_enriched_and_replayed(tmp_path):
    journey, diagnostics = capture(
        "captured-happy-path",
        lambda page: (
            page.locator('[data-msf-id="customer/form/name"]').fill("Jane Smith"),
            page.locator('[data-msf-id="customer/form/type"]').select_option("business"),
            page.locator('[data-msf-id="customer/form/notifications"]').check(),
            page.locator('[data-msf-id="customer/form/save"]').click(),
        ),
    )
    assert diagnostics == []
    assert journey["steps"] == [
        {"action": "set", "target": "customer/form/name", "value": "${runtime:customer/form/name}"},
        {"action": "select", "target": "customer/form/type", "value": "business"},
        {"action": "toggle", "target": "customer/form/notifications", "value": "checked"},
        {"action": "click", "target": "customer/form/save"},
    ]
    composer = JourneyComposer(CONTRACT)
    composer.add_step(journey["steps"], "wait", "customer/form/status", state="saved", timeout_ms=3000)
    composer.add_step(journey["steps"], "expect", "customer/form/status", state="saved")
    assert validate(CONTRACT, journey) == []
    events = execute(journey, CONTRACT, URL, runtime_values={"customer/form/name": "Jane Smith"})
    assert all(event["result"] == "passed" for event in events)
    assert validate_events(events) == []


def test_captured_validation_failure_is_enriched_and_replayed():
    journey, diagnostics = capture(
        "captured-validation-failure",
        lambda page: page.locator('[data-msf-id="customer/form/save"]').click(),
    )
    assert diagnostics == []
    composer = JourneyComposer(CONTRACT)
    composer.add_step(journey["steps"], "expect", "customer/form/validation/name", state="error")
    assert validate(CONTRACT, journey) == []
    events = execute(journey, CONTRACT, URL)
    assert all(event["result"] == "passed" for event in events)
    assert validate_events(events) == []


def test_captured_interaction_state_path_replays():
    journey, diagnostics = capture(
        "captured-interaction-state",
        lambda page: (
            page.locator('[data-msf-id="customer/form/notifications"]').check(),
            page.locator('[data-msf-id="customer/form/details"]').click(),
            page.locator('[data-msf-id="customer/navigation/notes"]').click(),
        ),
    )
    assert diagnostics == []
    composer = JourneyComposer(CONTRACT)
    composer.add_step(journey["steps"], "expect", "customer/form/notifications", state="checked")
    composer.add_step(journey["steps"], "expect", "customer/form/details", state="collapsed")
    composer.add_step(journey["steps"], "expect", "customer/navigation/notes", state="active")
    assert validate(CONTRACT, journey) == []
    events = execute(journey, CONTRACT, URL)
    assert all(event["result"] == "passed" for event in events)
    assert validate_events(events) == []


def test_capture_ignores_missing_id_and_diagnoses_unknown_target():
    missing, missing_diagnostics = capture(
        "captured-missing-id",
        lambda page: page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button id=plain>Plain</button>'); document.querySelector('#plain').click()"),
    )
    assert missing["steps"] == []
    assert missing_diagnostics == [{"type": "missing_semantic_id", "event": "click"}]

    unknown, diagnostics = capture(
        "captured-unknown-id",
        lambda page: (
            page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button data-msf-id=unknown/action>Unknown</button>')"),
            page.locator('[data-msf-id="unknown/action"]').click(),
        ),
    )
    assert unknown["steps"] == [{"action": "click", "target": "unknown/action"}]
    assert diagnostics == [{"type": "unknown_contract_target", "target": "unknown/action"}]
    assert any("target_not_in_contract" in error for error in validate(CONTRACT, unknown))


def test_capture_normalizes_input_and_redacts_sensitive_value():
    journey, diagnostics = capture(
        "captured-normalized-input",
        lambda page: page.evaluate("""
            const input = document.querySelector('[data-msf-id="customer/form/name"]');
            for (const value of ['J', 'Ja', 'Jan', 'Jane']) {
              input.value = value;
              input.dispatchEvent(new Event('input', {bubbles: true}));
            }
        """),
    )
    assert diagnostics == []
    assert journey["steps"] == [{"action": "set", "target": "customer/form/name", "value": "${runtime:customer/form/name}"}]
    assert "Jane" not in json.dumps(journey)


def test_capture_sessions_have_distinct_identity_and_canonical_output(tmp_path):
    first, _ = capture("capture-one", lambda page: page.locator('[data-msf-id="customer/navigation/notes"]').click(), debug=True)
    second, _ = capture("capture-two", lambda page: page.locator('[data-msf-id="customer/navigation/notes"]').click(), debug=True)
    assert first["origin"] == second["origin"] == "captured"
    assert first["capture_session_id"] != second["capture_session_id"]
    assert validate(CONTRACT, first) == []
    assert validate(CONTRACT, second) == []
