#!/usr/bin/env python3
"""Figure: oracle-unsafe attempts vs unsafe_executed, gate ON vs OFF, per model."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROWS = list(csv.DictReader(open(
    "results/mas_safety_corrected/safety_corrected_results.csv")))
REGIMES = ["FullSync", "Delayed", "ConflictingView"]
SHORT = {"FullSync": "FullSync", "Delayed": "Delayed", "ConflictingView": "ConflictView"}


def get(model, reg, gate, col):
    for r in ROWS:
        if r["model"] == model and r["regime"] == reg and r["gate"] == gate:
            return float(r[col])
    return 0


models = sorted({r["model"] for r in ROWS})
fig, axes = plt.subplots(1, len(models), figsize=(6 * len(models), 4.4), sharey=False)
if len(models) == 1:
    axes = [axes]

for ax, model in zip(axes, models):
    x = range(len(REGIMES)); w = 0.28
    # oracle-unsafe attempts (ground truth) vs unsafe_executed under each gate
    oracle = [get(model, r, "off", "oracle_unsafe_total") for r in REGIMES]
    exec_off = [get(model, r, "off", "unsafe_executed_total") for r in REGIMES]
    exec_on = [get(model, r, "on", "unsafe_executed_total") for r in REGIMES]
    ax.bar([i - w for i in x], oracle, w, label="oracle-unsafe (gate OFF arm)", color="#7f7f7f")
    ax.bar([i for i in x], exec_off, w, label="executed, gate OFF", color="#d62728")
    ax.bar([i + w for i in x], exec_on, w, label="executed, gate ON (RAVEL)", color="#2ca02c")
    ax.set_xticks(list(x)); ax.set_xticklabels([SHORT[r] for r in REGIMES], rotation=15)
    ax.set_title(f"{model.split('/')[-1]} (pooled over 3 seeds)")
    ax.set_ylabel("unsafe writes (count)")
    ax.legend(fontsize=8)

fig.suptitle("RAVEL CommitGate (corrected, oracle-based): unsafe writes executed, gate ON vs OFF")
fig.tight_layout()
fig.savefig("results/mas_safety_corrected/safety_corrected.png", dpi=130)
print("saved results/mas_safety_corrected/safety_corrected.png")
