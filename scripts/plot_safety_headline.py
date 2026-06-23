#!/usr/bin/env python3
"""Publication-quality headline figure for the corrected write-safety result.

Top row: per-model grouped bars — oracle-unsafe writes (would-be) vs unsafe writes
that ACTUALLY executed under gate OFF (ablation) and gate ON (RAVEL), by regime.
Bottom: a compact "unsafe execution rate" panel (OFF≈100% vs ON=0%) + token overhead.
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROWS = list(csv.DictReader(open(
    "results/mas_safety_corrected/safety_corrected_results.csv")))
REGIMES = ["FullSync", "Delayed", "ConflictingView"]
LABEL = {"FullSync": "FullSync\n(control)", "Delayed": "Delayed",
         "ConflictingView": "ConflictingView"}
MODELS = sorted({r["model"] for r in ROWS})
MNAME = {m: m.split("/")[-1] for m in MODELS}

C_ORACLE = "#9aa0a6"   # gray  — would-be unsafe (ground truth)
C_OFF = "#e8453c"      # red   — executed, gate OFF
C_ON = "#34a853"       # green — executed, gate ON


def g(model, reg, gate, col):
    for r in ROWS:
        if r["model"] == model and r["regime"] == reg and r["gate"] == gate:
            return float(r[col])
    return 0.0


plt.rcParams.update({"font.size": 11, "axes.titlesize": 12, "axes.spines.top": False,
                     "axes.spines.right": False})
fig = plt.figure(figsize=(13, 7.2))
gs = fig.add_gridspec(2, 2, height_ratios=[2.0, 1.0], hspace=0.42, wspace=0.22)

# --- top row: counts per model ---
ymax = max(g(m, r, "off", "oracle_unsafe_total") for m in MODELS for r in REGIMES) * 1.18
for j, model in enumerate(MODELS):
    ax = fig.add_subplot(gs[0, j])
    x = range(len(REGIMES)); w = 0.26
    oracle = [g(model, r, "off", "oracle_unsafe_total") for r in REGIMES]
    off = [g(model, r, "off", "unsafe_executed_total") for r in REGIMES]
    on = [g(model, r, "on", "unsafe_executed_total") for r in REGIMES]
    b1 = ax.bar([i - w for i in x], oracle, w, color=C_ORACLE, label="oracle-unsafe (would-be)")
    b2 = ax.bar([i for i in x], off, w, color=C_OFF, label="executed — gate OFF (ablation)")
    b3 = ax.bar([i + w for i in x], on, w, color=C_ON, label="executed — gate ON (RAVEL)")
    for bars in (b1, b2, b3):
        for b in bars:
            h = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2, h + ymax * 0.012, f"{int(h)}",
                    ha="center", va="bottom", fontsize=9)
    ax.set_xticks(list(x)); ax.set_xticklabels([LABEL[r] for r in REGIMES])
    ax.set_ylim(0, ymax)
    ax.set_ylabel("unsafe writes (count, pooled over 3 seeds)")
    inf = {r: int(g(model, r, "on", "infra_total") + g(model, r, "off", "infra_total")) for r in REGIMES}
    valid = int(sum(g(model, r, gt, "valid_total") for r in REGIMES for gt in ("on", "off")))
    ax.set_title(f"{MNAME[model]}   (valid N≈{valid}; infra excluded)")
    if j == 0:
        ax.legend(loc="upper left", fontsize=9, frameon=False)

# --- bottom-left: unsafe execution rate (OFF vs ON), adverse regimes only ---
axr = fig.add_subplot(gs[1, 0])
adverse = ["Delayed", "ConflictingView"]
xr = range(len(MODELS)); w = 0.36
def rate(model, gate):
    num = sum(g(model, r, gate, "unsafe_executed_total") for r in adverse)
    den = sum(g(model, r, gate, "oracle_unsafe_total") for r in adverse)
    return 100 * num / den if den else 0
off_rate = [rate(m, "off") for m in MODELS]
on_rate = [rate(m, "on") for m in MODELS]
axr.bar([i - w/2 for i in xr], off_rate, w, color=C_OFF, label="gate OFF")
axr.bar([i + w/2 for i in xr], on_rate, w, color=C_ON, label="gate ON")
for i, m in enumerate(MODELS):
    axr.text(i - w/2, off_rate[i] + 2, f"{off_rate[i]:.0f}%", ha="center", fontsize=9)
    axr.text(i + w/2, on_rate[i] + 2, f"{on_rate[i]:.0f}%", ha="center", fontsize=9)
axr.set_xticks(list(xr)); axr.set_xticklabels([MNAME[m] for m in MODELS])
axr.set_ylim(0, 115); axr.set_ylabel("% of oracle-unsafe\nwrites that executed")
axr.set_title("Unsafe-write execution rate (adverse regimes)")
axr.legend(fontsize=9, frameon=False, loc="center right")

# --- bottom-right: token overhead gate ON vs OFF ---
axt = fig.add_subplot(gs[1, 1])
on_tok = [sum(g(m, r, "on", "tok_per_task") for r in REGIMES) / 3 for m in MODELS]
off_tok = [sum(g(m, r, "off", "tok_per_task") for r in REGIMES) / 3 for m in MODELS]
axt.bar([i - w/2 for i in xr], off_tok, w, color="#9467bd", label="gate OFF")
axt.bar([i + w/2 for i in xr], on_tok, w, color="#1f77b4", label="gate ON")
for i, m in enumerate(MODELS):
    oh = (on_tok[i]/off_tok[i]-1)*100 if off_tok[i] else 0
    axt.text(i, max(on_tok[i], off_tok[i]) + 1200, f"{oh:+.1f}%", ha="center", fontsize=9)
axt.set_xticks(list(xr)); axt.set_xticklabels([MNAME[m] for m in MODELS])
axt.set_ylabel("avg tokens / valid task"); axt.set_title("Token cost (gate ON vs OFF)")
axt.legend(fontsize=9, frameon=False, loc="lower right")

fig.suptitle("RAVEL CommitGate blocks unsafe writes under shared-state drift "
             "(corrected, oracle-based measurement)", fontsize=14, y=0.985)
fig.text(0.5, 0.005,
         "tau2 airline · 50 tasks × 3 seeds · fixed Gemma4 user · Stage-A staleness perturbation · "
         "unsafe = write on stale evidence per an independent oracle · gate-ON misses ARE counted "
         "(test_gate_on_miss_is_counted_non_circular)",
         ha="center", fontsize=8.5, style="italic", color="#444")
fig.savefig("results/mas_safety_corrected/headline_figure.png", dpi=150, bbox_inches="tight")
print("saved results/mas_safety_corrected/headline_figure.png")
