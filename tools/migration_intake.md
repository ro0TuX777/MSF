# Migration Intake Template (Per Legacy App)

Use this template in the legacy app workspace before proposing extraction.

## 1) App Context
- App name:
- Repository path:
- Primary runtime stack (language/framework):
- Deployment model today:
- Team owner(s):
- Environment(s) targeted for first migration (dev/stage/prod):

## 2) Current Architecture Snapshot
- Main UI entry points/routes:
- High-level backend modules/services:
- Data stores and external dependencies:
- Existing background jobs/workers:
- Known performance bottlenecks:

## 3) Migration Objectives
- Why migrate now:
- What success looks like in 30-60 days:
- UI parity requirements (must-not-change behavior):
- Non-functional constraints (latency, uptime, cost):

## 4) Candidate Discovery Notes
List initial feature candidates and observations:

| Feature | Current Module(s) | User Impact | Failure Impact | UI Coupling | Notes |
|---|---|---|---|---|---|
| | | | | | |

## 5) Data and Dependency Mapping
For each likely candidate, capture:
- Inputs (request/session/state/files):
- Outputs (UI payloads/events/files):
- Internal dependencies:
- External APIs/tools/models:
- Security/PII concerns:

## 6) Boundary Design Notes
For each candidate:
- Proposed contract endpoint(s):
- Required response fields:
- Timeout/retry policy:
- Degraded/unavailable behavior:
- Local fallback policy (if any):

## 7) Cutover Plan (UI Preservation)
- Existing UI route/component to preserve:
- Boundary adapter insertion point:
- Feature flag or phased rollout plan:
- Rollback trigger and rollback path:

## 8) Validation Plan
- Contract tests:
- Boundary tests:
- UI parity checks:
- Isolation checks:
- Regression scope:

## 9) Candidate Scoring Input (CSV)
Create `candidate_scores.csv` with this header and 0-10 values:

```csv
name,business_impact,blast_radius,reliability_pain,change_velocity,dependency_weight,api_boundary_clarity,ui_coupling,extraction_complexity,test_coverage_confidence
```

Scoring guidance:
- Higher is better for: `business_impact`, `blast_radius`, `reliability_pain`, `change_velocity`, `dependency_weight`, `api_boundary_clarity`, `test_coverage_confidence`.
- Higher is worse for: `ui_coupling`, `extraction_complexity` (the scorer inverts these).

Then run:

```bash
python tools/score_candidates.py --input candidate_scores.csv --top 10
```

Optional runtime signals file (`runtime_signals.csv`):

```csv
name,p95_latency_ms,error_rate_pct,requests_per_min,change_events_30d
```

Then merge and score:

```bash
python tools/merge_candidate_signals.py --candidates candidate_scores.csv --runtime runtime_signals.csv
python tools/score_candidates.py --input merged_candidate_scores.csv --top 10
```

## 10) Final Migration Sequence
Fill after scoring:
1. Wave 1 candidates:
2. Wave 2 candidates:
3. Deferred candidates:
4. Risks and mitigations:
