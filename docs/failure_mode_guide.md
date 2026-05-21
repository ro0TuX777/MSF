# Failure Mode Guide

This guide describes operational procedures for recovering from standard lifecycle blockages.

## 1. Governance Requires Approval
- **Symptom**: `cmd_promote` aborts with `promotion_result: halted_by_governance`.
- **Likely Cause**: High data sensitivity or critical domains detected (e.g. Payments).
- **Inspection Point**: `_governance_handoff.json` `requested_action.action_type`.
- **Expected State Event**: `msf.governance_admission.require_approval`.
- **Operator Action**: Present the approval packet to the ForgeRoot board for manual sign-off.
- **Retry Safety**: Safe. Re-running the command after approval bypasses the halt block.
- **Escalation**: Escalation to InfoSec required if approval is denied.

## 2. Irreversible Mutation Halted Rollback
- **Symptom**: `cmd_rollback` aborted.
- **Likely Cause**: Operator flagged `irreversible_mutations_occurred=True` in the checklist.
- **Inspection Point**: `_rollback_readiness.json` status `IRREVERSIBLE_CHANGE_DETECTED`.
- **Expected State Event**: `msf.rollback.halted_by_governance`.
- **Operator Action**: Perform manual DB reconciliation, then check `data_reconciled=True`.
- **Retry Safety**: Wait for manual reconciliation before retrying.
- **Escalation**: Requires DBA/Architecture review.

## 3. Parity Shadow Failure
- **Symptom**: Parity harness returns `FAIL` and promotion blocked.
- **Likely Cause**: Insufficient traffic (`samples < 25`) or mismatched API payload fields.
- **Inspection Point**: `_parity_report.json` `mismatched_keys`.
- **Expected State Event**: `msf.promotion.halted_by_parity`.
- **Operator Action**: Fix the extracted service logic to match legacy API payloads exactly.
- **Retry Safety**: Safe. Re-run parity harness when service is fixed.
- **Escalation**: Developer team.
