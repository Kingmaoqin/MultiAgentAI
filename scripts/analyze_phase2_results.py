#!/usr/bin/env python3
"""Phase-2 results analyzer (plan §3.2).

Walks a results directory of trial summaries + canonical event logs, computes the
trial-level metric row for each, and writes one CSV. Zero-denominator / undefined
metrics are written as the literal ``NA`` (never coerced to 0), per plan §9.8.

Usage:
  python scripts/analyze_phase2_results.py \
      --results-dir results/phase2/<run> \
      --out artifacts/phase2/tables/main_results.csv \
      [--reference-regime FullSync]

Reference (FullSync) trajectories are matched per (domain, task_id, method,
model, seed) so trajectory_edit_distance_to_fullsync / first_divergence_step are
computed against the same task's FullSync run when present.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ravel_core import metrics as M
from ravel_core.event_logger import read_events, normalize_mas_trace

# Column order for the output CSV (plan §3.2).
COLUMNS = [
    "trial_id", "domain", "task_id", "method", "regime", "model", "seed",
    "success_final_state", "official_reward", "policy_violation_count",
    "total_llm_calls", "total_tool_calls", "read_tool_calls", "write_tool_calls",
    "total_input_tokens", "total_output_tokens", "uncached_input_tokens",
    "visible_field_count", "raw_field_count", "ledger_records",
    "raw_fetch_count", "ledger_fetch_count", "reconcile_steps",
    "candidate_write_count", "committed_write_count", "blocked_write_count",
    "EvidenceValidRate", "StaleActionRate", "ConflictingWriteRate",
    "UnsafeActionRate", "CaughtConflictRate", "RecoveryRate", "OverblockRate",
    "trajectory_edit_distance_to_fullsync", "first_divergence_step",
    "tool_selection_accuracy", "argument_accuracy",
    "dependency_order_satisfaction", "loop_count", "unnecessary_retry_count",
    "failure_type",
]


def _na(v: Any) -> Any:
    """Render None (undefined / zero-denominator) as NA for the CSV."""
    return "NA" if v is None else v


def _load_summary(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return json.load(fh)


def _events_for(summary: dict[str, Any], summary_path: Path) -> list[dict[str, Any]]:
    """Load the canonical event log for a summary, normalizing legacy traces."""
    header = {k: summary.get(k) for k in
              ("trial_id", "domain", "task_id", "method", "regime", "model", "seed")}
    # explicit pointer first
    ptr = summary.get("event_log")
    candidates = [Path(ptr)] if ptr else []
    stem = summary_path.stem.replace("_summary", "")
    candidates += [
        summary_path.with_name(f"{stem}_events.jsonl"),
        summary_path.with_name(f"{stem}.jsonl"),
    ]
    for c in candidates:
        if c and c.exists():
            rows = list(read_events(c))
            # canonical rows already have event_type; legacy have 'kind'
            if rows and "kind" in rows[0] and "event_type" not in rows[0]:
                return normalize_mas_trace(rows, header=header)
            return rows
    return []


def build_row(summary: dict[str, Any], events: list[dict[str, Any]],
              reference_seq: list[tuple[str, str]] | None,
              write_tool_names: set[str] | None = None) -> dict[str, Any]:
    safety = M.derive_safety_metrics(summary)
    tokens = M.aggregate_token_usage(events) if events else {}
    calls = M.count_tool_calls(events, write_tool_names) if events else {}
    seq = M.canonical_tool_sequence(events) if events else []
    traj = M.trajectory_metrics(seq, reference_seq)

    n_read = calls.get("read_tool_calls")
    n_write = calls.get("write_tool_calls")
    total_tool = None if n_read is None and n_write is None else (n_read or 0) + (n_write or 0)

    row = {
        "trial_id": summary.get("trial_id"),
        "domain": summary.get("domain"),
        "task_id": summary.get("task_id"),
        "method": summary.get("method"),
        "regime": summary.get("regime"),
        "model": summary.get("model"),
        "seed": summary.get("seed"),
        "success_final_state": summary.get("official_reward"),
        "official_reward": summary.get("official_reward"),
        "policy_violation_count": len(summary.get("policy_violations") or []),
        "total_llm_calls": calls.get("total_llm_calls"),
        "total_tool_calls": total_tool,
        "read_tool_calls": n_read,
        "write_tool_calls": n_write,
        "total_input_tokens": tokens.get("total_input_tokens"),
        "total_output_tokens": tokens.get("total_output_tokens"),
        "uncached_input_tokens": tokens.get("uncached_input_tokens"),
        "visible_field_count": summary.get("visible_field_count"),
        "raw_field_count": summary.get("raw_field_count"),
        "ledger_records": summary.get("ledger_records"),
        "raw_fetch_count": summary.get("raw_fetch_count"),
        "ledger_fetch_count": summary.get("ledger_fetch_count"),
        "reconcile_steps": summary.get("n_reconciliation_steps"),
        "candidate_write_count": summary.get("n_candidate_writes"),
        "committed_write_count": summary.get("n_executed_writes"),
        "blocked_write_count": (
            (summary.get("n_candidate_writes") or 0) - (summary.get("n_executed_writes") or 0)
            if summary.get("n_candidate_writes") is not None else None),
        "EvidenceValidRate": safety.get("evidence_valid_rate"),
        "StaleActionRate": safety.get("stale_action_rate"),
        "ConflictingWriteRate": safety.get("conflicting_write_rate"),
        "UnsafeActionRate": safety.get("unsafe_action_rate"),
        "CaughtConflictRate": safety.get("conflicting_write_catch_rate"),
        "RecoveryRate": safety.get("recovery_rate"),
        "OverblockRate": safety.get("overblock_rate"),
        "failure_type": summary.get("failure_type"),
        **traj,
    }
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference-regime", default="FullSync")
    args = ap.parse_args()

    rdir = Path(args.results_dir)
    summary_paths = sorted(rdir.rglob("*_summary.json"))
    if not summary_paths:
        print(f"no *_summary.json under {rdir}", file=sys.stderr)
        return 1

    loaded = [(p, _load_summary(p)) for p in summary_paths]

    # index FullSync reference sequences per (domain, task_id, method, model, seed)
    ref_seqs: dict[tuple, list[tuple[str, str]]] = {}
    for p, s in loaded:
        if s.get("regime") == args.reference_regime:
            key = (s.get("domain"), s.get("task_id"), s.get("method"),
                   s.get("model"), s.get("seed"))
            ref_seqs[key] = M.canonical_tool_sequence(_events_for(s, p))

    rows = []
    for p, s in loaded:
        key = (s.get("domain"), s.get("task_id"), s.get("method"),
               s.get("model"), s.get("seed"))
        ref = ref_seqs.get(key) if s.get("regime") != args.reference_regime else None
        rows.append(build_row(s, _events_for(s, p), ref))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _na(r.get(k)) for k in COLUMNS})
    print(f"wrote {len(rows)} trial rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
