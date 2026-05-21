# CI Migration Gates Guide

## Purpose
CI migration gates enforce migration quality before merge.

## Tool
- `tools/ci_migration_gates.py`

## Pipeline Coverage
- Contract sanity checks (`contracts/*.json`)
- Service health audit (`tools/service_health_audit.py`)
- Container build gate (`docker compose build`)
- Optional container scan gate (Trivy)
- Optional UI parity and smoke gates

## Local Run Example
```bash
python tools/ci_migration_gates.py --run-health-audit --run-container-build --services example-service --ui-checklist tools/ui_parity_checklist_template.json
```

## GitHub Workflow
- `.github/workflows/migration-gates.yml`

This workflow builds service images, starts services, then runs `ci_migration_gates.py`.
