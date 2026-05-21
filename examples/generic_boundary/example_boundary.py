"""Example boundary adapter using the MFS Boundary SDK.

Shows how a host app calls an extracted MFS feature through
one boundary adapter with timeout, retry, and readiness logic.

Replace 'example' with your feature name and wire into your host app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add MFS root to path so boundary_sdk is importable.
MFS_ROOT = Path(__file__).resolve().parents[2]
if str(MFS_ROOT) not in sys.path:
    sys.path.insert(0, str(MFS_ROOT))

from boundary_sdk.client import MFSBoundaryClient


def _get_base_url() -> str:
    return os.getenv("MFS_EXAMPLE_BASE_URL", "http://localhost:8610")


# Reusable client instance.
_client = MFSBoundaryClient(
    service_name="example-service",
    base_url=_get_base_url(),
    timeout_s=5.0,
    retries=1,
)


def check_health() -> dict:
    """Check if the example service is reachable and healthy."""
    return _client.health()


def get_capabilities() -> dict:
    """Fetch supported capabilities from the example service."""
    return _client.get("/v1/example/capabilities")


def process(payload: dict) -> dict:
    """Call the example feature's process endpoint.

    Args:
        payload: Feature-specific input data.

    Returns:
        Contract-shaped response dict.
    """
    return _client.post("/v1/example/process", json=payload)


if __name__ == "__main__":
    # Quick smoke test.
    print("Health:", check_health())
    print("Capabilities:", get_capabilities())
    print("Process:", process({"input": "test"}))
