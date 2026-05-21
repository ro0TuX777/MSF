from abc import ABC, abstractmethod
from typing import Any, Dict

class GovernanceAdmissionAdapter(ABC):
    """
    Base interface for ForgeRoot governance admission adapters.
    """
    
    @abstractmethod
    def admit_cutover_promotion(self, handoff_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a handoff packet to the governance system and return the decision.
        
        The expected returned dictionary should conform to:
        {
          "decision": "ALLOW" | "BLOCK" | "REQUIRE_APPROVAL" | "ESCALATE" | "ERROR",
          "reason": "...",
          "matched_policy": "...",
          "required_action": "...",
          "receipt_ref": "..."
        }
        
        A failure to connect or unexpected exception should result in a decision of "ERROR" to fail-closed.
        """
        pass
