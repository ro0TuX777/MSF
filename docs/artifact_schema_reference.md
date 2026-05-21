# Artifact Schema Reference

## 1. `_protected_resources.json`
- **Purpose**: Defines static risk profile and sensitive domains detected in the codebase.
- **Fields**: `risk_profile` (sensitivity, governance risk), `endpoints` (domain mapping).

## 2. `_rollback_checklist.json`
- **Purpose**: Manual reconciliation input for the rollback gate.
- **Fields**: `irreversible_mutations_occurred` (bool), `data_reconciled` (bool), `notes` (str).

## 3. `_parity_report.json`
- **Purpose**: Output of the shadow parity validation harness.
- **Fields**: `status` (PASS/FAIL), `total_samples`, `global_match_rate`, `endpoints`.

## 4. `_governance_handoff.json` (Approval Packets)
- **Purpose**: Sent to ForgeRoot for admission decisions.
- **Action Types**: 
  - `msf.approval_packet.promote`
  - `msf.approval_packet.rollback`
  - `msf.approval_packet.final_cutover`
- **Fields**: `requested_action`, `risk_profile`, `state_history_hash`, `service_surface`.

## 5. `.state.json`
- **Purpose**: Transactional log of orchestrator actions.
- **Fields**: `current_stage`, `history` (array of transition events and admission receipts).

## 6. `closeout_summary.json`
- **Purpose**: Ultimate lifecycle audit trace for external review.
- **Fields**: `timeline`, `governance_decisions`, `parity_results`, `rollback_evidence`, `unresolved_risks`.

## 7. `migration_pack.zip`
- **Purpose**: Zipped bundle containing all evidence and closeout configurations.

## 8. `_forgeroot_policy_preview.yaml`
- **Purpose**: Synthesized YAML preview of what ForgeRoot will enforce upon final deployment.
