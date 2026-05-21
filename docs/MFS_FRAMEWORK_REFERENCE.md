# MFS Framework Reference (App-Agnostic)

## Purpose
MFS is a modernization framework for existing applications that were not originally designed as microservices.

The framework helps teams extract feature execution into containers without rewriting the entire host app at once.

## Problem MFS Solves
Legacy apps often have tightly coupled feature logic in the UI/runtime path. This creates:
- high regression risk,
- hard-to-isolate failures,
- low deployment flexibility,
- difficult reuse of feature logic.

MFS introduces a controlled extraction path from in-process feature code to containerized services.

## Design Principles
- Feature-first extraction, not full-platform rewrite.
- One feature, one boundary adapter, one contract surface.
- Contract-first communication between host app and extracted service.
- Container-first execution for migrated features.
- Explicit degraded/unavailable states over hidden fallback chains.

## Extraction Model
Each migrated feature has two layers:
- Host App Layer: UI, orchestration, and user flow.
- Service Layer: feature execution logic behind an API.

Minimal service contract:
- `GET /health`
- at least one versioned endpoint under `/v1/...`

## Core Components
- `contracts/*.json`: required payload fields, type expectations, status values, contract version.
- `registry/services.json`: service identity, base URL env vars, endpoint paths, contract location.
- `services/<feature>_service/`: service implementation and Dockerfile.
- `tools/service_health_audit.py`: health + contract drift validation.

## Registry Schema
Each service entry should define:
- `name`
- `base_url_envs` (ordered env var fallbacks)
- `default_base_url`
- `health_path`
- `contract_path`
- `contract_file`

Notes:
- Use generic `MFS_*` env vars for all service base URLs.

## Boundary Adapter Contract
The host app should call each extracted feature only through one boundary adapter.

Boundary responsibilities:
- connection config and auth headers,
- timeout and retry policy,
- readiness checks for startup races,
- mapping service status to host UI/runtime semantics,
- optional fallback behavior (explicitly controlled, never implicit).

Implementation support:
- shared SDK: `boundary_sdk/client.py`
- scaffold tool: `tools/scaffold_boundary.py`

## Migration Workflow
1. Identify candidate feature.
2. Define v1 contract JSON.
3. Extract execution logic into `services/<feature>_service`.
4. Containerize and expose health + versioned endpoints.
5. Create/update host boundary adapter.
6. Register service in `registry/services.json`.
7. Validate with audit and tests.
8. Cut over traffic through the boundary.

## Candidate Selection Heuristics
Prioritize extraction for features with:
- high failure impact,
- heavy dependencies,
- independent scaling needs,
- frequent change velocity,
- clear API boundaries.

Keep local for now when feature is mostly presentation-only and low risk.

## Validation Gates (Definition of Done)
1. Health Validation:
- `/health` returns HTTP 200 with stable payload shape.

2. Contract Validation:
- required fields exist,
- field types match contract JSON,
- `contract_version` matches expected value,
- `status` in allowed values.

3. Boundary Validation:
- remote call path works,
- degraded/unavailable handled cleanly,
- retries/readiness logic avoids startup race failures,
- fallback behavior matches explicit policy.

4. Failure Isolation Validation:
- service failure does not crash host app,
- failure remains scoped to feature path.

5. Regression Validation:
- boundary tests pass,
- contract tests pass,
- no unrelated subsystem regressions.

## Runtime and Operations
Recommended defaults for extracted features:
- container-first routing,
- readiness wait before first call,
- single retry for startup race conditions,
- telemetry on dependency failures,
- structured logs with stable keys.

## Standalone Bootstrap
The repository includes a standalone `docker-compose.yml` with default stub-provider startup for the example service.

Run:
- `docker compose up -d --build`
- `python tools/service_health_audit.py`

## Scaffolding
Use the scaffold tool to create a new service, contract, and registry entry:
- `python tools/scaffold_feature.py --feature <feature-name> --port <port>`
- Scaffold templates are stored in `templates/scaffold/`.

## Contract Evolution
Use contract diff tooling before promoting new contract versions:
- `python tools/contract_diff.py --old contracts/<feature>_v1.json --new contracts/<feature>_v2.json --mode both`

Compatibility modes:
- `backward`: checks if new producer can satisfy old consumers.
- `forward`: checks if old producer can satisfy new consumers.
- `both`: runs both checks.

## Migration Execution Guide
- See `docs/MIGRATION_PLAYBOOK.md` for reverse-engineering workflow, candidate scoring, and phased cutover sequencing.

## Reference Examples
A generic boundary adapter example is provided under `examples/generic_boundary/` to illustrate the boundary SDK pattern.

## Near-Term Framework Evolution
- Add schema-level validation mode for contracts (JSON Schema/OpenAPI-compatible).
- Add environment-aware cutover adapters (feature flag providers, deployment platform hooks).
- Enhance boundary scaffolding with detected endpoint/module mapping.
