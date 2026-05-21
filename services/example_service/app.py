"""MFS Example Service.

Reference implementation showing the MFS service pattern:
- GET /health for readiness/liveness
- GET /v1/example/capabilities for contract discovery
- POST /v1/example/process for feature execution

Replace this with your own extracted feature logic.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, request

logger = logging.getLogger("mfs.example_service")

CONTRACT_VERSION = "v1"

app = Flask(__name__)


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _authorized() -> bool:
    expected = os.getenv("MFS_EXAMPLE_TOKEN", "").strip()
    if not expected:
        return True
    auth_header = request.headers.get("Authorization", "")
    return auth_header == f"Bearer {expected}"


def _provider_mode() -> str:
    return os.getenv("MFS_EXAMPLE_PROVIDER", "stub").strip().lower()


def _envelope(*, status: str = "healthy", source: str = "example_service", error: str | None = None) -> Dict[str, Any]:
    if status not in {"healthy", "degraded", "unavailable"}:
        status = "degraded"
    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "source": source,
        "generated_at": _utc_now(),
        "error": error,
    }


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "example-service", "contract_version": CONTRACT_VERSION}), 200


@app.get("/v1/example/capabilities")
def capabilities():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    payload = _envelope()
    payload.update({
        "feature": "example",
        "supports": ["process"],
    })
    return jsonify(payload), 200


@app.post("/v1/example/process")
def process():
    """Stub feature endpoint. Replace with your extracted feature logic."""
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    if _provider_mode() != "legacy_app":
        # Stub mode: return a placeholder response.
        body = request.get_json(silent=True) or {}
        payload = _envelope(source="example_service_stub")
        payload["result"] = {
            "input_received": bool(body),
            "message": "Stub provider active. Set MFS_EXAMPLE_PROVIDER=legacy_app to enable real feature logic.",
        }
        return jsonify(payload), 200

    # Legacy app mode: wire your extracted feature logic here.
    try:
        body = request.get_json(silent=True) or {}
        payload = _envelope()
        payload["result"] = {
            "input_received": bool(body),
            "message": "Legacy provider placeholder. Replace with actual feature call.",
        }
        return jsonify(payload), 200
    except Exception as exc:
        logger.exception("Example service process failed")
        payload = _envelope(status="unavailable", error=str(exc))
        payload["result"] = None
        return jsonify(payload), 200


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("MFS_LOG_LEVEL", "INFO"),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    app.run(host="0.0.0.0", port=int(os.getenv("MFS_EXAMPLE_PORT", "8610")))
