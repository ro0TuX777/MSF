# Sample Modernization Walkthrough

This walkthrough demonstrates the end-to-end modernization of the `Payments` module.

## 1. Candidate Profiling
**Command**:
```bash
python tools/assess_candidate_risk.py --source-dir ./legacy/payments --contract ./contracts/payments_v1.json --output docs/_generated/payments_protected_resources.json
```
**Expected Artifact**: `payments_protected_resources.json`
**Outcome**: The static scanner identifies the `checkout` domain and flags `data_sensitivity` as `high`.

## 2. Parity Harness
**Command**:
```bash
python tools/parity_harness.py --log-file shadow/parity.jsonl --output docs/_generated/payments_parity_report.json
```
**Expected Artifact**: `payments_parity_report.json`
**Outcome**: The match rate exceeds 95%. `status` is `PASS`.

## 3. Governance Gate and Promotion
**Command**:
```bash
python tools/cutover_orchestrator.py promote --manifest docs/_generated/payments_cutover.json --stage canary_10 --execute
```
**Expected Artifact**: `payments_governance_handoff.json` (Approval Packet: `msf.approval_packet.promote`)
**Outcome**: Since the endpoints are flagged as `high` sensitivity, ForgeRoot triggers a `REQUIRE_APPROVAL` gate. Promotion halts automatically. The operator escalates the ticket, gets approval, and retries.

## 4. Rollback (Emergency Scenario)
If an issue occurs in `canary_10`, we assess rollback safety.
**Command**:
```bash
python tools/cutover_orchestrator.py rollback --manifest docs/_generated/payments_cutover.json --rollback-checklist docs/_generated/payments_rollback_checklist.json --execute
```
**Expected Gate Outcomes**:
- If `irreversible_mutations_occurred` is `True`, ForgeRoot evaluates the packet and halts the automated rollback (`REQUIRE_APPROVAL`).
- If `data_reconciled` is `True`, ForgeRoot allows the rollback.
