#!/usr/bin/env python3
"""Bar chart of unsafe writes committed, by regime x gate x domain."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROWS = list(csv.DictReader(open("results/mas_safety/safety_results.csv")))


def get(dom, reg, gate, col):
    for r in ROWS:
        if r["domain"] == dom and r["regime"] == reg and r["gate"] == gate:
            return int(r[col])
    return 0


regimes = ["FullSync", "Delayed", "ConflictingView"]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
for ax, dom in zip(axes, ["airline", "retail"]):
    x = range(len(regimes)); w = 0.36
    off = [get(dom, r, "off", "unsafe_committed") for r in regimes]
    on = [get(dom, r, "on", "unsafe_committed") for r in regimes]
    ax.bar([i - w / 2 for i in x], off, w, label="gate OFF (ablation)", color="#d62728")
    ax.bar([i + w / 2 for i in x], on, w, label="gate ON (RAVEL)", color="#2ca02c")
    ax.set_xticks(list(x)); ax.set_xticklabels(regimes, rotation=15)
    ax.set_title(f"{dom} (n=50)"); ax.set_ylabel("unsafe writes committed"); ax.legend()
fig.suptitle("RAVEL CommitGate: unsafe writes under controlled staleness (Gemma4)")
fig.tight_layout()
fig.savefig("results/mas_safety/unsafe_committed.png", dpi=130)
print("saved results/mas_safety/unsafe_committed.png")
