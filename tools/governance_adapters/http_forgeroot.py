import requests
from typing import Any, Dict
from .base import GovernanceAdmissionAdapter

class HttpForgeRootAdapter(GovernanceAdmissionAdapter):
    """
    Thin HTTP adapter for interacting with a real ForgeRoot admission API.
    POSTs the packet, validates response, normalizes decision, and fails closed on error.
    """
    def __init__(self, url: str, timeout_s: float = 10.0, headers: Dict[str, str] = None):
        self.url = url
        self.timeout_s = timeout_s
        self.headers = headers or {}

    def admit_cutover_promotion(self, handoff_packet: Dict[str, Any]) -> Dict[str, Any]:
        try:
            resp = requests.post(
                self.url,
                json=handoff_packet,
                headers=self.headers,
                timeout=self.timeout_s
            )
            resp.raise_for_status()
            payload = resp.json()
            
            if not isinstance(payload, dict):
                return self._build_error("Invalid response format: not a JSON object")
            
            decision = str(payload.get("decision", "")).strip().upper()
            if decision not in ["ALLOW", "BLOCK", "REQUIRE_APPROVAL", "ESCALATE", "ERROR"]:
                return self._build_error(f"Unknown decision from ForgeRoot: {decision}")
                
            return {
                "decision": decision,
                "reason": payload.get("reason", "No reason provided"),
                "matched_policy": payload.get("matched_policy", "unknown"),
                "required_action": payload.get("required_action", "None"),
                "receipt_ref": payload.get("receipt_ref")
            }
            
        except requests.exceptions.RequestException as e:
            return self._build_error(f"HTTP request failed: {str(e)}")
        except Exception as e:
            return self._build_error(f"Unexpected adapter failure: {str(e)}")

    def _build_error(self, reason: str) -> Dict[str, Any]:
        return {
            "decision": "ERROR",
            "reason": reason,
            "matched_policy": "none",
            "required_action": "Check ForgeRoot connectivity or adapter configuration",
            "receipt_ref": None
        }
