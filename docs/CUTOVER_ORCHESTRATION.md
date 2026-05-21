# Cutover Orchestration Guide

## Purpose
Cutover tooling provides a repeatable command path for staged rollout and rollback.

## Files
- `templates/cutover/cutover_manifest.json.tmpl`
- `tools/scaffold_cutover.py`
- `tools/cutover_orchestrator.py`

## 1) Scaffold a Manifest
```bash
python tools/scaffold_cutover.py --feature sentiment-analysis
```

Default output:
- `docs/_generated/sentiment_analysis_cutover.json`

## 2) Review Plan
```bash
python tools/cutover_orchestrator.py plan --manifest docs/_generated/sentiment_analysis_cutover.json
```

## 3) Optional Pre-Promote Gates
You can define gates in the manifest `gates` block:
- `ui_parity_checklist`
- `ui_smoke_spec`
- `ui_browser_spec`
- `ui_checklist_fail_on_todo`

Or pass gate paths via CLI:
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/sentiment_analysis_cutover.json --stage canary_5 --ui-checklist tools/ui_parity_checklist_template.json --ui-smoke-spec tools/ui_smoke_spec_template.json
```

Browser gate via CLI:
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/sentiment_analysis_cutover.json --stage canary_5 --ui-browser-spec tools/ui_browser_spec_template.json
```

## 4) Promote a Stage (Dry-Run)
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/sentiment_analysis_cutover.json --stage canary_5
```

## 5) Promote a Stage (Execute)
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/sentiment_analysis_cutover.json --stage canary_5 --execute
```

## 6) Check Status
```bash
python tools/cutover_orchestrator.py status --manifest docs/_generated/sentiment_analysis_cutover.json
```

## 7) Rollback
```bash
python tools/cutover_orchestrator.py rollback --manifest docs/_generated/sentiment_analysis_cutover.json
```

Use `--execute` to run rollback commands; without it, command is dry-run.

## Environment Integrations
Manifest `integrations` block supports optional provider adapters and HTTP hooks:
- `flag_provider` (native adapters: `local_env_flag`, `argo_rollouts`)
- `deploy_provider` (native adapters: `docker_compose`, `argo_rollouts`)
- `slo_policy` (policy-based auto-halt from live metrics)

HTTP hooks:
- `flag_hook`
- `deploy_hook`
- `health_check`
- `rollback_hook`

Behavior:
- Hooks run in dry-run unless `--execute` is set.
- Failed `flag_hook` or `deploy_hook` blocks promotion.
- `health_check` runs after deploy/verify and can fail promotion.
- `rollback_hook` runs before rollback command path.
- `slo_policy` runs after deploy/verify and blocks promotion if thresholds are breached.

## Notes
- Manifest commands are placeholders by default; replace with real deployment and verification commands.
- State is stored in `<manifest>.state.json` unless `--state` is provided.
- Pre-promote gates run before deploy/verify in `promote`; a failing gate blocks promotion.
