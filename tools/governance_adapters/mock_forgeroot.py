from typing import Any, Dict
from .base import GovernanceAdmissionAdapter

class MockForgeRootAdapter(GovernanceAdmissionAdapter):
    """
    A mock adapter for testing deterministic ForgeRoot outcomes.
    Reads 'mock_decision' from the requested_action in the handoff packet if present,
    otherwise looks for environment variables or defaults to ALLOW.
    """
    
    def __init__(self, default_decision: str = "ALLOW"):
        self.default_decision = default_decision

    def admit_cutover_promotion(self, handoff_packet: Dict[str, Any]) -> Dict[str, Any]:
        # Fail closed on empty/bad packet
        if not handoff_packet:
            return self._build_response("ERROR", "Empty handoff packet")

        requested_action = handoff_packet.get("requested_action", {})
        decision = requested_action.get("mock_decision", self.default_decision)

        # Check sensitive candidate without registered policy (test case 6)
        risk_profile = handoff_packet.get("risk_profile", {})
        if risk_profile.get("data_sensitivity") == "high" and risk_profile.get("governance_risk") == "requires_policy":
            if requested_action.get("force_allow_sensitive") is not True:
                decision = "BLOCK"
                return self._build_response(
                    decision, 
                    "No ForgeRoot policy registered for sensitive service endpoint",
                    "missing_runtime_policy",
                    "Register protected-resource policy before promotion"
                )

        if decision not in ["ALLOW", "BLOCK", "REQUIRE_APPROVAL", "ESCALATE", "ERROR"]:
            decision = "ERROR"
            
        return self._build_response(decision, f"Mocked decision: {decision}")

    def _build_response(self, decision: str, reason: str, matched_policy: str = "default", required_action: str = "None") -> Dict[str, Any]:
        return {
            "decision": decision,
            "reason": reason,
            "matched_policy": matched_policy,
            "required_action": required_action,
            "receipt_ref": f"mock_receipt_{decision.lower()}"
        }
