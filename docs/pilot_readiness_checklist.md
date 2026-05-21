# Pilot Readiness Checklist

Use this checklist prior to engaging in a live operational pilot of MSF to modernize a service.

## 1. Environment Preparedness
- [ ] ForgeRoot Adapter is configured in `cutover_manifest.json` (`http` or `mock` for pilot).
- [ ] Boundary Shadow SDK is enabled in the legacy system.
- [ ] Parity shadow logs are actively streaming to the expected directory.
- [ ] Protected Resources static scanner heuristics are calibrated for the target codebase language.

## 2. Policy & Governance Preparedness
- [ ] ForgeRoot admission controller is online and reachable.
- [ ] Escalation path is documented for `REQUIRE_APPROVAL` responses.
- [ ] Approvers are identified and trained on reading MSF Approval Packets.

## 3. Pilot Go/No-Go Decision
*Review all items above before proceeding.*
- **Decision:** [ GO / NO-GO ]
- **Approver:** ____________________
- **Date:** ____________________
- **Required Remediation (if NO-GO):** ____________________
