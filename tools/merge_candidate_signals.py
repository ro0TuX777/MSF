#!/usr/bin/env python3
"""Merge discovery candidate scores with runtime signals.

Usage:
  python tools/merge_candidate_signals.py --candidates docs/_generated/candidate_scores.csv --runtime runtime_signals.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List


def _clamp_0_10(value: float) -> float:
    return max(0.0, min(10.0, value))


def _safe_float(raw: str, default: float = 0.0) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _latency_to_pain(p95_ms: float, *, good_ms: float, bad_ms: float) -> float:
    if p95_ms <= good_ms:
        return 0.0
    if p95_ms >= bad_ms:
        return 10.0
    return _clamp_0_10(((p95_ms - good_ms) / (bad_ms - good_ms)) * 10.0)


def _error_to_pain(error_rate_pct: float, *, bad_pct: float) -> float:
    if error_rate_pct <= 0:
        return 0.0
    if error_rate_pct >= bad_pct:
        return 10.0
    return _clamp_0_10((error_rate_pct / bad_pct) * 10.0)


def _change_freq_to_score(change_events_30d: float, *, cap: float) -> float:
    if change_events_30d <= 0:
        return 0.0
    if change_events_30d >= cap:
        return 10.0
    return _clamp_0_10((change_events_30d / cap) * 10.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge static candidate scores with runtime signals")
    parser.add_argument("--candidates", required=True, help="CSV from discover_candidates.py")
    parser.add_argument("--runtime", required=True, help="Runtime signals CSV")
    parser.add_argument("--output", default="", help="Output CSV path (default: alongside candidates as merged_candidate_scores.csv)")
    parser.add_argument("--latency-good-ms", type=float, default=200.0, help="Latency p95 at or below this is pain=0")
    parser.add_argument("--latency-bad-ms", type=float, default=2000.0, help="Latency p95 at or above this is pain=10")
    parser.add_argument("--error-bad-pct", type=float, default=5.0, help="Error rate pct at or above this is pain=10")
    parser.add_argument("--change-cap-30d", type=float, default=60.0, help="Change events per 30d at or above this is score=10")
    args = parser.parse_args()

    candidates_path = Path(args.candidates).resolve()
    runtime_path = Path(args.runtime).resolve()
    if not candidates_path.exists():
        raise FileNotFoundError(f"Candidates CSV not found: {candidates_path}")
    if not runtime_path.exists():
        raise FileNotFoundError(f"Runtime CSV not found: {runtime_path}")

    candidates = _load_csv(candidates_path)
    runtime_rows = _load_csv(runtime_path)

    runtime_by_name: Dict[str, Dict[str, str]] = {}
    for row in runtime_rows:
        name = str(row.get("name", "")).strip()
        if name:
            runtime_by_name[name] = row

    merged: List[Dict[str, str]] = []
    for row in candidates:
        name = str(row.get("name", "")).strip()
        rt = runtime_by_name.get(name, {})

        p95_ms = _safe_float(rt.get("p95_latency_ms", "0"), 0.0)
        error_pct = _safe_float(rt.get("error_rate_pct", "0"), 0.0)
        change_30d = _safe_float(rt.get("change_events_30d", "0"), 0.0)
        rpm = _safe_float(rt.get("requests_per_min", "0"), 0.0)

        out = dict(row)
        out["p95_latency_ms"] = str(round(p95_ms, 3))
        out["error_rate_pct"] = str(round(error_pct, 4))
        out["change_events_30d"] = str(round(change_30d, 3))
        out["requests_per_min"] = str(round(rpm, 3))
        out["runtime_latency_pain"] = str(round(_latency_to_pain(p95_ms, good_ms=args.latency_good_ms, bad_ms=args.latency_bad_ms), 3))
        out["runtime_error_rate_pain"] = str(round(_error_to_pain(error_pct, bad_pct=args.error_bad_pct), 3))
        out["runtime_change_frequency"] = str(round(_change_freq_to_score(change_30d, cap=args.change_cap_30d), 3))
        merged.append(out)

    out_path = Path(args.output).resolve() if args.output else candidates_path.with_name("merged_candidate_scores.csv")

    fieldnames = list(merged[0].keys()) if merged else []
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in merged:
            writer.writerow(row)

    matched = sum(1 for row in merged if _safe_float(row.get("p95_latency_ms", "0"), 0.0) > 0 or _safe_float(row.get("error_rate_pct", "0"), 0.0) > 0)
    print(f"Merged candidates: {len(merged)}")
    print(f"Runtime matches with non-zero signals: {matched}")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
