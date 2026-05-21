#!/usr/bin/env python3
"""Discover and rank microservice extraction candidates from a legacy repository.

Usage:
  python tools/discover_candidates.py --target <legacy-repo-path>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

DEFAULT_WEIGHTS: Dict[str, float] = {
    "business_impact": 0.20,
    "blast_radius": 0.20,
    "reliability_pain": 0.15,
    "change_velocity": 0.10,
    "dependency_weight": 0.10,
    "api_boundary_clarity": 0.10,
    "test_coverage_confidence": 0.05,
    "ui_coupling": 0.05,
    "extraction_complexity": 0.05,
}
INVERT_METRICS = {"ui_coupling", "extraction_complexity"}

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".rs",
}

EXCLUDE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "out",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
}

ROUTE_PATTERNS = [
    re.compile(r"@\s*app\.(get|post|put|patch|delete|route)\s*\("),
    re.compile(r"@\s*router\.(get|post|put|patch|delete)\s*\("),
    re.compile(r"\b(app|router)\.(get|post|put|patch|delete|use)\s*\("),
    re.compile(r"\b(path|re_path)\s*\("),
    re.compile(r"@\s*(GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)\b"),
]
IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+", re.MULTILINE),
    re.compile(r"^\s*from\s+\S+\s+import\s+", re.MULTILINE),
    re.compile(r"\brequire\s*\("),
]
TODO_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
TEST_FILE_HINT = re.compile(r"(^|[\\/])(test|tests|spec|specs|__tests__)([\\/]|$)|(_test\.|\.test\.|_spec\.|\.spec\.)", re.IGNORECASE)
UI_PATH_HINT = re.compile(r"(^|[\\/])(ui|frontend|web|client|views|components|pages)([\\/]|$)", re.IGNORECASE)


@dataclass
class BucketStats:
    name: str
    files: int = 0
    lines: int = 0
    bytes_size: int = 0
    route_hits: int = 0
    import_hits: int = 0
    todo_hits: int = 0
    complexity_hits: int = 0
    test_files: int = 0
    ui_files: int = 0
    churn_hits: int = 0
    sample_files: List[str] = field(default_factory=list)


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return ""


def _route_hits(content: str) -> int:
    return sum(len(p.findall(content)) for p in ROUTE_PATTERNS)


def _import_hits(content: str) -> int:
    return sum(len(p.findall(content)) for p in IMPORT_PATTERNS)


def _complexity_hits(content: str) -> int:
    return len(re.findall(r"\b(if|for|while|switch|case|try|except|catch)\b", content))


def _bucket_name(target_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(target_root)
    parts = rel.parts
    if len(parts) == 1:
        return "root"
    if parts[0] in {"src", "app", "lib", "services", "modules", "packages"} and len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _iter_source_files(target_root: Path, max_files: int) -> Iterable[Path]:
    count = 0
    for path in target_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        yield path
        count += 1
        if count >= max_files:
            break


def _git_churn_by_file(target_root: Path, since_days: int) -> Dict[str, int]:
    churn: Dict[str, int] = defaultdict(int)
    try:
        probe = subprocess.run(
            ["git", "-C", str(target_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            return churn

        log = subprocess.run(
            ["git", "-C", str(target_root), "log", f"--since={since_days}.days", "--name-only", "--pretty=format:"],
            capture_output=True,
            text=True,
            check=False,
        )
        if log.returncode != 0:
            return churn

        for line in log.stdout.splitlines():
            rel = line.strip()
            if not rel:
                continue
            churn[rel.replace("\\", "/")] += 1
    except Exception:
        return defaultdict(int)
    return churn


def _normalize_0_10(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return max(0.0, min(10.0, (value / cap) * 10.0))


def _score_bucket(stats: BucketStats) -> Dict[str, float]:
    files = float(stats.files)
    lines = float(stats.lines)
    routes = float(stats.route_hits)
    imports = float(stats.import_hits)
    todos = float(stats.todo_hits)
    churn = float(stats.churn_hits)
    complexity = float(stats.complexity_hits)
    test_ratio = (float(stats.test_files) / files) if files else 0.0
    ui_ratio = (float(stats.ui_files) / files) if files else 0.0

    business_impact = _normalize_0_10(routes * 2.0 + files, cap=40.0)
    blast_radius = _normalize_0_10(lines + imports * 20.0, cap=25000.0)
    reliability_pain = _normalize_0_10(todos * 25.0 + complexity + churn * 15.0, cap=8000.0)
    change_velocity = _normalize_0_10(churn, cap=120.0)
    dependency_weight = _normalize_0_10(imports, cap=400.0)
    api_boundary_clarity = max(0.0, min(10.0, _normalize_0_10(routes, cap=15.0) + (2.0 if routes > 0 else 0.0) - ui_ratio * 2.0))
    ui_coupling = max(0.0, min(10.0, ui_ratio * 10.0))
    extraction_complexity = max(
        0.0,
        min(10.0, _normalize_0_10(lines, cap=12000.0) * 0.5 + _normalize_0_10(imports, cap=250.0) * 0.3 + ui_coupling * 0.2),
    )
    test_coverage_confidence = max(0.0, min(10.0, test_ratio * 10.0))

    return {
        "business_impact": round(business_impact, 3),
        "blast_radius": round(blast_radius, 3),
        "reliability_pain": round(reliability_pain, 3),
        "change_velocity": round(change_velocity, 3),
        "dependency_weight": round(dependency_weight, 3),
        "api_boundary_clarity": round(api_boundary_clarity, 3),
        "ui_coupling": round(ui_coupling, 3),
        "extraction_complexity": round(extraction_complexity, 3),
        "test_coverage_confidence": round(test_coverage_confidence, 3),
    }


def _bucket_label(stats: BucketStats) -> str:
    files = float(stats.files or 1)
    ui_ratio = float(stats.ui_files) / files
    if ui_ratio >= 0.6:
        return "ui-heavy"
    if stats.route_hits > 0 and ui_ratio <= 0.2:
        return "service-backend"
    if stats.route_hits > 0:
        return "fullstack-feature"
    if stats.import_hits >= 60 or stats.lines >= 2500:
        return "core-platform"
    return "module"


def _priority_score(metrics: Dict[str, float]) -> float:
    total = 0.0
    for key, weight in DEFAULT_WEIGHTS.items():
        raw = float(metrics[key])
        effective = 10.0 - raw if key in INVERT_METRICS else raw
        total += (effective / 10.0) * weight * 100.0
    return round(total, 3)


def _write_candidate_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    fieldnames = [
        "name",
        "bucket_label",
        "business_impact",
        "blast_radius",
        "reliability_pain",
        "change_velocity",
        "dependency_weight",
        "api_boundary_clarity",
        "ui_coupling",
        "extraction_complexity",
        "test_coverage_confidence",
        "files",
        "lines",
        "route_hits",
        "import_hits",
        "todo_hits",
        "churn_hits",
        "sample_files",
        "priority_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_markdown_report(path: Path, target: Path, rows: List[Dict[str, object]], since_days: int) -> None:
    lines: List[str] = []
    lines.append("# Migration Discovery Report")
    lines.append("")
    lines.append(f"- Target: `{target}`")
    lines.append(f"- Churn window: last {since_days} days (if git history available)")
    lines.append(f"- Candidate buckets analyzed: {len(rows)}")
    lines.append("")
    lines.append("## Top Candidates")
    lines.append("")
    lines.append("| Rank | Candidate | Label | Priority Score | Files | Lines | Route Hits | Churn |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for idx, row in enumerate(rows[:10], start=1):
        lines.append(
            f"| {idx} | {row['name']} | {row['bucket_label']} | {row['priority_score']} | {row['files']} | {row['lines']} | {row['route_hits']} | {row['churn_hits']} |"
        )

    lines.append("")
    lines.append("## Candidate Notes")
    lines.append("")
    for row in rows[:10]:
        lines.append(f"### {row['name']}")
        lines.append(f"- Label: {row['bucket_label']}")
        lines.append(f"- Priority score: {row['priority_score']}")
        lines.append(
            "- Metrics: "
            f"impact={row['business_impact']}, blast={row['blast_radius']}, reliability={row['reliability_pain']}, "
            f"velocity={row['change_velocity']}, dependencies={row['dependency_weight']}, boundary={row['api_boundary_clarity']}, "
            f"ui_coupling={row['ui_coupling']}, complexity={row['extraction_complexity']}, test_conf={row['test_coverage_confidence']}"
        )
        samples = str(row["sample_files"]).split("; ") if row.get("sample_files") else []
        if samples:
            lines.append("- Sample files:")
            for item in samples[:3]:
                lines.append(f"  - `{item}`")
        lines.append("")

    lines.append("## Next Step")
    lines.append("Use `tools/score_candidates.py` with the generated CSV for reweighting and final migration wave selection.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and rank extraction candidates in a legacy repository")
    parser.add_argument("--target", default=".", help="Path to legacy repository root")
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory to write discovery outputs (default: <target>/docs/_generated)",
    )
    parser.add_argument("--max-files", type=int, default=5000, help="Maximum number of source files to scan")
    parser.add_argument("--since-days", type=int, default=180, help="Git churn lookback window in days")
    parser.add_argument("--top", type=int, default=15, help="How many top candidates to print")
    parser.add_argument("--min-lines", type=int, default=80, help="Minimum bucket lines to keep as a candidate")
    parser.add_argument(
        "--exclude-buckets",
        default="docs,doc,scripts,script,tools,tests,test,infra,ops,config,configs,migrations",
        help="Comma-separated bucket prefixes to exclude (e.g. tools,docs,infra)",
    )
    parser.add_argument(
        "--include-buckets",
        default="",
        help="Optional comma-separated bucket prefixes to include (applied before exclusions)",
    )
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Target path is not a directory: {target}")

    churn_by_file = _git_churn_by_file(target, since_days=max(1, args.since_days))

    buckets: Dict[str, BucketStats] = {}
    scanned = 0
    for file_path in _iter_source_files(target, max_files=max(1, args.max_files)):
        scanned += 1
        rel = file_path.relative_to(target)
        bucket = _bucket_name(target, file_path)
        stats = buckets.setdefault(bucket, BucketStats(name=bucket))

        content = _safe_read_text(file_path)
        if not content:
            continue

        line_count = content.count("\n") + 1
        rel_posix = str(rel).replace("\\", "/")

        stats.files += 1
        stats.lines += line_count
        stats.bytes_size += file_path.stat().st_size
        stats.route_hits += _route_hits(content)
        stats.import_hits += _import_hits(content)
        stats.todo_hits += len(TODO_PATTERN.findall(content))
        stats.complexity_hits += _complexity_hits(content)
        stats.churn_hits += int(churn_by_file.get(rel_posix, 0))
        if TEST_FILE_HINT.search(rel_posix):
            stats.test_files += 1
        if UI_PATH_HINT.search(rel_posix):
            stats.ui_files += 1
        if len(stats.sample_files) < 5:
            stats.sample_files.append(rel_posix)

    include_prefixes = [s.strip().strip("/").lower() for s in args.include_buckets.split(",") if s.strip()]
    exclude_prefixes = [s.strip().strip("/").lower() for s in args.exclude_buckets.split(",") if s.strip()]

    def _is_selected_bucket(name: str) -> bool:
        key = name.lower().strip("/")
        if include_prefixes and not any(key == p or key.startswith(p + "/") for p in include_prefixes):
            return False
        if any(key == p or key.startswith(p + "/") for p in exclude_prefixes):
            return False
        return True

    ranked: List[Dict[str, object]] = []
    for name, stats in buckets.items():
        if stats.files == 0:
            continue
        if stats.lines < max(1, args.min_lines):
            continue
        if not _is_selected_bucket(name):
            continue
        metrics = _score_bucket(stats)
        row: Dict[str, object] = {
            "name": name,
            "bucket_label": _bucket_label(stats),
            **metrics,
            "files": stats.files,
            "lines": stats.lines,
            "route_hits": stats.route_hits,
            "import_hits": stats.import_hits,
            "todo_hits": stats.todo_hits,
            "churn_hits": stats.churn_hits,
            "sample_files": "; ".join(stats.sample_files),
        }
        row["priority_score"] = _priority_score(metrics)
        ranked.append(row)

    ranked.sort(key=lambda item: float(item["priority_score"]), reverse=True)

    output_dir = (Path(args.output_dir).resolve() if args.output_dir.strip() else (target / "docs" / "_generated").resolve())
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "candidate_scores.csv"
    report_path = output_dir / "migration_report.md"
    json_path = output_dir / "discovery_summary.json"

    _write_candidate_csv(csv_path, ranked)
    _write_markdown_report(report_path, target=target, rows=ranked, since_days=max(1, args.since_days))

    summary = {
        "target": str(target),
        "scanned_source_files": scanned,
        "candidate_buckets": len(ranked),
        "top": ranked[: max(1, args.top)],
        "outputs": {
            "candidate_scores_csv": str(csv_path),
            "migration_report_md": str(report_path),
            "discovery_summary_json": str(json_path),
        },
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Scanned source files: {scanned}")
    print(f"Candidate buckets: {len(ranked)}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {report_path}")
    print(f"Wrote: {json_path}")
    print("\nTop candidates:")
    for idx, row in enumerate(ranked[: max(1, args.top)], start=1):
        print(f"{idx:>2}. {row['name']} (score={row['priority_score']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
