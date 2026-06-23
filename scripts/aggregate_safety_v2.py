#!/usr/bin/env python3
"""Aggregate the cross-model + FieldMask + token safety experiment."""
import csv, json, glob
from pathlib import Path

ROOT = Path("/home/xqin5/multiaiagent/results/mas_safety_v2")
ORDER = {"FullSync": 0, "Delayed": 1, "RoleAwareFieldMask": 2, "ConflictingView": 3}


def main():
    rows = []
    for model_dir in sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name != "logs"):
        for f in glob.glob(str(model_dir / "*/condition_summary.json")):
            d = json.load(open(f)); s = d["safety"]; t = d.get("tokens", {})
            rows.append({
                "model": model_dir.name, "regime": d["regime"], "gate": d["gate"],
                "pass": round(d.get("pass_rate") or 0, 3),
                "writes": s["write_attempts"], "stale": s["stale_attempts"],
                "blind": s.get("blind_attempts", 0), "blocked": s["blocked"],
                "unsafe": s["unsafe_committed"],
                "tok_per_task": t.get("tokens_per_task", 0),
                "total_tokens": t.get("total_tokens", 0),
            })
    if not rows:
        print("(no v2 conditions complete yet)"); return
    rows.sort(key=lambda r: (r["model"], ORDER.get(r["regime"], 9), r["gate"]))
    csv_path = ROOT / "safety_v2_results.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    print(f"{'model':8}{'regime':19}{'gate':5}{'pass':>6}{'writes':>7}{'stale':>6}"
          f"{'blind':>6}{'blocked':>8}{'unsafe':>7}{'tok/task':>9}")
    print("-" * 86)
    for r in rows:
        print(f"{r['model']:8}{r['regime']:19}{r['gate']:5}{r['pass']:>6}{r['writes']:>7}"
              f"{r['stale']:>6}{r['blind']:>6}{r['blocked']:>8}{r['unsafe']:>7}{r['tok_per_task']:>9.0f}")
    print(f"\nCSV: {csv_path}")

    # token cost: gate ON vs OFF, averaged across regimes per model
    print("\n--- Token cost (avg tokens/task, gate ON vs OFF) ---")
    for model in sorted({r["model"] for r in rows}):
        on = [r["tok_per_task"] for r in rows if r["model"] == model and r["gate"] == "on"]
        off = [r["tok_per_task"] for r in rows if r["model"] == model and r["gate"] == "off"]
        if on and off:
            ao, af = sum(on) / len(on), sum(off) / len(off)
            oh = (ao / af - 1) * 100 if af else 0
            print(f"  {model}: ON={ao:.0f}  OFF={af:.0f}  overhead={oh:+.1f}%")


if __name__ == "__main__":
    main()
