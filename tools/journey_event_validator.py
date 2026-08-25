#!/usr/bin/env python3
"""Validate canonical MSF semantic UI event receipts."""

from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = {
    "schema_version", "session_id", "run_id", "journey_id", "step_index",
    "requested", "resolved", "observed", "resulting_state", "result",
}


def validate_event(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - event.keys())
    if missing:
        errors.append(f"event_invalid: missing fields: {', '.join(missing)}")
    if event.get("schema_version") != "msf.semantic_event.v1":
        errors.append("event_invalid: unsupported schema_version")
    if not isinstance(event.get("step_index"), int):
        errors.append("event_invalid: step_index must be an integer")
    if event.get("result") not in {"passed", "failed"}:
        errors.append("event_invalid: result must be passed or failed")
    if not isinstance(event.get("requested"), dict) or not isinstance(event.get("resolved"), dict):
        errors.append("event_invalid: requested and resolved must be objects")
    return errors


def validate_events(events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for index, event in enumerate(events):
        errors.extend(f"step {index}: {error}" for error in validate_event(event))
    return errors