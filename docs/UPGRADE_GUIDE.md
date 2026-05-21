# MSF Upgrade Guide: Migrating to ForgeRoot Governance v1

**Target Audience:** AI Developers / Engineers maintaining earlier versions of the MSF framework or applications relying on older MSF behaviors.

This guide details the structural and operational changes introduced in the MSF Phase 1-9 modernization initiative. To reintegrate and absorb the latest capabilities, your local MSF instance must be updated to align with the new **ForgeRoot-Governed Architecture**.

---

## 1. Governance Handoff (The Biggest Change)

Previously, MSF may have relied on local mock approvals or bypass scripts. MSF now explicitly enforces a **Zero Trust Admission** layer via ForgeRoot.

### What You Need to Change:
- **HTTP Adapter**: Your MSF instance must now securely POST to ForgeRoot for every stage promotion.
  - **Endpoint**: `POST /api/v1/admit` (or as configured in your HTTP adapter).
  - **Payload Schema**: Must strictly conform to `msf.governance_handoff.v1`.
- **Payload Requirements**: You can no longer just send a feature name. The handoff packet MUST contain:
  - `metadata`: Including the action (`msf.approval_packet.promote`) and stage (`canary_5`, `full_100`, etc.).
  - `parity_summary`: Mathematical proof of semantic parity.
  - `rollback_readiness`: Boolean flags proving the mutation is reversible (`irreversible_mutations_occurred`).
  - `protected_resources`: The target's risk profile (`sensitive_domains: ["payments"]`, etc.).

## 2. Managing Policy Decisions

Your `cutover_orchestrator.py` or equivalent promotion loop MUST now natively handle three distinct decisions returned by ForgeRoot:

1. **`ALLOW`**: Proceed with the rollout.
2. **`REQUIRE_APPROVAL`**: Halt the promotion. This happens automatically if the candidate touches sensitive domains (e.g., PII). Your orchestrator must gracefully pause and await human-in-the-loop approval.
3. **`ESCALATE` / `BLOCK`**: Abort the rollout. This occurs if parity fails or irreversible mutations are detected.

*Action Item:* Ensure your deployment scripts do not silently swallow non-ALLOW decisions. A non-ALLOW decision must break the automated pipeline.

## 3. Durable Receipt Persistence

ForgeRoot no longer returns deterministic stub receipts (e.g., `fr_receipt_stub_...`). It returns durable cryptographic receipts (e.g., `sha256:...`).

### What You Need to Change:
- Your orchestrator must extract the `receipt_ref` from the ForgeRoot JSON response.
- This receipt must be persisted in your local `*_cutover.state.json` file.
- The `build_migration_pack.py` tool must package these receipts into the final `closeout_summary.json` for compliance auditing. 

## 4. Dependencies

- We have introduced a strict `requirements.txt` to prevent supply chain drift. Ensure your environment installs dependencies strictly from this file to guarantee compatibility with the new HTTP transport and JSON schema validation layers.

## Reference Files to Absorb
To fully synchronize your legacy MSF application with these updates, have your AI Dev read and sync the following files:
1. `docs/architecture/forgeroot_integration_summary.md` (For the exact architecture and HTTP contract)
2. `docs/operator_runbook.md` (For the updated CLI commands and workflow)
3. `tools/cutover_orchestrator.py` (For the exact implementation of the `REQUIRE_APPROVAL` and `ESCALATE` halting logic)
4. `tools/build_migration_pack.py` (For how receipts are propagated to the closeout summary)
