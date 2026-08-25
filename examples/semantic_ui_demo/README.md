# MSF Semantic UI Demo

This fixture demonstrates an application adopting the MSF Semantic UI Contract without a framework or backend.

## Run static validation

```bash
python tools/semantic_ui_validator.py --contract examples/semantic_ui_demo/demo_ui_contract.json --journey examples/semantic_ui_demo/journeys/happy_path.json
```

## Run a journey in Chromium

The page is self-contained, so a local server is not required:

```bash
python tools/reference_browser_executor.py --contract examples/semantic_ui_demo/demo_ui_contract.json --journey examples/semantic_ui_demo/journeys/happy_path.json --url file:///absolute/path/to/MSF/examples/semantic_ui_demo/webapp/index.html --output-jsonl semantic_events.jsonl
```

The contract is `msf.semantic_ui_contract.v1`; events are `msf.semantic_event.v1`. The executor supports `set`, `clear`, `focus`, `select`, `toggle`, `click`, `wait`, and `expect`. It resolves only `data-msf-id` values and observes explicit `data-msf-state` values. Native control properties remain owned by the browser. Event values for controls marked `sensitive` are redacted.

Run the complete integration check with:

```bash
python -m pytest tests/test_semantic_ui_poc.py -q
```

The drift test changes only the save button's semantic ID and verifies that the unchanged journey fails with `target_not_found`.

## Capture Interactions

Phase B capture is an input adapter over the existing page. It observes meaningful `input`, `change`, and control `click` events, resolves the nearest `data-msf-id`, and emits the same `{journey_id, steps}` journey artifact used by the composer. Consecutive text inputs normalize to one final `set`; select duplicates are removed; assertions are never inferred. Sensitive values become `${runtime:customer/form/name}` placeholders and must be supplied only at replay time.

For an interactive session:

```bash
python tools/semantic_interaction_capture.py --url file:///absolute/path/to/MSF/examples/semantic_ui_demo/webapp/index.html --contract examples/semantic_ui_demo/demo_ui_contract.json --journey-id captured-customer-workflow --output captured_journey.json --headed
```

Then enrich the captured artifact with `JourneyComposer` waits or expectations and run the existing validator, reference executor, and event validator. Capture diagnostics report missing semantic IDs and targets absent from the current contract without introducing selectors into the journey.

## Retrofit Discovery and Coverage

The MSF-specific retrofit probe inspects the rendered application and produces a review report. It identifies meaningful controls, reads current `data-msf-state`, observes semantic browser events, matches IDs to the approved contract, and proposes IDs only for developer review:

```bash
python tools/semantic_retrofit.py --url file:///absolute/path/to/MSF/examples/semantic_ui_demo/webapp/index.html --contract examples/semantic_ui_demo/demo_ui_contract.json --output retrofit_report.json
python tools/semantic_ui_coverage.py --url file:///absolute/path/to/MSF/examples/semantic_ui_demo/webapp/index.html --contract examples/semantic_ui_demo/demo_ui_contract.json
```

The coverage check fails when an approved contract control is not rendered, a rendered semantic ID is uncontracted, or a rendered semantic state is not declared. ID and state proposals are advisory; approval remains a developer decision and does not modify application code.

## Compose Journeys

The contract-driven composer is a usability layer over the existing canonical journey object. It has no selectors or browser knowledge:

```bash
python tools/journey_composer.py --contract examples/semantic_ui_demo/demo_ui_contract.json --journey-id composed-save-customer --step '{"action":"set","target":"customer/form/name","value":"Jane Smith"}' --step '{"action":"click","target":"customer/form/save"}' --output composed_journey.json
```

Use `--list-targets` to inspect each contract target with its permitted actions and valid states. The composer rejects invalid combinations, while `tools/semantic_ui_validator.py` remains authoritative for manually authored artifacts. Generated journeys use the same canonical JSON shape as the checked-in journeys and pass through the existing reference executor and event validator.
