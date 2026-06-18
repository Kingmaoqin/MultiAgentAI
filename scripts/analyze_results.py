#!/usr/bin/env python3
"""RAVEL experiment results analyzer.

Loads all completed results and produces:
  - Completion table (baseline vs RAVEL)
  - Paired per-task comparison (baseline vs each regime)
  - Paired bootstrap 95% CI for delta-reward
  - RAVEL safety metrics from exp_summary.json
  - Token efficiency (if available)

Usage:
    python3 scripts/analyze_results.py
    python3 scripts/analyze_results.py --domain airline
    python3 scripts/analyze_results.py --full   # wait for all runs
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Optional

RESULTS_ROOT = Path("/home/xqin5/multiaiagent/results")
CORRECTED_ROOT = Path("/home/xqin5/multiaiagent/results/ravel_corrected")
BASELINE_ROOT = Path("/home/xqin5/multiaiagent/results")  # always points to real baseline
DOMAINS = ["airline", "retail", "telecom"]
REGIMES = ["FullSync", "Delayed", "FieldMask", "ConflictingView"]
N_EXPECTED = {"airline": 10, "retail": 14, "telecom": 14}
BOOT_N = 10_000


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_sims(path: Path) -> list[dict]:
    try:
        d = json.loads(path.read_text())
        return d.get("simulations") or []
    except Exception:
        return []


def sims_to_task_reward(sims: list[dict]) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {}
    for s in sims:
        tid = str(s.get("task_id", ""))
        ri = s.get("reward_info") or {}
        r = ri.get("reward") if isinstance(ri, dict) else getattr(ri, "reward", None)
        try:
            r = float(r) if r is not None else None
        except (TypeError, ValueError):
            r = None
        out[tid] = r
    return out


def sims_to_termination(sims: list[dict]) -> dict[str, str]:
    return {str(s.get("task_id", "")): str(s.get("termination_reason", "")) for s in sims}


def load_exp_summary(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def paired_bootstrap(
    task_ids: list[str],
    base: dict[str, Optional[float]],
    ravel: dict[str, Optional[float]],
    n: int = BOOT_N,
    seed: int = 42,
) -> dict:
    """Paired bootstrap for mean delta reward (RAVEL - baseline)."""
    rng = random.Random(seed)
    paired = []
    for tid in task_ids:
        b = base.get(tid)
        r = ravel.get(tid)
        if b is not None and r is not None:
            paired.append((b, r))

    if len(paired) < 2:
        return {"n_pairs": len(paired), "delta_mean": None, "ci_lo": None, "ci_hi": None, "p_gt0": None}

    obs_delta = sum(r - b for b, r in paired) / len(paired)

    boot_deltas = []
    for _ in range(n):
        sample = rng.choices(paired, k=len(paired))
        boot_deltas.append(sum(r - b for b, r in sample) / len(sample))

    boot_deltas.sort()
    ci_lo = boot_deltas[int(0.025 * n)]
    ci_hi = boot_deltas[int(0.975 * n)]
    p_gt0 = sum(1 for d in boot_deltas if d > 0) / n

    return {
        "n_pairs": len(paired),
        "delta_mean": obs_delta,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "p_gt0": p_gt0,
    }


# ---------------------------------------------------------------------------
# Per-condition summary
# ---------------------------------------------------------------------------

def condition_summary(
    task_ids: list[str],
    tr: dict[str, Optional[float]],
    term: dict[str, str] | None = None,
) -> dict:
    valid = [(tid, r) for tid, r in tr.items() if tid in task_ids and r is not None]
    n_pass = sum(1 for _, r in valid if r >= 1.0)
    n_expected = len(task_ids)
    n_done = len([r for tid, r in tr.items() if tid in task_ids])
    mean_r = sum(r for _, r in valid) / len(valid) if valid else None
    n_timeout = sum(1 for t in (term or {}).values() if "timeout" in t or "max_steps" in t)
    return {
        "n_done": n_done,
        "n_expected": n_expected,
        "n_valid": len(valid),
        "n_pass": n_pass,
        "n_timeout": n_timeout,
        "mean_reward": mean_r,
        "pass_rate": n_pass / n_expected if n_expected else None,
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_r(v: Optional[float], w: int = 6) -> str:
    return f"{v:.3f}".ljust(w) if v is not None else " N/A ".ljust(w)


def fmt_pct(v: Optional[float], w: int = 7) -> str:
    return f"{100*v:.1f}%".ljust(w) if v is not None else "  N/A ".ljust(w)


def fmt_delta(v: Optional[float]) -> str:
    if v is None:
        return " N/A "
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.3f}"


def sig_star(p: Optional[float]) -> str:
    if p is None:
        return "   "
    if p >= 0.95 or p <= 0.05:
        return " **"
    if p >= 0.90 or p <= 0.10:
        return "  *"
    return "   "


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(domain_filter: Optional[str] = None, verbose: bool = False):
    domains = [domain_filter] if domain_filter else DOMAINS

    # ---- Header ----
    print("\n" + "=" * 90)
    print("RAVEL EXPERIMENT ANALYSIS")
    print("=" * 90)

    all_results: dict[str, dict] = {}  # domain -> {condition_name -> task_reward_dict}

    for domain in domains:
        n_exp = N_EXPECTED[domain]
        n_exp_task_ids = None  # will be populated from split CSV

        # Load frozen dev split task IDs
        split_csv = Path("/home/xqin5/multiaiagent/artifacts/task_audit/splits_dev.csv")
        task_ids: list[str] = []
        if split_csv.exists():
            import csv
            with split_csv.open() as f:
                for row in csv.DictReader(f):
                    if row["domain"] == domain:
                        task_ids.append(row["task_id"])
        if not task_ids:
            task_ids = [str(i) for i in range(n_exp)]

        print(f"\n{'─'*90}")
        print(f"DOMAIN: {domain.upper()} ({len(task_ids)} dev tasks)")
        print(f"{'─'*90}")
        print(f"  {'Condition':<36} {'Done':>5} {'MeanR':<8} {'Pass%':<8} {'ΔvsBase':<10} {'95%CI':<22} {'p>0':<6}")
        print(f"  {'-'*84}")

        # Load baseline (llm_agent_gt) — always from original results dir, not corrected
        base_path = BASELINE_ROOT / "dev_baseline" / domain / "results.json"
        base_sims = load_sims(base_path)
        base_tr = sims_to_task_reward(base_sims)
        base_sum = condition_summary(task_ids, base_tr)
        all_results.setdefault(domain, {})["baseline_gt"] = base_tr

        print(f"  {'Baseline (llm_agent_gt)':<36} {base_sum['n_done']:>3}/{base_sum['n_expected']:<2} "
              f"{fmt_r(base_sum['mean_reward'])} {fmt_pct(base_sum['pass_rate'])}"
              f"  {'(reference)'}")

        # Load non-GT baseline if exists
        nongt_path = BASELINE_ROOT / "ravel_exp" / domain / "baseline_llm_agent" / "results.json"
        nongt_sims = load_sims(nongt_path)
        if nongt_sims:
            nongt_tr = sims_to_task_reward(nongt_sims)
            nongt_sum = condition_summary(task_ids, nongt_tr)
            all_results[domain]["baseline_nongt"] = nongt_tr
            print(f"  {'Baseline (llm_agent, no-GT)':<36} {nongt_sum['n_done']:>3}/{nongt_sum['n_expected']:<2} "
                  f"{fmt_r(nongt_sum['mean_reward'])} {fmt_pct(nongt_sum['pass_rate'])}")

        # RAVEL regimes
        for regime in REGIMES:
            # Corrected runs use a flat layout: RESULTS_ROOT/domain/ravel_{regime}/
            # Original runs use: RESULTS_ROOT/ravel_exp/domain/ravel_{regime}/
            flat_path = RESULTS_ROOT / domain / f"ravel_{regime.lower()}" / "results.json"
            nested_path = RESULTS_ROOT / "ravel_exp" / domain / f"ravel_{regime.lower()}" / "results.json"
            rpath = flat_path if flat_path.exists() else nested_path
            if not rpath.exists():
                print(f"  {'RAVEL-'+regime:<36} {'--':>5}{'  (not started)':}")
                continue

            rsims = load_sims(rpath)
            if not rsims:
                print(f"  {'RAVEL-'+regime:<36} {'0':>3}/{n_exp:<2}  (running...)")
                continue

            rtr = sims_to_task_reward(rsims)
            rsum = condition_summary(task_ids, rtr)
            all_results[domain][f"ravel_{regime.lower()}"] = rtr

            boot = paired_bootstrap(task_ids, base_tr, rtr)
            delta_str = fmt_delta(boot["delta_mean"])
            if boot["ci_lo"] is not None:
                ci_str = f"[{boot['ci_lo']:+.3f},{boot['ci_hi']:+.3f}]"
            else:
                ci_str = "N/A"
            star = sig_star(boot["p_gt0"])
            p_str = f"{boot['p_gt0']:.2f}" if boot["p_gt0"] is not None else " N/A"

            print(f"  {'RAVEL-'+regime:<36} {rsum['n_done']:>3}/{rsum['n_expected']:<2} "
                  f"{fmt_r(rsum['mean_reward'])} {fmt_pct(rsum['pass_rate'])}"
                  f"  {delta_str:<10} {ci_str:<22} {p_str:<6}{star}")

            # Verbose: per-task breakdown
            if verbose:
                for tid in sorted(task_ids, key=lambda x: int(x) if x.isdigit() else 0):
                    b = base_tr.get(tid)
                    r = rtr.get(tid)
                    b_str = f"{b:.1f}" if b is not None else " ?"
                    r_str = f"{r:.1f}" if r is not None else " ?"
                    d_str = f"{r-b:+.1f}" if b is not None and r is not None else "  ?"
                    print(f"    task={tid:>4}  base={b_str}  ravel={r_str}  delta={d_str}")

    # ---- Aggregate across domains ----
    print(f"\n{'─'*90}")
    print("AGGREGATE (all domains pooled)")
    print(f"{'─'*90}")

    all_task_ids = []
    for domain in domains:
        split_csv = Path("/home/xqin5/multiaiagent/artifacts/task_audit/splits_dev.csv")
        if split_csv.exists():
            import csv
            with split_csv.open() as f:
                for row in csv.DictReader(f):
                    if row["domain"] in domains:
                        all_task_ids.append(f"{row['domain']}_{row['task_id']}")

    # Build pooled task→reward dicts with domain prefix to avoid collision
    def pool(domain_results: dict, key: str) -> dict[str, Optional[float]]:
        out: dict[str, Optional[float]] = {}
        for domain in domains:
            dr = domain_results.get(domain, {}).get(key, {})
            for tid, r in dr.items():
                out[f"{domain}_{tid}"] = r
        return out

    pool_base = pool(all_results, "baseline_gt")
    for regime in REGIMES:
        k = f"ravel_{regime.lower()}"
        pool_rv = pool(all_results, k)
        if not pool_rv:
            continue
        valid_base = [r for r in pool_base.values() if r is not None]
        valid_rv = [r for r in pool_rv.values() if r is not None]
        if not valid_base or not valid_rv:
            continue
        boot = paired_bootstrap(all_task_ids, pool_base, pool_rv)
        n_pass = sum(1 for r in valid_rv if r >= 1.0)
        mean_rv = sum(valid_rv) / len(valid_rv)
        ci_str = (f"[{boot['ci_lo']:+.3f},{boot['ci_hi']:+.3f}]"
                  if boot["ci_lo"] is not None else "N/A")
        p_str = f"{boot['p_gt0']:.2f}" if boot["p_gt0"] is not None else "N/A"
        star = sig_star(boot["p_gt0"])
        print(f"  {'RAVEL-'+regime:<36} {len(valid_rv):>3}/{len(all_task_ids):<3} "
              f"{fmt_r(mean_rv)} {fmt_pct(n_pass/len(all_task_ids) if all_task_ids else None)}"
              f"  {fmt_delta(boot['delta_mean']):<10} {ci_str:<22} {p_str}{star}")

    print("=" * 90)
    print("\nLegend: ** p>0.95 (or p<0.05), * p>0.90 (or p<0.10)  [paired bootstrap, n=10k]")
    print("Δ = RAVEL_mean_reward - Baseline_mean_reward (positive = RAVEL better)")

    # ---- Save machine-readable summary ----
    summary_path = RESULTS_ROOT / "analysis_summary.json"  # saves in corrected dir if --corrected
    out = {"domains": {}, "regimes": REGIMES}
    for domain in domains:
        split_csv = Path("/home/xqin5/multiaiagent/artifacts/task_audit/splits_dev.csv")
        task_ids = []
        if split_csv.exists():
            import csv
            with split_csv.open() as f:
                for row in csv.DictReader(f):
                    if row["domain"] == domain:
                        task_ids.append(row["task_id"])
        base_tr = all_results.get(domain, {}).get("baseline_gt", {})
        domain_out = {"task_ids": task_ids, "baseline_gt": {}, "ravel": {}}
        base_sum = condition_summary(task_ids, base_tr)
        domain_out["baseline_gt"] = {
            **base_sum,
            "per_task": {tid: base_tr.get(tid) for tid in task_ids},
        }
        for regime in REGIMES:
            k = f"ravel_{regime.lower()}"
            rtr = all_results.get(domain, {}).get(k, {})
            if rtr:
                rsum = condition_summary(task_ids, rtr)
                boot = paired_bootstrap(task_ids, base_tr, rtr)
                domain_out["ravel"][regime] = {
                    **rsum,
                    "bootstrap": boot,
                    "per_task": {tid: rtr.get(tid) for tid in task_ids},
                }
        out["domains"][domain] = domain_out

    summary_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nMachine-readable summary → {summary_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=DOMAINS, default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--corrected", action="store_true",
                        help="Load from ravel_corrected/ directory (fixed CommitGate)")
    args = parser.parse_args()

    if args.corrected:
        # Remap RAVEL paths to corrected directory (baseline always read from BASELINE_ROOT)
        global RESULTS_ROOT
        RESULTS_ROOT = CORRECTED_ROOT

    analyze(domain_filter=args.domain, verbose=args.verbose)


if __name__ == "__main__":
    main()
