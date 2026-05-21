# Known Limitations

This document candidly lists the current structural boundaries and limitations of the MSF framework.

## 1. Heuristic Risk Profiling
- **Limitation**: `assess_candidate_risk.py` uses naive string and regex matching (e.g., searching for "checkout" or "token").
- **Impact**: Prone to false positives in loosely named modules, or false negatives if code is heavily obfuscated. It is highly conservative by design.

## 2. Shadow Parity Matching
- **Limitation**: The shadow SDK only captures simple JSON request/response payloads.
- **Impact**: Complex side-effects, asynchronous queues, or multi-step transactional boundaries are not compared.

## 3. Rollback Mutational Safety
- **Limitation**: The rollback readiness gate relies on a manual `_rollback_checklist.json` to declare data mutations.
- **Impact**: It cannot automatically detect database schema drift or silent data writes across microservices.

## 4. Scaffold Adapter
- **Limitation**: Generates basic HTTP/REST interface boundaries.
- **Impact**: Does not support scaffolding gRPC, GraphQL, or raw TCP streams out of the box.

## 5. Mock Governance Adapter
- **Limitation**: The Mock adapter used in offline phases will override explicit decisions if the endpoints are strictly classified as high sensitivity without the `force_allow_sensitive` parameter.
