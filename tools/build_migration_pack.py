#!/usr/bin/env python3
"""Build a single AI-ready migration pack from generated MFS artifacts.

Outputs:
- migration_pack.json
- migration_pack.md
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _read_text_lines(path: Path) -> List[str]:
    text = _read_text(path)
    if not text:
        return []
    return text.splitlines()


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists() or not path.is_file():
        return []
    rows: List[Dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({k: (v or "") for k, v in row.items() if k is not None})
    except Exception:
        return []
    return rows


def _to_float(raw: str, default: float = 0.0) -> float:
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _sort_candidates(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not rows:
        return []
    key = "priority_score" if "priority_score" in rows[0] else "score"
    return sorted(rows, key=lambda r: _to_float(r.get(key, "0"), 0.0), reverse=True)


def _candidate_view(rows: List[Dict[str, str]], top: int) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in _sort_candidates(rows)[: max(1, top)]:
        result.append(
            {
                "name": row.get("name", ""),
                "bucket_label": row.get("bucket_label", ""),
                "priority_score": _to_float(row.get("priority_score", "0"), 0.0),
                "business_impact": _to_float(row.get("business_impact", "0"), 0.0),
                "blast_radius": _to_float(row.get("blast_radius", "0"), 0.0),
                "ui_coupling": _to_float(row.get("ui_coupling", "0"), 0.0),
                "extraction_complexity": _to_float(row.get("extraction_complexity", "0"), 0.0),
            }
        )
    return result


def _collect_artifact(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
    }


def _extract_run_commands(sequence_text: str) -> List[str]:
    lines: List[str] = []
    for line in sequence_text.splitlines():
        text = line.strip()
        if text.lower().startswith("python "):
            lines.append(text)
    return lines


def _boundary_stub_paths(boundaries_dir: Path) -> List[str]:
    if not boundaries_dir.exists() or not boundaries_dir.is_dir():
        return []
    return sorted(str(p) for p in boundaries_dir.glob("*_boundary.py"))


def _detect_target_root(workspace: Path, discovery_dir: Path, context_manifest: Optional[Dict[str, Any]]) -> Optional[Path]:
    if context_manifest and isinstance(context_manifest.get("legacy_target"), str):
        p = Path(str(context_manifest["legacy_target"])).resolve()
        if p.exists() and p.is_dir():
            return p

    summary = _read_json(discovery_dir / "discovery_summary.json")
    if summary and isinstance(summary.get("target"), str):
        p = Path(str(summary["target"])).resolve()
        if p.exists() and p.is_dir():
            return p

    # Fallback: workspace parent may be the legacy repo root.
    if workspace.parent.exists() and workspace.parent.is_dir():
        return workspace.parent.resolve()
    return None


def _snippet_entry(path: Path, *, max_lines: int, max_chars: int) -> Optional[Dict[str, Any]]:
    lines = _read_text_lines(path)
    if not lines:
        return None
    sliced = lines[: max(1, max_lines)]
    content = "\n".join(sliced)
    truncated = False
    if len(content) > max(1, max_chars):
        content = content[: max(1, max_chars)]
        truncated = True
    if len(lines) > len(sliced):
        truncated = True
    return {
        "path": str(path),
        "line_start": 1,
        "line_end": min(len(lines), max(1, max_lines)),
        "total_lines": len(lines),
        "truncated": truncated,
        "content": content,
    }


def _candidate_snippets(
    top_candidates: List[Dict[str, Any]],
    source_rows: List[Dict[str, str]],
    *,
    target_root: Optional[Path],
    max_files_per_candidate: int,
    max_lines: int,
    max_chars: int,
) -> Dict[str, List[Dict[str, Any]]]:
    if target_root is None:
        return {}

    source_index = {row.get("name", ""): row for row in source_rows}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in top_candidates:
        name = str(candidate.get("name", "")).strip()
        row = source_index.get(name, {})
        sample_raw = str(row.get("sample_files", "")).strip()
        if not sample_raw:
            continue
        rel_paths = [s.strip() for s in sample_raw.split(";") if s.strip()]
        snippets: List[Dict[str, Any]] = []
        for rel in rel_paths[: max(1, max_files_per_candidate)]:
            file_path = (target_root / rel).resolve()
            if not file_path.exists() or not file_path.is_file():
                continue
            entry = _snippet_entry(file_path, max_lines=max_lines, max_chars=max_chars)
            if entry is not None:
                snippets.append(entry)
        if snippets:
            out[name] = snippets
    return out


def _build_markdown(pack: Dict[str, Any]) -> str:
    meta = pack["metadata"]
    summary = pack["summary"]
    lines: List[str] = []
    lines.append("# Migration Pack")
    lines.append("")
    lines.append(f"- Generated at: `{meta['generated_at']}`")
    lines.append(f"- Workspace: `{meta['workspace']}`")
    lines.append(f"- Discovery dir: `{meta['discovery_dir']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Candidate source: `{summary['candidate_source']}`")
    lines.append(f"- Total candidate rows: {summary['candidate_rows_total']}")
    lines.append(f"- Top candidates included: {summary['top_candidates_count']}")
    lines.append(f"- Boundary stubs: {summary['boundary_stub_count']}")
    lines.append(f"- Missing critical artifacts: {len(summary['missing_critical_artifacts'])}")
    lines.append(f"- Code snippet candidates: {summary.get('snippet_candidate_count', 0)}")
    lines.append("")

    lines.append("## Top Candidates")
    lines.append("")
    lines.append("| Rank | Name | Label | Priority | UI Coupling | Complexity |")
    lines.append("|---|---|---|---:|---:|---:|")
    for idx, row in enumerate(pack["top_candidates"], start=1):
        lines.append(
            f"| {idx} | {row['name']} | {row['bucket_label'] or '-'} | {row['priority_score']:.3f} | {row['ui_coupling']:.3f} | {row['extraction_complexity']:.3f} |"
        )
    if not pack["top_candidates"]:
        lines.append("| - | (none) | - | - | - | - |")
    lines.append("")

    lines.append("## Boundary Stubs")
    lines.append("")
    if pack["boundary_stubs"]:
        for path in pack["boundary_stubs"]:
            lines.append(f"- `{path}`")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Command Sequence")
    lines.append("")
    if pack["recommended_commands"]:
        for cmd in pack["recommended_commands"]:
            lines.append(f"- `{cmd}`")
    else:
        lines.append("- none")
    lines.append("")

    if summary["missing_critical_artifacts"]:
        lines.append("## Missing Critical Artifacts")
        lines.append("")

    if summary.get("snippet_candidate_count", 0):
        lines.append("## Embedded Snippets")
        lines.append("")
        lines.append("- Snippets are embedded in `migration_pack.json` under `code_snippets`.")
        lines.append("- Use these excerpts for faster AI context loading before deep file reads.")
        lines.append("")
        for item in summary["missing_critical_artifacts"]:
            lines.append(f"- `{item}`")
        lines.append("")

    lines.append("## AI Dev Prompt Seed")
    lines.append("")
    lines.append(
        "Read the MFS docs listed in this pack, then use top candidates and workspace artifacts to produce a phased migration plan that preserves existing UI behavior while extracting large/high-risk features into containerized services."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AI-ready migration_pack from MFS artifacts")
    parser.add_argument("--workspace", required=True, help="Path to onboarding workspace (e.g., <repo>/mfs_migration)")
    parser.add_argument("--discovery-dir", default="", help="Optional discovery directory override")
    parser.add_argument("--output-dir", default="", help="Output directory (default: <workspace>/pack)")
    parser.add_argument("--top", type=int, default=10, help="Top candidates to include")
    parser.add_argument("--include-file-snippets", action="store_true", help="Embed top candidate file snippets into migration_pack.json")
    parser.add_argument("--snippet-max-files-per-candidate", type=int, default=2, help="Max sample files to embed per top candidate")
    parser.add_argument("--snippet-max-lines", type=int, default=120, help="Max lines per snippet")
    parser.add_argument("--snippet-max-chars", type=int, default=6000, help="Max characters per snippet")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace}")

    discovery_dir = Path(args.discovery_dir).resolve() if args.discovery_dir.strip() else (workspace / "discovery").resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir.strip() else (workspace / "pack").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "intake": workspace / "migration_intake.md",
        "plan": workspace / "migration_plan.md",
        "context_manifest": workspace / "context_manifest.json",
        "ai_start": workspace / "AI_DEV_START.md",
        "sequence_script": workspace / "run_mfs_sequence.ps1",
        "candidate_scores": discovery_dir / "candidate_scores.csv",
        "merged_candidate_scores": discovery_dir / "merged_candidate_scores.csv",
        "migration_report": discovery_dir / "migration_report.md",
        "score_results": discovery_dir / "score_results.json",
        "discovery_summary": discovery_dir / "discovery_summary.json",
        "runtime_signals": workspace / "runtime_signals.csv",
        "ui_parity_checklist": workspace / "ui_parity_checklist.json",
        "ui_smoke_spec": workspace / "ui_smoke_spec.json",
        "cutover_manifest": workspace / "cutover_manifest.json",
    }
    
    manifest_path = Path(files["cutover_manifest"])
    handoff_packets = list(manifest_path.parent.glob("*_governance_handoff.json"))
    
    # Sort handoff packets (promote vs rollback)
    promote_packets = [p for p in handoff_packets if "rollback" not in p.name]
    rollback_packets = [p for p in handoff_packets if "rollback" in p.name]
    
    governance_handoff = _read_json(promote_packets[0]) if promote_packets else None
    rollback_handoff = _read_json(rollback_packets[0]) if rollback_packets else None
    
    governance_decision = None
    rollback_decision = None
    parity_report = None
    protected_resources = None
    policy_preview = None
    state_history = []
    
    if promote_packets or rollback_packets:
        base_file = promote_packets[0] if promote_packets else rollback_packets[0]
        state_file = base_file.with_name(base_file.name.replace("_rollback_governance_handoff.json", "_cutover.state.json").replace("_governance_handoff.json", "_cutover.state.json"))
        state = _read_json(state_file)
        if state and "history" in state:
            state_history = state["history"]
            for event in reversed(state["history"]):
                action = event.get("action", "")
                if action.startswith("msf.governance_admission."):
                    if event.get("decision_payload", {}).get("action_type") == "msf.approval_packet.rollback":
                        rollback_decision = event.get("decision_payload")
                    else:
                        governance_decision = event.get("decision_payload")
                    
        parity_file = base_file.with_name(base_file.name.replace("_rollback_governance_handoff.json", "_parity_report.json").replace("_governance_handoff.json", "_parity_report.json"))
        parity_report = _read_json(parity_file) if parity_file.exists() else None
        
        pr_file = base_file.with_name(base_file.name.replace("_rollback_governance_handoff.json", "_protected_resources.json").replace("_governance_handoff.json", "_protected_resources.json"))
        protected_resources = _read_json(pr_file) if pr_file.exists() else None
        
        policy_file = base_file.with_name(base_file.name.replace("_rollback_governance_handoff.json", "_forgeroot_policy_preview.yaml").replace("_governance_handoff.json", "_forgeroot_policy_preview.yaml"))
        policy_preview = policy_file.read_text(encoding="utf-8") if policy_file.exists() else None

    # Generate closeout summary
    closeout_summary = {
        "timeline": state_history,
        "governance_decisions": {
            "promote": governance_decision,
            "rollback": rollback_decision
        },
        "parity_results": parity_report,
        "protected_resources": protected_resources,
        "rollback_evidence": rollback_handoff,
        "unresolved_risks": [] # extracted from rollback handoff if any
    }
    if rollback_handoff:
        closeout_summary["unresolved_risks"] = rollback_handoff.get("requested_action", {}).get("unresolved_risks", [])

    artifacts = {name: _collect_artifact(path) for name, path in files.items()}
    context_manifest = _read_json(files["context_manifest"])
    boundaries_dir = workspace / "boundaries"
    boundary_stubs = _boundary_stub_paths(boundaries_dir)

    merged_rows = _read_csv(files["merged_candidate_scores"])
    candidate_rows = _read_csv(files["candidate_scores"])
    if merged_rows:
        candidate_source = "merged_candidate_scores"
        source_rows = merged_rows
    else:
        candidate_source = "candidate_scores"
        source_rows = candidate_rows

    top_candidates = _candidate_view(source_rows, top=max(1, args.top))
    target_root = _detect_target_root(workspace, discovery_dir, context_manifest)
    code_snippets = (
        _candidate_snippets(
            top_candidates,
            source_rows,
            target_root=target_root,
            max_files_per_candidate=max(1, args.snippet_max_files_per_candidate),
            max_lines=max(1, args.snippet_max_lines),
            max_chars=max(1, args.snippet_max_chars),
        )
        if args.include_file_snippets
        else {}
    )

    sequence_text = _read_text(files["sequence_script"])
    recommended_commands = _extract_run_commands(sequence_text)

    missing_critical = [
        name
        for name in ["intake", "plan", "candidate_scores", "migration_report", "runtime_signals"]
        if not artifacts[name]["exists"]
    ]

    pack: Dict[str, Any] = {
        "metadata": {
            "generated_at": _now_iso(),
            "workspace": str(workspace),
            "discovery_dir": str(discovery_dir),
            "output_dir": str(output_dir),
        },
        "summary": {
            "candidate_source": candidate_source,
            "candidate_rows_total": len(source_rows),
            "top_candidates_count": len(top_candidates),
            "boundary_stub_count": len(boundary_stubs),
            "missing_critical_artifacts": missing_critical,
            "snippet_candidate_count": len(code_snippets),
        },
        "artifacts": artifacts,
        "boundary_stubs": boundary_stubs,
        "top_candidates": top_candidates,
        "code_snippets": code_snippets,
        "recommended_commands": recommended_commands,
        "context_manifest": context_manifest,
        "target_root": str(target_root) if target_root else None,
        "governance": {
            "promote_approval_packet": governance_handoff,
            "promote_decision": governance_decision,
            "rollback_approval_packet": rollback_handoff,
            "rollback_decision": rollback_decision,
            "protected_resources": protected_resources,
            "policy_preview": policy_preview,
        },
        "parity_report": parity_report,
        "closeout_summary": closeout_summary,
    }

    json_path = output_dir / "migration_pack.json"
    json_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    
    closeout_path = output_dir / "closeout_summary.json"
    closeout_path.write_text(json.dumps(closeout_summary, indent=2), encoding="utf-8")
    
    md_path = output_dir / "migration_pack.md"
    md_path.write_text(_build_markdown(pack), encoding="utf-8")

    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"Top candidates included: {len(top_candidates)}")
    print(f"Snippet candidates included: {len(code_snippets)}")
    print(f"Missing critical artifacts: {len(missing_critical)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
