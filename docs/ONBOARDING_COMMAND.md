# Onboarding Command Guide

## Purpose
`mfs_onboard.py` bootstraps a migration workspace inside a legacy app repository.

## Command
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --features billing,search,recommendations
```

Profile-first command (recommended):
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --profile planning_pack
```

Run onboarding + immediate discovery:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --features billing,search,recommendations --run-discovery --discovery-top 20
```

## Generated Workspace
Default path in target repo:
- `mfs_migration/`

Includes:
- `migration_intake.md`
- `candidate_scores.csv`
- `runtime_signals.csv`
- `ui_parity_checklist.json`
- `ui_smoke_spec.json`
- `migration_plan.md`
- `boundaries/*.py`
- `AI_DEV_START.md`
- `context_manifest.json`
- `run_mfs_sequence.ps1`
- `discovery/*` (when `--run-discovery` is used)

## Notes
- Use `--workspace` to change output folder name.
- Use `--force` to overwrite existing generated files.
- Available profiles: `auto`, `discovery_only`, `planning_pack`, `cutover_ready`, `ci_strict`.
- `auto` infers the best profile from repo signals (size, route density, test density, stack indicators).
