# MFS Migration Playbook

## Goal
Use MFS to reverse-engineer an existing legacy application and extract high-value features into containerized microservices while preserving as much of the existing UI as possible.

## Primary Use Case
1. Download the MFS framework to a local path.
2. Open the legacy application repository.
3. Instruct a local AI developer assistant to read MFS Markdown docs first:
- `README.md`
- `docs/MFS_FRAMEWORK_REFERENCE.md`
- `docs/MIGRATION_PLAYBOOK.md`
4. Ask it to discuss the migration approach and produce a feature extraction plan.
5. Execute migration in phases, keeping current UI behavior stable.

## Operator Prompt Starter
Use this in the legacy app workspace:

```text
Read the MFS framework docs in this path: <path-to-MSF>.
Understand the MFS purpose, contracts, registry, scaffold workflow, and migration rules.
Then analyze this legacy app and propose a migration plan to extract large/high-risk features into MFS containers while retaining the existing UI and routes where possible.
Start with candidate discovery, scoring, and a phased cutover plan.
```

## Named Task Profiles
Use onboarding profiles to standardize AI-dev startup behavior.

`auto` profile is also available and will infer a recommended profile from repo signals (size, route density, test density, stack indicators).

1. `discovery_only`
- Purpose: fast initial triage.
- Command:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --profile discovery_only
```

2. `planning_pack`
- Purpose: balanced default for migration planning.
- Command:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --profile planning_pack
```

3. `cutover_ready`
- Purpose: stronger prep for boundary + rollout execution.
- Command:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --profile cutover_ready
```

4. `ci_strict`
- Purpose: high-signal extraction context for stricter gate-driven workflows.
- Command:
```bash
python tools/mfs_onboard.py --target <legacy-repo-path> --profile ci_strict
```

Override defaults as needed with:
- `--features`
- `--workspace`
- `--run-discovery`
- `--discovery-top`
- `--force`

## Migration Outcomes
- Feature execution paths are isolated in service containers.
- Host UI remains mostly unchanged and calls boundaries instead of internal heavy modules.
- Runtime failures are isolated to feature scope.
- Contracts, health endpoints, and drift audits are enforced.

## Phase 0: Readiness
1. Confirm baseline app health (tests, smoke checks, key user journeys).
2. Inventory current architecture:
- UI routes and key screens,
- feature modules and dependencies,
- data stores and external integrations,
- startup/runtime constraints.
3. Define non-negotiables:
- UI parity requirements,
- latency budgets,
- rollback expectations.

## Phase 1: Candidate Discovery (Reverse Engineering)
Discover extraction candidates using:
- route-to-module mapping,
- import/dependency hotspots,
- error-prone modules,
- high-change files,
- heavy CPU/IO/model/tool chains.

Recommended automation:

```bash
python tools/discover_candidates.py --target <legacy-repo-path> --top 20
```

Recommended for real legacy apps to suppress framework/ops noise:

```bash
python tools/discover_candidates.py --target <legacy-repo-path> --top 20 --exclude-buckets docs,tools,scripts,tests,infra
```

Generated artifacts:
- `docs/_generated/candidate_scores.csv`
- `docs/_generated/migration_report.md`
- `docs/_generated/discovery_summary.json`

If runtime telemetry is available, merge it before final scoring:

```bash
python tools/merge_candidate_signals.py --candidates <legacy-repo-path>/docs/_generated/candidate_scores.csv --runtime <runtime-signals.csv>
python tools/score_candidates.py --input <legacy-repo-path>/docs/_generated/merged_candidate_scores.csv --top 20
```

Candidate signals:
- frequent regressions,
- long execution time,
- deep dependency tree,
- clear input/output API boundary,
- independent scaling potential.

## Phase 2: Candidate Scoring
Score each candidate across:
- Business impact.
- Failure blast radius.
- Extraction complexity.
- UI coupling level.
- Test coverage confidence.

Start with high-impact and medium-complexity candidates.

## Phase 3: Contract and Boundary Design
For each selected feature:
1. Define contract JSON in `contracts/<feature>_v1.json`.
2. Keep boundary responsibilities in host app:
- auth and request shaping,
- timeout/retry/readiness,
- status mapping to UI states,
- explicit fallback policy.
3. Scaffold boundary using reusable SDK template:

```bash
python tools/scaffold_boundary.py --feature <feature-name> --base-url <service-base-url>
```
4. Preserve existing UI route/component surface unless change is required.

## Phase 4: Scaffold and Build Service
Use MFS scaffold:

```bash
python tools/scaffold_feature.py --feature <feature-name> --port <port>
```

Generated artifacts:
- `services/<feature>_service/app.py`
- `services/<feature>_service/Dockerfile`
- `services/<feature>_service/requirements.txt`
- `contracts/<feature>_v1.json`
- registry entry in `registry/services.json`

Then replace stub logic with extracted legacy execution logic.

## Phase 5: Cutover Sequencing (UI Preservation First)
Recommended sequence:
1. Keep UI unchanged.
2. Introduce boundary adapter behind existing UI actions.
3. Run boundary in shadow mode if possible.
4. Enable container-first for selected users/environments.
5. Roll out progressively (feature flag or percentage).

Rules:
- No direct UI calls into extracted internals.
- One feature = one boundary adapter.
- Prefer explicit degraded states over hidden local cascades.

## Phase 6: Validation Gates
A migration is complete only when all pass:
1. Contract validation.
2. Health validation.
3. Boundary behavior validation.
4. UI parity validation.
5. Failure isolation validation.
6. Regression suite and smoke checks.

Contract version gate:

```bash
python tools/contract_diff.py --old contracts/<feature>_v1.json --new contracts/<feature>_v2.json --mode both
```

Advanced semantics supported via `field_semantics` in contract JSON (enum/default compatibility checks).

Run framework audit:

```bash
python tools/service_health_audit.py
```

## Phase 7: Rollback and Operations
Before production cutover:
- define rollback trigger and owner,
- keep previous in-process path available briefly,
- add service health alarms and structured logs,
- document runbook for start/restart/degradation.

## Practical UI-Parity Checklist
- Existing routes unchanged.
- Existing buttons/toggles unchanged unless intentional.
- Existing status/error banners preserved.
- Existing metadata displays preserved.
- Non-text outputs (audio/files/previews) preserved.
- Empty/error/loading states preserved.

## Multi-Feature Program Strategy
When migrating multiple features:
1. Migrate one feature end-to-end first.
2. Reuse boundary and observability patterns.
3. Standardize contract fields and status semantics.
4. Keep rollout cadence small and reversible.

## Definition of Success
- Legacy app keeps its familiar UI and user flows.
- Large/high-risk features run in isolated containers.
- New feature migrations follow repeatable MFS workflow.
- Teams can modernize incrementally without a full rewrite.

## Phase 7.5: Cutover Command Path
Create feature cutover manifest:
```bash
python tools/scaffold_cutover.py --feature <feature-name>
```

Run orchestration:
```bash
python tools/cutover_orchestrator.py plan --manifest docs/_generated/<feature>_cutover.json
python tools/cutover_orchestrator.py promote --manifest docs/_generated/<feature>_cutover.json --stage canary_5
python tools/cutover_orchestrator.py status --manifest docs/_generated/<feature>_cutover.json
python tools/cutover_orchestrator.py rollback --manifest docs/_generated/<feature>_cutover.json
```

Quick promote with full UI pre-gates:
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/<feature>_cutover.json --stage canary_5 --ui-checklist <ui-parity-checklist.json> --ui-smoke-spec <ui-smoke-spec.json> --ui-browser-spec <ui-browser-spec.json>
```

## Phase 8: UI Parity Harness Gate
Run parity checklist:
```bash
python tools/ui_parity_checklist.py --checklist <ui-parity-checklist.json>
```

Run smoke assertions:
```bash
python tools/ui_smoke_runner.py --spec <ui-smoke-spec.json>
```

Run browser journey assertions:
```bash
python tools/ui_browser_runner.py --spec <ui-browser-spec.json>
```

Promotion rule:
- Do not promote to next canary stage unless checklist, smoke, and browser checks pass.

CI/CD gate command including browser parity:
```bash
python tools/ci_migration_gates.py --contract-dir contracts --run-health-audit --ui-checklist <ui-parity-checklist.json> --ui-smoke-spec <ui-smoke-spec.json> --ui-browser-spec <ui-browser-spec.json>
```

## V2 Hardening Roadmap
This roadmap focuses only on capabilities required for the MFS mission:
- help AI devs extract and organize legacy-app migration context,
- preserve legacy UI behavior while moving large features to containers,
- reduce manual migration risk and ambiguity.

### Priority 1: Runtime Signal Automation
Current gap:
- Candidate scoring still depends on manually supplied runtime signal CSVs.

Target outcome:
- Auto-ingest latency, error-rate, and change-frequency signals from legacy app telemetry.

Deliverables:
1. Add `tools/ingest_runtime_signals.py` to parse common sources:
- app logs,
- APM exports,
- metrics snapshots (CSV/JSON).
2. Normalize into `runtime_signals.csv` schema automatically.
3. Add confidence markers per signal (`measured`, `estimated`, `missing`).

Success criteria:
- AI dev can run one command and get non-empty runtime signal data for top candidate buckets.

Starter command:
```bash
python tools/ingest_runtime_signals.py --sources <logs/*.jsonl,metrics.csv,app.log> --output <legacy-repo-path>/mfs_migration/runtime_signals.csv
```

### Priority 2: Unified Artifact Ingestion Pack
Current gap:
- No single workflow to collect and label all migration-relevant artifacts.

Target outcome:
- One command generates a complete AI-ready context bundle from legacy repo + optional runtime outputs.

Deliverables:
1. Add `tools/build_migration_pack.py`:
- collects route maps, key modules, API specs, logs, changelog snippets, and scoring outputs.
2. Emit standardized `migration_pack.json` with stable keys.
3. Generate `migration_pack.md` executive summary for fast AI context loading.

Success criteria:
- AI dev starts with one pack file instead of piecing together multiple sources manually.

### Priority 3: Boundary Generation Intelligence
Current gap:
- Boundary stubs are generic and require manual adaptation to legacy call surfaces.

Target outcome:
- Semi-automated boundary scaffolding mapped to detected endpoints/modules.

Deliverables:
1. Extend boundary scaffold with optional mapping input:
- route/function map,
- source module hints.
2. Generate pre-filled method names and endpoint paths from discovery artifacts.
3. Add boundary lint checks for required behaviors:
- timeout,
- retry,
- readiness,
- explicit fallback policy.

Success criteria:
- AI dev spends less time manually wiring boundary entry points.

### Priority 4: Contract Evolution Hardening
Current gap:
- Contract diff checks are useful but not schema-rich.

Target outcome:
- Safer contract evolution with stronger compatibility guarantees.

Deliverables:
1. Add schema-level validation mode (JSON Schema/OpenAPI-compatible fields).
2. Add stricter checks for:
- enum narrowing,
- required/optional transitions,
- default value behavior.
3. Add CI gate to block incompatible changes without approved version bump.

Success criteria:
- Fewer runtime integration regressions during v1->v2 contract transitions.

### Priority 5: Browser-Level UI Parity Validation
Current gap:
- Current harness is checklist + HTTP smoke, but no user-flow browser automation.

Target outcome:
- Reliable UI parity checks for route/action/output behavior under migration.

Deliverables:
1. Add browser smoke harness (Playwright-based):
- route load,
- primary button flow,
- visible status/error metadata checks.
2. Add pre/post migration snapshot comparison support.
3. Integrate into cutover pre-gate option.

Success criteria:
- Promotion blocked automatically when critical user journeys regress.

### Priority 6: Environment-Aware Cutover Integrations
Current gap:
- Orchestrator is command-based and generic; not integrated with common rollout systems.

Target outcome:
- Safer and easier rollout/rollback in real deployment environments.

Deliverables:
1. Add adapters for:
- feature flag providers,
- deployment platform commands,
- health SLO checks.
2. Add staged auto-halt rules:
- error budget breach,
- latency regression thresholds.
3. Add machine-readable incident output for rollback events.

Success criteria:
- Canary expansion and rollback decisions are automated by policy, not manual guesswork.

### Priority 7: Adaptive Onboarding Profiles
Current gap:
- Profiles are static presets and not tuned by actual repo characteristics.

Target outcome:
- `mfs_onboard` selects and tunes profile defaults based on discovered repo traits.

Deliverables:
1. Add `--profile auto` mode.
2. Infer recommended settings from:
- repo size,
- stack type,
- test density,
- route density.
3. Emit explicit rationale in `AI_DEV_START.md`.

Success criteria:
- AI dev gets an immediately appropriate onboarding plan with minimal manual tuning.

Pack builder command:
```bash
python tools/build_migration_pack.py --workspace <legacy-repo-path>/mfs_migration --top 10 --include-file-snippets
```

## Suggested Execution Order
1. Runtime Signal Automation
2. Unified Artifact Ingestion Pack
3. Boundary Generation Intelligence
4. Contract Evolution Hardening
5. Browser-Level UI Parity Validation
6. Environment-Aware Cutover Integrations
7. Adaptive Onboarding Profiles
