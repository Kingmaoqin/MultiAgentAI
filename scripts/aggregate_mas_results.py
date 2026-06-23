#!/usr/bin/env python3
"""Aggregate MAS experiment results into a single table + CSV."""

import csv
import json
from pathlib import Path

OUT = Path("/home/xqin5/multiaiagent/results/mas_experiment")
REGIMES = ["fullsync", "delayed", "roleawarefieldmask", "conflictingview"]


def main():
    rows = []
    for model_dir in sorted(p for p in OUT.iterdir() if p.is_dir() and p.name != "logs"):
        for domain_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            for regime_dir in sorted(p for p in domain_dir.iterdir() if p.is_dir()):
                s = regime_dir / "exp_summary.json"
                if not s.exists():
                    continue
                d = json.loads(s.read_text())
                rows.append({
                    "model": model_dir.name, "domain": domain_dir.name,
                    "regime": d.get("regime", regime_dir.name),
                    "n_pass": d.get("n_pass"), "n_tasks": d.get("n_tasks"),
                    "pass_rate": d.get("pass_rate"),
                    "elapsed_s": d.get("elapsed_s"),
                })

    if not rows:
        print("(no results yet)")
        return

    csv_path = OUT / "mas_results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{'model':10} {'domain':8} {'regime':18} {'pass':>8} {'rate':>6} {'sec':>7}")
    print("-" * 62)
    for r in rows:
        pr = f"{100*r['pass_rate']:.0f}%" if r["pass_rate"] is not None else "?"
        print(f"{r['model']:10} {r['domain']:8} {r['regime']:18} "
              f"{r['n_pass']}/{r['n_tasks']:<5} {pr:>6} {r['elapsed_s']:>7}")
    print(f"\nCSV: {csv_path}")


if __name__ == "__main__":
    main()
