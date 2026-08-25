"""MFS scanners service."""

from __future__ import annotations

import datetime as dt
import os

from flask import Flask, jsonify

CONTRACT_VERSION = "v1"
FEATURE = "scanners"

app = Flask(__name__)


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "scanners-service", "contract_version": CONTRACT_VERSION}), 200


@app.get("/v1/scanners/capabilities")
def capabilities():
    return jsonify(
        {
            "contract_version": CONTRACT_VERSION,
            "status": "healthy",
            "source": "scanners_service",
            "generated_at": _utc_now(),
            "feature": FEATURE,
            "supports": ["health", "capabilities"],
            "error": None,
        }
    ), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("MFS_SCANNERS_PORT", "8620")))
