import json
import shutil
from pathlib import Path
import pytest

from tools.journey_event_validator import validate_events
from tools.journey_composer import JourneyComposer
from tools.reference_browser_executor import execute
from tools.semantic_ui_validator import load_json, validate

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "semantic_ui_demo"
CONTRACT_PATH = DEMO / "demo_ui_contract.json"
WEBAPP = DEMO / "webapp" / "index.html"


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def compose_demo_journeys(composer):
    journeys = []
    steps = []
    composer.add_step(steps, "set", "customer/form/name", value="Jane Smith")
    composer.add_step(steps, "select", "customer/form/type", value="business")
    composer.add_step(steps, "toggle", "customer/form/notifications")
    composer.add_step(steps, "click", "customer/form/save")
    composer.add_step(steps, "wait", "customer/form/status", state="saved", timeout_ms=3000)
    composer.add_step(steps, "expect", "customer/form/status", state="saved")
    journeys.append(composer.compose("composed-save-customer", steps))

    steps = []
    composer.add_step(steps, "click", "customer/form/save")
    composer.add_step(steps, "expect", "customer/form/validation/name", state="error")
    journeys.append(composer.compose("composed-validation-failure", steps))

    steps = []
    composer.add_step(steps, "expect", "customer/form/details", state="expanded")
    composer.add_step(steps, "toggle", "customer/form/details")
    composer.add_step(steps, "expect", "customer/form/details", state="collapsed")
    composer.add_step(steps, "click", "customer/navigation/notes")
    composer.add_step(steps, "expect", "customer/navigation/notes", state="active")
    journeys.append(composer.compose("composed-interaction-state", steps))
    return journeys


def test_composer_discovers_contract_and_generates_three_canonical_journeys():
    composer = JourneyComposer.from_path(CONTRACT_PATH)
    assert "customer/form/save" in composer.targets()
    assert composer.actions_for("customer/form/save") == ["click"]
    assert composer.states_for("customer/form/status", "expect") == ["ready", "saving", "saved", "error"]
    for journey in compose_demo_journeys(composer):
        assert validate(load_json(CONTRACT_PATH), journey) == []


def test_composed_journeys_pass_validation_execution_and_event_validation():
    contract = load_json(CONTRACT_PATH)
    composer = JourneyComposer(contract)
    for index, journey in enumerate(compose_demo_journeys(composer)):
        assert validate(contract, journey) == []
        output = ROOT / "tests" / f".semantic-events-{index}.jsonl"
        try:
            events = execute(journey, contract, file_url(WEBAPP), output=output)
            persisted = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        finally:
            output.unlink(missing_ok=True)
        assert all(event["result"] == "passed" for event in events)
        assert validate_events(events) == []
        assert persisted == events


def test_composer_prevents_invalid_operation_and_validator_rejects_manual_artifact():
    contract = load_json(CONTRACT_PATH)
    composer = JourneyComposer(contract)
    with pytest.raises(ValueError, match="not permitted"):
        composer.add_step([], "set", "customer/form/save", value="invalid")

    manually_invalid = {
        "journey_id": "manual-invalid",
        "steps": [{"action": "set", "target": "customer/form/save", "value": "invalid"}],
    }
    assert any("action_not_allowed" in error for error in validate(contract, manually_invalid))


def test_composer_changes_with_contract_action_removal():
    contract = load_json(CONTRACT_PATH)
    composer = JourneyComposer(contract)
    contract["controls"]["customer/form/save"]["actions"].remove("click")
    changed_composer = JourneyComposer(contract)
    assert "click" not in changed_composer.actions_for("customer/form/save")
    with pytest.raises(ValueError, match="not permitted"):
        changed_composer.add_step([], "click", "customer/form/save")


def test_semantic_journeys_validate():
    contract = load_json(CONTRACT_PATH)
    for journey_path in sorted((DEMO / "journeys").glob("*.json")):
        assert validate(contract, load_json(journey_path)) == []


def test_reference_executor_runs_journeys_and_emits_events(tmp_path):
    contract = load_json(CONTRACT_PATH)
    for journey_path in sorted((DEMO / "journeys").glob("*.json")):
        journey = load_json(journey_path)
        events = execute(journey, contract, file_url(WEBAPP))
        assert len(events) == len(journey["steps"])
        assert all(event["result"] == "passed" for event in events)
        assert validate_events(events) == []
        assert len({event["session_id"] for event in events}) == 1
        assert len({event["run_id"] for event in events}) == 1
        if any("value" in step for step in journey["steps"]):
            assert any(event["requested"].get("value") == "[REDACTED]" for event in events)


def test_reference_executor_detects_contract_drift(tmp_path):
    drifted_page = tmp_path / "index.html"
    shutil.copy2(WEBAPP, drifted_page)
    drifted_page.write_text(
        drifted_page.read_text(encoding="utf-8").replace(
            'data-msf-id="customer/form/save"',
            'data-msf-id="customer/form/save-button"',
        ),
        encoding="utf-8",
    )

    contract = load_json(CONTRACT_PATH)
    journey = load_json(DEMO / "journeys" / "happy_path.json")
    events = execute(journey, contract, file_url(drifted_page))

    assert events[-1]["result"] == "failed"
    assert "target_not_found" in events[-1]["error"]
    assert events[-1]["resolved"]["msf_id"] == "customer/form/save"


def test_invalid_action_is_rejected_before_browser_launch():
    contract = load_json(CONTRACT_PATH)
    journey = load_json(DEMO / "journeys" / "happy_path.json")
    journey["steps"][0]["action"] = "unsupported"
    with pytest.raises(ValueError, match="Journey rejected by contract"):
        execute(journey, contract, file_url(WEBAPP))


def test_invalid_state_is_rejected_by_contract():
    contract = load_json(CONTRACT_PATH)
    journey = load_json(DEMO / "journeys" / "happy_path.json")
    journey["steps"][-1]["state"] = "bogus"
    with pytest.raises(ValueError, match="state_not_declared"):
        execute(journey, contract, file_url(WEBAPP))


def test_save_failure_is_reported_when_saved_state_never_arrives(tmp_path):
    demo_copy = tmp_path / "demo"
    shutil.copytree(DEMO / "webapp", demo_copy / "webapp")
    broken_page = demo_copy / "webapp" / "index.html"
    broken_app = demo_copy / "webapp" / "app.js"
    broken_app.write_text(
        broken_app.read_text(encoding="utf-8").replace("setState(status, 'saved');", "setState(status, 'error');"),
        encoding="utf-8",
    )
    contract = load_json(CONTRACT_PATH)
    journey = load_json(DEMO / "journeys" / "happy_path.json")
    events = execute(journey, contract, file_url(broken_page))
    assert events[-1]["result"] == "failed"
    assert "unexpected_state" in events[-1]["error"]


def test_repeated_runs_have_distinct_correlation_ids():
    contract = load_json(CONTRACT_PATH)
    journey = load_json(DEMO / "journeys" / "toggle_behavior.json")
    first = execute(journey, contract, file_url(WEBAPP))
    second = execute(journey, contract, file_url(WEBAPP))
    assert first[0]["session_id"] != second[0]["session_id"]
    assert first[0]["run_id"] != second[0]["run_id"]
