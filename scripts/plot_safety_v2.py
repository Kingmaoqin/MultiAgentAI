#!/usr/bin/env python3
"""v2 figure: unsafe writes by model x regime x gate + token overhead."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROWS = list(csv.DictReader(open("results/mas_safety_v2/safety_v2_results.csv")))
REGIMES = ["FullSync", "Delayed", "RoleAwareFieldMask", "ConflictingView"]
SHORT = {"FullSync": "FullSync", "Delayed": "Delayed",
         "RoleAwareFieldMask": "FieldMask", "ConflictingView": "ConflictView"}


def get(model, reg, gate, col):
    for r in ROWS:
        if r["model"] == model and r["regime"] == reg and r["gate"] == gate:
            return float(r[col])
    return 0


fig, axes = plt.subplots(1, 3, figsize=(15, 4.3))

# panels 1-2: unsafe writes per model
for ax, model in zip(axes[:2], ["gemma4", "gptoss"]):
    x = range(len(REGIMES)); w = 0.36
    off = [get(model, r, "off", "unsafe") for r in REGIMES]
    on = [get(model, r, "on", "unsafe") for r in REGIMES]
    ax.bar([i - w / 2 for i in x], off, w, label="gate OFF (ablation)", color="#d62728")
    ax.bar([i + w / 2 for i in x], on, w, label="gate ON (RAVEL)", color="#2ca02c")
    ax.set_xticks(list(x)); ax.set_xticklabels([SHORT[r] for r in REGIMES], rotation=20)
    ax.set_title(f"{model}: unsafe writes (n=50)"); ax.set_ylabel("unsafe writes committed")
    ax.legend()

# panel 3: token overhead (gate ON vs OFF, avg over regimes)
ax = axes[2]
models = ["gemma4", "gptoss"]
on_tok = [sum(get(m, r, "on", "tok_per_task") for r in REGIMES) / 4 for m in models]
off_tok = [sum(get(m, r, "off", "tok_per_task") for r in REGIMES) / 4 for m in models]
x = range(len(models)); w = 0.36
ax.bar([i - w / 2 for i in x], off_tok, w, label="gate OFF", color="#9467bd")
ax.bar([i + w / 2 for i in x], on_tok, w, label="gate ON", color="#1f77b4")
for i, m in enumerate(models):
    oh = (on_tok[i] / off_tok[i] - 1) * 100 if off_tok[i] else 0
    ax.text(i, max(on_tok[i], off_tok[i]) + 800, f"{oh:+.1f}%", ha="center", fontsize=10)
ax.set_xticks(list(x)); ax.set_xticklabels(models)
ax.set_title("token cost: gate ON vs OFF"); ax.set_ylabel("avg tokens / task"); ax.legend()

fig.suptitle("RAVEL CommitGate across models (Gemma4, gpt-oss) — unsafe writes & token cost")
fig.tight_layout()
fig.savefig("results/mas_safety_v2/safety_v2.png", dpi=130)
print("saved results/mas_safety_v2/safety_v2.png")
