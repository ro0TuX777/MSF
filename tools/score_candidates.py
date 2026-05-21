#!/usr/bin/env python3
"""Rank feature extraction candidates from a CSV input.

Usage:
  python tools/score_candidates.py --input candidate_scores.csv --top 10
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_WEIGHTS: Dict[str, float] = {
    "business_impact": 0.16,
    "blast_radius": 0.16,
    "reliability_pain": 0.12,
    "change_velocity": 0.08,
    "dependency_weight": 0.08,
    "api_boundary_clarity": 0.08,
    "test_coverage_confidence": 0.04,
    "ui_coupling": 0.04,
    "extraction_complexity": 0.04,
    "runtime_latency_pain": 0.10,
    "runtime_error_rate_pain": 0.10,
    "runtime_change_frequency": 0.10,
}

INVERT_METRICS = {"ui_coupling", "extraction_complexity"}
OPTIONAL_METRICS_DEFAULTS = {
    "runtime_latency_pain": 5.0,
    "runtime_error_rate_pain": 5.0,
    "runtime_change_frequency": 5.0,
}

REQUIRED_COLUMNS = [
    "name",
    "business_impact",
    "blast_radius",
    "reliability_pain",
    "change_velocity",
    "dependency_weight",
    "api_boundary_clarity",
    "ui_coupling",
    "extraction_complexity",
    "test_coverage_confidence",
]


def _clamp_0_10(value: float) -> float:
    return max(0.0, min(10.0, value))


def _parse_float(raw: str, field: str, row_name: str) -> float:
    try:
        return _clamp_0_10(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for '{field}' in '{row_name}': {raw!r}") from exc


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Weight sum must be > 0.")
    return {k: v / total for k, v in weights.items()}


def _parse_weights_arg(raw: str) -> Dict[str, float]:
    parsed = dict(DEFAULT_WEIGHTS)
    if not raw.strip():
        return _normalize_weights(parsed)

    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Invalid weight token: {token!r}. Expected key=value")
        key, val = token.split("=", 1)
        key = key.strip()
        if key not in DEFAULT_WEIGHTS:
            raise ValueError(f"Unknown weight key: {key!r}")
        try:
            parsed[key] = float(val.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid weight for {key!r}: {val!r}") from exc

    return _normalize_weights(parsed)


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV is missing a header row.")
        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

        rows: List[Dict[str, Any]] = []
        for raw_row in reader:
            name = str(raw_row.get("name", "")).strip()
            if not name:
                continue
            row: Dict[str, Any] = {"name": name}
            for metric in REQUIRED_COLUMNS:
                if metric == "name":
                    continue
                row[metric] = _parse_float(raw_row.get(metric, ""), metric, name)
            for metric, default_val in OPTIONAL_METRICS_DEFAULTS.items():
                raw_val = str(raw_row.get(metric, "")).strip()
                row[metric] = _parse_float(raw_val, metric, name) if raw_val else default_val
            rows.append(row)

    if not rows:
        raise ValueError("No candidate rows found in CSV.")
    return rows


def _score_row(row: Dict[str, Any], weights: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
    contributions: Dict[str, float] = {}
    total = 0.0
    for metric, weight in weights.items():
        raw = float(row[metric])
        effective = 10.0 - raw if metric in INVERT_METRICS else raw
        contribution = (effective / 10.0) * weight * 100.0
        contributions[metric] = round(contribution, 3)
        total += contribution
    return round(total, 3), contributions


def _print_table(scored_rows: List[Dict[str, Any]], top: int) -> None:
    print("rank,name,score")
    for idx, row in enumerate(scored_rows[:top], start=1):
        print(f"{idx},{row['name']},{row['score']:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank feature extraction candidates from CSV")
    parser.add_argument("--input", required=True, help="Path to candidate score CSV")
    parser.add_argument("--top", type=int, default=10, help="How many top candidates to print")
    parser.add_argument(
        "--weights",
        default="",
        help=(
            "Optional comma-separated weight overrides, e.g. "
            "business_impact=0.25,blast_radius=0.2,extraction_complexity=0.03"
        ),
    )
    parser.add_argument("--output-json", default="", help="Optional path to write full ranked output JSON")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    weights = _parse_weights_arg(args.weights)
    rows = _load_rows(input_path)

    scored_rows: List[Dict[str, Any]] = []
    for row in rows:
        score, contributions = _score_row(row, weights)
        scored_rows.append(
            {
                "name": row["name"],
                "score": score,
                "metrics": {k: row[k] for k in DEFAULT_WEIGHTS},
                "contributions": contributions,
            }
        )

    scored_rows.sort(key=lambda item: item["score"], reverse=True)

    _print_table(scored_rows, top=max(1, args.top))

    if args.output_json:
        out_path = Path(args.output_json).resolve()
        out_payload = {
            "input": str(input_path),
            "weights": weights,
            "results": scored_rows,
        }
        out_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
        print(f"\\nWrote detailed output: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
