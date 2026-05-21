# MSF ↔ ForgeRoot Integration Architecture

This document summarizes the final architecture and data flow for the Governed Modernization Lifecycle driven by the Migration Status Framework (MSF) and governed by ForgeRoot.

## Overview
MSF manages the safe extraction of microservices from legacy monoliths by executing a multi-stage canary lifecycle. ForgeRoot acts as the external defense-in-depth governance layer, ensuring that no extraction proceeds to production without satisfying strict parity, authorization, and rollback readiness policies.

## 1. Transport Layer
The communication bridge is an HTTP POST interface.
- **Endpoint:** `POST /api/v1/admit` (hosted by ForgeRoot)
- **Protocol:** HTTP (with HTTPS enforced in production)
- **Payload Schema:** `msf.governance_handoff.v1` (strict JSON)

## 2. Schema Contract (`msf.governance_handoff.v1`)
MSF aggregates evidence during the staging and canary phases and packages it into the handoff payload. The payload includes:
- **`metadata`**: Action, feature name, semantic stage (e.g., `canary_5`, `full_100`).
- **`parity_summary`**: Proof of semantic equivalence (e.g., matching HTTP response shapes and status codes).
- **`rollback_readiness`**: Proof that mutations can be reversed (`irreversible_mutations_occurred`).
- **`protected_resources`**: A risk assessment containing `data_sensitivity` and `sensitive_domains` (e.g., `payments`, `pii`).

## 3. ForgeRoot Policy Evaluation
ForgeRoot applies realistic policy evaluation based on the payload:
1. **Low-Risk (`ALLOW`)**: For read-only, non-sensitive extracts meeting parity. MSF continues its automatic promotion.
2. **High-Risk (`REQUIRE_APPROVAL`)**: For extracts involving sensitive domains (`payments`, `pii`). MSF halts automatic promotion and awaits operator intervention.
3. **Unsafe (`ESCALATE`/`BLOCK`)**: For extracts with irreversible mutations or failed parity. MSF definitively aborts the release.

## 4. Durable Receipt Persistence
For every decision, ForgeRoot returns a deterministic `receipt_ref` (`sha256:...`). MSF ensures this receipt is durable:
- **State File**: Stored in `docs/_generated/*_cutover.state.json` at the time of the event.
- **Migration Pack**: Aggregated into `pack/closeout_summary.json` for long-term audit storage.
- MSF is strictly configured to **reject** mocked or stubbed receipts in production profiles.
