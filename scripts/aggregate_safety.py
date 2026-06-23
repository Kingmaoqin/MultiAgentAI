#!/usr/bin/env python3
"""Aggregate write-safety experiment conditions into a table + CSV."""
import csv, json, glob
from pathlib import Path

OUT = Path("/home/xqin5/multiaiagent/results/mas_safety/gemma4")


def main():
    rows = []
    for f in glob.glob(str(OUT / "*/condition_summary.json")):
        d = json.load(open(f))
        s = d["safety"]
        rows.append({
            "domain": d["domain"], "regime": d["regime"], "gate": d["gate"],
            "n_tasks": d["n_tasks"], "pass_rate": round(d.get("pass_rate") or 0, 3),
            "writes": s["write_attempts"], "stale": s["stale_attempts"],
            "conflict": s["conflict_attempts"], "blocked": s["blocked"],
            "committed": s["committed"], "unsafe_committed": s["unsafe_committed"],
            "unsafe_rate": round(d.get("unsafe_committed_rate") or 0, 3),
        })
    if not rows:
        print("(no conditions complete yet)"); return
    order = {"FullSync": 0, "Delayed": 1, "ConflictingView": 2}
    rows.sort(key=lambda r: (r["domain"], order.get(r["regime"], 9), r["gate"]))
    csv_path = OUT.parent / "safety_results.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"{'domain':8}{'regime':17}{'gate':5}{'pass':>6}{'writes':>8}{'stale':>7}{'blocked':>9}{'unsafe':>8}{'unsafe_rate':>13}")
    print("-" * 81)
    for r in rows:
        print(f"{r['domain']:8}{r['regime']:17}{r['gate']:5}{r['pass_rate']:>6}{r['writes']:>8}"
              f"{r['stale']:>7}{r['blocked']:>9}{r['unsafe_committed']:>8}{r['unsafe_rate']:>13}")
    print(f"\nCSV: {csv_path}")
    print("\nRAVEL thesis check: under Delayed/ConflictingView, gate=on should give "
          "unsafe_committed≈0 while gate=off gives unsafe_committed>0; FullSync≈0 both.")


if __name__ == "__main__":
    main()
