#!/usr/bin/env python3
"""Aggregate the corrected (non-circular) write-safety experiment across seeds.

For each (model, regime, gate) cell, pool the 3 seeds and report the PRIMARY
oracle-based metrics with normal-approx 95% CIs over the seed means:
  - unsafe_executed_per_valid_task   (oracle-unsafe writes that ACTUALLY executed)
  - overblock_per_valid_task         (oracle-safe writes the gate blocked)
  - oracle_unsafe_attempt_rate       (oracle-unsafe writes / writes proposed)
  - tokens_per_valid_task
Also pools raw counts (unsafe_executed, oracle_unsafe, writes, valid N, infra).
"""
import csv, glob, json, math
from pathlib import Path

ROOT = Path("/home/xqin5/multiaiagent/results/mas_safety_corrected")
ORDER = {"FullSync": 0, "Delayed": 1, "ConflictingView": 2}


def ci95(vals):
    n = len(vals)
    if n == 0:
        return (0.0, 0.0, 0.0)
    m = sum(vals) / n
    if n < 2:
        return (m, m, m)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    half = 1.96 * sd / math.sqrt(n)
    return (m, m - half, m + half)


def main():
    # cell -> list of per-seed summary dicts
    cells = {}
    for f in glob.glob(str(ROOT / "*/*/condition_summary.json")):
        d = json.load(open(f))
        key = (d["model"], d["regime"], d["gate"])
        cells.setdefault(key, []).append(d)

    rows = []
    for (model, regime, gate), seeds in cells.items():
        # per-seed normalized metrics
        ue = [s["safety"]["unsafe_executed"] / s["n_valid"] if s["n_valid"] else 0 for s in seeds]
        ob = [s["safety"]["overblock"] / s["n_valid"] if s["n_valid"] else 0 for s in seeds]
        ar = [s["safety"]["oracle_unsafe_attempts"] / s["safety"]["write_attempts"]
              if s["safety"]["write_attempts"] else 0 for s in seeds]
        tk = [s["tokens"]["tokens_per_valid_task"] for s in seeds]
        ue_m, ue_lo, ue_hi = ci95(ue)
        ob_m, ob_lo, ob_hi = ci95(ob)
        ar_m, _, _ = ci95(ar)
        tk_m, tk_lo, tk_hi = ci95(tk)
        rows.append({
            "model": model, "regime": regime, "gate": gate, "n_seeds": len(seeds),
            "valid_total": sum(s["n_valid"] for s in seeds),
            "infra_total": sum(s["n_infra"] for s in seeds),
            "writes_total": sum(s["safety"]["write_attempts"] for s in seeds),
            "oracle_unsafe_total": sum(s["safety"]["oracle_unsafe_attempts"] for s in seeds),
            "unsafe_executed_total": sum(s["safety"]["unsafe_executed"] for s in seeds),
            "overblock_total": sum(s["safety"]["overblock"] for s in seeds),
            "unsafe_exec_per_task": round(ue_m, 4), "unsafe_exec_ci_lo": round(ue_lo, 4),
            "unsafe_exec_ci_hi": round(ue_hi, 4),
            "overblock_per_task": round(ob_m, 4), "overblock_ci_lo": round(ob_lo, 4),
            "overblock_ci_hi": round(ob_hi, 4),
            "oracle_unsafe_attempt_rate": round(ar_m, 3),
            "tok_per_task": round(tk_m, 0), "tok_ci_lo": round(tk_lo, 0), "tok_ci_hi": round(tk_hi, 0),
        })

    rows.sort(key=lambda r: (r["model"], ORDER.get(r["regime"], 9), r["gate"]))
    csv_path = ROOT / "safety_corrected_results.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    print(f"{'model':7}{'regime':17}{'gate':5}{'validN':>7}{'infra':>6}{'writes':>7}"
          f"{'oracleU':>8}{'UNSAFE_EXEC':>12}{'overblk':>8}{'tok/task':>9}")
    print("-" * 86)
    for r in rows:
        print(f"{r['model']:7}{r['regime']:17}{r['gate']:5}{r['valid_total']:>7}{r['infra_total']:>6}"
              f"{r['writes_total']:>7}{r['oracle_unsafe_total']:>8}"
              f"{r['unsafe_executed_total']:>12}{r['overblock_total']:>8}{r['tok_per_task']:>9.0f}")
    print(f"\nCSV: {csv_path}")

    # token overhead gate ON vs OFF, per model (paired over regimes)
    print("\n--- token cost (mean tok/task, gate ON vs OFF) ---")
    for model in sorted({r["model"] for r in rows}):
        on = [r["tok_per_task"] for r in rows if r["model"] == model and r["gate"] == "on"]
        off = [r["tok_per_task"] for r in rows if r["model"] == model and r["gate"] == "off"]
        if on and off:
            ao, af = sum(on) / len(on), sum(off) / len(off)
            print(f"  {model}: ON={ao:.0f}  OFF={af:.0f}  overhead={(ao/af-1)*100:+.1f}%")


if __name__ == "__main__":
    main()
