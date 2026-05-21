#!/usr/bin/env python3
"""Ingest runtime telemetry into MFS runtime_signals.csv schema.

Supported sources:
- JSONL logs with feature/latency/error fields
- CSV exports with similar fields
- Plain text logs with key=value pairs

Output schema:
name,p95_latency_ms,error_rate_pct,requests_per_min,change_events_30d
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

KV_PATTERN = re.compile(r"([a-zA-Z_][a-zA-Z0-9_\-]*)=([^\s]+)")


@dataclass
class FeatureRuntime:
    latencies: List[float] = field(default_factory=list)
    total_events: int = 0
    error_events: int = 0
    change_events_30d: int = 0
    timestamps: List[datetime] = field(default_factory=list)


def _parse_dt(raw: object) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _to_bool(raw: object) -> bool:
    text = str(raw or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "error", "failed", "fail"}


def _to_float(raw: object) -> Optional[float]:
    try:
        return float(str(raw).strip())
    except Exception:
        return None


def _extract_feature(payload: Dict[str, object]) -> str:
    for key in ("feature", "name", "service", "component", "module"):
        val = payload.get(key)
        if val is not None:
            text = str(val).strip()
            if text:
                return text
    return "unknown_feature"


def _extract_latency_ms(payload: Dict[str, object]) -> Optional[float]:
    for key in ("latency_ms", "duration_ms", "response_time_ms", "p95_latency_ms"):
        if key in payload:
            return _to_float(payload.get(key))
    return None


def _extract_is_error(payload: Dict[str, object]) -> bool:
    if "error" in payload:
        return _to_bool(payload.get("error"))
    if "is_error" in payload:
        return _to_bool(payload.get("is_error"))
    status = str(payload.get("status", "")).strip().lower()
    if status in {"error", "failed", "fail", "unavailable"}:
        return True
    code = _to_float(payload.get("status_code"))
    if code is not None and code >= 500:
        return True
    return False


def _extract_change_event(payload: Dict[str, object]) -> bool:
    if "change_event" in payload:
        return _to_bool(payload.get("change_event"))
    event = str(payload.get("event", "")).strip().lower()
    if event in {"deploy", "release", "rollback", "config_change", "feature_toggle"}:
        return True
    return False


def _extract_timestamp(payload: Dict[str, object]) -> Optional[datetime]:
    for key in ("timestamp", "ts", "time", "created_at", "event_time"):
        if key in payload:
            dt = _parse_dt(payload.get(key))
            if dt is not None:
                return dt
    return None


def _parse_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield {k: obj[k] for k in obj}


def _parse_csv(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {k: row[k] for k in row if k is not None}


def _parse_kv_log(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            pairs = dict(KV_PATTERN.findall(line))
            if not pairs:
                continue
            yield {k: v for k, v in pairs.items()}


def _iter_records(path: Path, fmt: str) -> Iterable[Dict[str, object]]:
    mode = fmt
    if mode == "auto":
        suffix = path.suffix.lower()
        if suffix in {".jsonl", ".ndjson"}:
            mode = "jsonl"
        elif suffix == ".csv":
            mode = "csv"
        else:
            mode = "log"

    if mode == "jsonl":
        yield from _parse_jsonl(path)
    elif mode == "csv":
        yield from _parse_csv(path)
    elif mode == "log":
        yield from _parse_kv_log(path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(round((len(sorted_vals) - 1) * p))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return float(sorted_vals[idx])


def _rpm(count: int, timestamps: List[datetime]) -> float:
    if count <= 0:
        return 0.0
    if len(timestamps) >= 2:
        start = min(timestamps)
        end = max(timestamps)
        seconds = max(1.0, (end - start).total_seconds())
        minutes = max(1.0 / 60.0, seconds / 60.0)
        return count / minutes
    return float(count)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest runtime telemetry into runtime_signals.csv")
    parser.add_argument("--sources", required=True, help="Comma-separated file paths or globs")
    parser.add_argument("--format", default="auto", choices=["auto", "jsonl", "csv", "log"], help="Input format")
    parser.add_argument("--output", required=True, help="Output runtime signals CSV path")
    parser.add_argument("--exclude-unknown", action="store_true", help="Drop rows with unknown feature name")
    args = parser.parse_args()

    source_patterns = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not source_patterns:
        raise ValueError("--sources must include at least one path or glob")

    files: List[Path] = []
    for pattern in source_patterns:
        p = Path(pattern)
        if any(ch in pattern for ch in "*?[]"):
            files.extend(Path().glob(pattern))
        elif p.exists() and p.is_file():
            files.append(p)

    unique_files = sorted({f.resolve() for f in files})
    if not unique_files:
        raise FileNotFoundError("No telemetry files found from --sources")

    data: Dict[str, FeatureRuntime] = defaultdict(FeatureRuntime)

    for file in unique_files:
        for rec in _iter_records(file, args.format):
            feature = _extract_feature(rec)
            if args.exclude_unknown and feature == "unknown_feature":
                continue

            item = data[feature]
            item.total_events += 1

            latency = _extract_latency_ms(rec)
            if latency is not None and latency >= 0:
                item.latencies.append(latency)

            if _extract_is_error(rec):
                item.error_events += 1

            if _extract_change_event(rec):
                item.change_events_30d += 1

            ts = _extract_timestamp(rec)
            if ts is not None:
                item.timestamps.append(ts)

    rows: List[Dict[str, object]] = []
    for name, metric in sorted(data.items(), key=lambda kv: kv[0]):
        if metric.total_events == 0:
            continue
        error_rate_pct = (metric.error_events / metric.total_events) * 100.0
        row = {
            "name": name,
            "p95_latency_ms": round(_percentile(metric.latencies, 0.95), 3),
            "error_rate_pct": round(error_rate_pct, 4),
            "requests_per_min": round(_rpm(metric.total_events, metric.timestamps), 3),
            "change_events_30d": int(metric.change_events_30d),
        }
        rows.append(row)

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "p95_latency_ms", "error_rate_pct", "requests_per_min", "change_events_30d"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Processed files: {len(unique_files)}")
    print(f"Features extracted: {len(rows)}")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
