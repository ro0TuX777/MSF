# Example Migration Pack Structure

The final output of an MSF lifecycle is a zip archive (and JSON representation) that bundles all contextual evidence for auditor review.

## Directory Layout (Unzipped)
```text
migration_pack/
├── closeout_summary.json            # Timeline, decisions, and parity outcomes.
├── migration_pack.json              # Structured data of the entire artifact hierarchy.
├── migration_pack.md                # Human-readable markdown summary.
├── context_manifest.json            # Original context scoping.
├── _generated/
│   ├── feature_cutover.json         # Infrastructure cutover stages.
│   ├── feature_protected_resources.json # Static data sensitivity mapping.
│   ├── feature_parity_report.json   # Shadow match results.
│   ├── feature_governance_handoff.json # Primary approval packet for promotion.
│   ├── feature_rollback_governance_handoff.json # Approval packet for rollback (if applicable).
│   └── feature_forgeroot_policy_preview.yaml # Projected runtime governance policy.
└── boundaries/                      # API contract definitions.
```

## Reviewer Interaction
Auditors should primarily read `closeout_summary.json` to verify:
1. `timeline`: Shows all stage promotions, halted rollbacks, and explicit ForgeRoot admission events.
2. `governance_decisions`: Confirms an `ALLOW` receipt exists before the final cutover occurred.
