# CI Gate Matrix

This matrix maps automated tests to the lifecycle claims they validate, dictating fail-closed behavior across the pipeline.

| Lifecycle Claim | CI Test Execution | Failure Behavior |
| --- | --- | --- |
| **Parity Matching** | `parity_harness.py` executed before promotion | If samples < 25 or threshold missed, `cmd_promote` halts *before* ForgeRoot admission. |
| **Protected Resource Identification** | `assess_candidate_risk.py` executed during scaffolding | Missing risk profiles route as `unknown` (failing closed in strict ForgeRoot policies). |
| **Pre-Promote Governance Admission** | `cutover_orchestrator.py` `cmd_promote` | Any non-`ALLOW` response (e.g., `REQUIRE_APPROVAL`, `BLOCK`) halts the orchestrator immediately. |
| **Pre-Rollback Governance Admission** | `cutover_orchestrator.py` `cmd_rollback` | Automatically halted if `irreversible_mutations_occurred=True` without manual override. |
| **Migration Closeout Auditing** | `build_migration_pack.py` executed post-lifecycle | Fails if missing critical lifecycle artifacts or corrupted state signatures. |
