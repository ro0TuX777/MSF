# UI Parity Harness Guide

## Purpose
UI parity harness protects legacy UX during feature migration by combining:
- structured manual parity checklist (`ui_parity_checklist.py`)
- automated HTTP smoke assertions (`ui_smoke_runner.py`)

## Files
- `tools/ui_parity_checklist.py`
- `tools/ui_smoke_runner.py`
- `tools/ui_browser_runner.py`
- `tools/ui_parity_checklist_template.json`
- `tools/ui_smoke_spec_template.json`
- `tools/ui_browser_spec_template.json`

## Semantic UI Reference Application

The framework contract can also be exercised independently of an application framework with the self-contained fixture in `examples/semantic_ui_demo/`. It defines semantic IDs and explicit states, validates journeys before launch, and executes them in Chromium:

```bash
python tools/semantic_ui_validator.py --contract examples/semantic_ui_demo/demo_ui_contract.json --journey examples/semantic_ui_demo/journeys/happy_path.json
python tools/reference_browser_executor.py --contract examples/semantic_ui_demo/demo_ui_contract.json --journey examples/semantic_ui_demo/journeys/happy_path.json --url file:///absolute/path/to/MFS/examples/semantic_ui_demo/webapp/index.html
```

The focused integration suite covers async save, validation failure, disclosure toggling, semantic JSONL events, and intentional `data-msf-id` drift:

```bash
python -m pytest tests/test_semantic_ui_poc.py -q
```

## MSF Retrofit Discovery

For existing applications, `tools/semantic_retrofit.py` is the MSF-specific discovery layer. It inspects rendered controls, current semantic state, and real browser events, then reports contract matches, missing identities, unknown targets, and reviewable domain-ID proposals. `tools/semantic_ui_coverage.py` validates the live rendered surface against the approved MSF UI contract. These reports are advisory and do not replace the canonical contract or journey validators.

## 1) Run Checklist Evaluation
```bash
python tools/ui_parity_checklist.py --checklist tools/ui_parity_checklist_template.json
```

Optional strict mode:
```bash
python tools/ui_parity_checklist.py --checklist tools/ui_parity_checklist_template.json --fail-on-todo
```

## 2) Run UI Smoke Assertions
```bash
python tools/ui_smoke_runner.py --spec tools/ui_smoke_spec_template.json
```

## 3) Run Browser-Level Journey Checks (Playwright)
```bash
python tools/ui_browser_runner.py --spec tools/ui_browser_spec_template.json
```

Prerequisites:
- `pip install playwright`
- `playwright install`

## 3) Persist Results
```bash
python tools/ui_parity_checklist.py --checklist tools/ui_parity_checklist_template.json --output-json docs/_generated/ui_parity_checklist_result.json
python tools/ui_smoke_runner.py --spec tools/ui_smoke_spec_template.json --output-json docs/_generated/ui_smoke_result.json
python tools/ui_browser_runner.py --spec tools/ui_browser_spec_template.json --output-json docs/_generated/ui_browser_result.json
```

## Recommended Cutover Gate
Before each promote stage:
1. Checklist overall = PASS (or only approved TODOs).
2. Smoke overall = PASS.
3. Browser journey checks overall = PASS for critical routes.
4. If any required gate fails, stop promotion and run rollback path.
