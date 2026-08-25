# Modular Feature Services (MFS)

MFS is an app-agnostic framework for extracting large or risky features from a legacy application into isolated microservices and containers.

## What MFS Enables
- Reverse-engineer existing app features into service candidates.
- Move feature execution into dedicated containers while keeping UI and orchestration stable.
- Enforce versioned API contracts per extracted feature.
- Standardize health checks, readiness, and contract-drift audits.
- Reduce regression blast radius during legacy modernization.

## Framework Pattern
1. Keep the host app as the composition layer.
2. Extract feature execution into a dedicated service container.
3. Expose at least:
   - `GET /health`
   - one versioned contract endpoint (for example, `/v1/<feature>/capabilities`)
4. Route host app calls through one boundary adapter per feature.
5. Define expected payload shape in `contracts/*.json`.
6. Register service metadata in `registry/services.json`.
7. Validate with `python tools/service_health_audit.py`.

## Repository Layout
- `contracts/`: versioned response contracts.
- `registry/`: service registry and audit metadata.
- `services/`: containerized feature services.
- `templates/`: reusable scaffold templates.
- `tools/`: validation and operational tooling.
- `docs/`: framework reference and migration playbook.
- `examples/generic_boundary/`: generic boundary adapter example.

## Quick Start
1. Start the standalone stack:
```bash
docker compose up -d --build
```
2. Set service base URL env vars for your environment, for example:
```bash
MFS_EXAMPLE_BASE_URL=http://localhost:8610
```
3. Run the audit:
```bash
python tools/service_health_audit.py
```

## Provider Modes
For app-agnostic startup, services default to stub providers where needed:
- `MFS_<FEATURE>_PROVIDER=stub` (default — returns placeholder responses)
- `MFS_<FEATURE>_PROVIDER=legacy_app` (wires to host app modules for real feature logic)

## Scaffold a New Feature
Generate a new service + contract + registry entry:
```bash
python tools/scaffold_feature.py --feature sentiment-analysis --port 8670
```
The generator renders reusable files from `templates/scaffold/`.

This creates:
- `services/sentiment_analysis_service/app.py`
- `services/sentiment_analysis_service/Dockerfile`
- `services/sentiment_analysis_service/requirements.txt`
- `contracts/sentiment_analysis_v1.json`
- a new entry in `registry/services.json`

## Legacy Host Integration
If you need host-app-specific behavior, keep it in boundary adapters and optionally enable `legacy_app` provider mode per service.

## Boundary SDK + Templates
Reusable boundary SDK:
- `boundary_sdk/client.py`

Generate a boundary adapter template:
```bash
python tools/scaffold_boundary.py --feature sentiment-analysis --base-url http://localhost:8670
```

Guide:
- `docs/BOUNDARY_SDK.md`

## Agent SDK (External Agent Wiring)
Generate a typed Python SDK so external agents (LLMs, orchestrators) can consume an MFS-extracted service:
```bash
python tools/scaffold_agent_sdk.py --app-name "MyApp" --app-slug myapp --port 5000 --governance full --output ./myapp_sdk/
```

Three governance modes:
- `stateless` — no sessions, pure REST
- `session_only` — sessions with auto-create/refresh/retry
- `full` — CONCORD-style: sessions + trust + budgets + guards

From manifest (complex apps with many actions):
```bash
python tools/scaffold_agent_sdk.py --from-manifest agent_sdk_manifest.yaml --output ./myapp_sdk/
```

Guide:
- `docs/AGENT_SDK.md`
- `examples/agent_sdk_manifest_example.yaml`

## MCP Bridge (Agent → Service via MCP)
Generate a standalone MCP server + OpenAPI spec from any registered service:
```bash
python tools/scaffold_mcp.py --service example-service --output ./mcp_servers/example/
```

This enables the complementary chain:
- **MFS extracts + containerizes** → **scaffold_mcp.py wraps as MCP** → **Agent uses it**
- Generated MCP server works with Claude Desktop, Codex, or any MCP client
- Generated OpenAPI spec works with [EasyMCP](https://github.com/ab0t-com/easymcp) for additional agent toolchains

Generate for all registered services:
```bash
python tools/scaffold_mcp.py --all --output ./mcp_servers/
```

Guide:
- `docs/MCP_BRIDGE.md`

## Contract Lifecycle Tooling
Compare contract versions and check backward/forward compatibility:
```bash
python tools/contract_diff.py --old contracts/feature_v1.json --new contracts/feature_v2.json --mode both
```

## Migration Planning
Use `docs/MIGRATION_PLAYBOOK.md` for reverse-engineering candidate selection and phased cutover while preserving existing UI.

## Intake and Scoring
Use the intake template per legacy app:
- `tools/migration_intake.md`

Auto-discover candidates in a legacy repo:
```bash
python tools/discover_candidates.py --target <legacy-repo-path> --top 20
```
Focused discovery example (exclude non-product buckets):
```bash
python tools/discover_candidates.py --target <legacy-repo-path> --top 20 --exclude-buckets docs,tools,scripts,tests,infra
```
Default outputs:
- `<legacy-repo-path>/docs/_generated/candidate_scores.csv`
- `<legacy-repo-path>/docs/_generated/migration_report.md`
- `<legacy-repo-path>/docs/_generated/discovery_summary.json`

Merge runtime signals (latency, error, runtime change frequency):
```bash
python tools/merge_candidate_signals.py --candidates <legacy-repo-path>/docs/_generated/candidate_scores.csv --runtime tools/runtime_signals_template.csv
```

Auto-build runtime signals from telemetry sources:
```bash
python tools/ingest_runtime_signals.py --sources "<telemetry1.jsonl,metrics.csv,app.log>" --output <legacy-repo-path>/mfs_migration/runtime_signals.csv
```

Rank candidate features from CSV (merged or manual):
```bash
python tools/score_candidates.py --input candidate_scores.csv --top 10
```
Starter CSV template:
- `tools/candidate_scores_template.csv`
- `tools/runtime_signals_template.csv`

## Cutover Orchestration
Scaffold staged rollout manifest:
```bash
python tools/scaffold_cutover.py --feature sentiment-analysis
```

Plan/promote/rollback via orchestrator:
```bash
python tools/cutover_orchestrator.py plan --manifest docs/_generated/sentiment_analysis_cutover.json
python tools/cutover_orchestrator.py promote --manifest docs/_generated/sentiment_analysis_cutover.json --stage canary_5
python tools/cutover_orchestrator.py rollback --manifest docs/_generated/sentiment_analysis_cutover.json
```

Guide:
- `docs/CUTOVER_ORCHESTRATION.md`

## UI Parity Harness
Checklist runner:
```bash
python tools/ui_parity_checklist.py --checklist tools/ui_parity_checklist_template.json
```

HTTP smoke runner:
```bash
python tools/ui_smoke_runner.py --spec tools/ui_smoke_spec_template.json
```

Guide:
- `docs/UI_PARITY_HARNESS.md`

## Semantic UI Retrofit
The semantic UI workflow lets an existing application adopt stable MSF control identities and explicit UI states without coupling journeys to DOM selectors. The runtime probe can inspect rendered controls, observe browser events, match controls to an approved contract, and report missing or unknown identities:
```bash
python tools/semantic_retrofit.py --url file:///absolute/path/to/app/index.html --contract examples/semantic_ui_demo/demo_ui_contract.json --output retrofit_report.json
```

Before instrumentation, inventory common controls in HTML, JSX, TSX, and Vue source files. The report includes source locations, labels, DOM IDs, handler attributes, state evidence, inferred actions, and reviewable semantic ID proposals:
```bash
python tools/semantic_retrofit.py --source-dir <legacy-app>/src --contract examples/semantic_ui_demo/demo_ui_contract.json --output source_retrofit_report.json
```

Approved mappings can be rendered as a unified diff and applied explicitly. Approval files are keyed by the reported relative file and line:
```json
{
   "approvals": {
      "components/CustomerForm.tsx:12": {
         "semantic_id": "customer/form/save",
         "state": "enabled"
      }
   }
}
```
```bash
python tools/semantic_retrofit.py --source-dir <legacy-app>/src --contract examples/semantic_ui_demo/demo_ui_contract.json --approval approvals.json --patch retrofit.patch
python tools/semantic_retrofit.py --source-dir <legacy-app>/src --contract examples/semantic_ui_demo/demo_ui_contract.json --approval approvals.json --patch retrofit.patch --apply
```

The default is a dry run. Only approved `data-msf-id` and initial `data-msf-state` attributes are materialized. Framework-specific state-machine reconstruction, deeper handler analysis, and richer state-update instrumentation remain adapter work for React, Vue, and Angular.

Pre-promote UI gates (optional):
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/sentiment_analysis_cutover.json --stage canary_5 --ui-checklist tools/ui_parity_checklist_template.json --ui-smoke-spec tools/ui_smoke_spec_template.json
```

## CI/CD Migration Gates
Run migration gates locally:
```bash
python tools/ci_migration_gates.py --run-health-audit --run-container-build --services example-service --ui-checklist tools/ui_parity_checklist_template.json
```

Workflow:
- `.github/workflows/migration-gates.yml`
- `docs/CI_MIGRATION_GATES.md`

## Legacy Repo Onboarding
Bootstrap migration workspace in a legacy repo:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --features billing,search
```

Profile-based onboarding (recommended):
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --profile auto
```

Bootstrap and run discovery immediately:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --features billing,search --run-discovery --discovery-top 20
```

Guide:
- `docs/ONBOARDING_COMMAND.md`

## Migration Pack Builder
Build a single AI-ready pack from generated onboarding/discovery artifacts:
```bash
python tools/build_migration_pack.py --workspace <legacy-repo-path>/mfs_migration --top 10 --include-file-snippets
```

Outputs:
- `<workspace>/pack/migration_pack.json`
- `<workspace>/pack/migration_pack.md`

Browser-level parity checks (Playwright):
```bash
python tools/ui_browser_runner.py --spec tools/ui_browser_spec_template.json
```

Advanced contract semantics check (enum/default compatibility):
```bash
python tools/contract_diff.py --old contracts/feature_v1.json --new contracts/feature_v2.json --mode both
```
