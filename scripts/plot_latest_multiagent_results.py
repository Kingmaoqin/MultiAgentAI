#!/usr/bin/env python3
"""Generate the latest RAVEL multi-agent safety figures in figures/."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures"
CORRECTED = ROOT / "results/mas_safety_corrected/safety_corrected_results.csv"
V2 = ROOT / "results/mas_safety_v2/safety_v2_results.csv"

RED = "#C43C39"
GREEN = "#16836F"
GRAY = "#98A2AE"
BLUE = "#2E6BE6"
AMBER = "#D97706"
INK = "#172033"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def number(
    rows: list[dict[str, str]],
    model: str,
    regime: str,
    gate: str,
    field: str,
) -> float:
    for row in rows:
        if (
            row["model"] == model
            and row["regime"] == regime
            and row["gate"] == gate
        ):
            return float(row[field])
    raise KeyError((model, regime, gate, field))


def configure() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.labelcolor": INK,
            "axes.edgecolor": "#B8C0CC",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "text.color": INK,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def save(fig: plt.Figure, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / name, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_corrected_headline(rows: list[dict[str, str]]) -> None:
    models = ["openai/g4", "openai/gpt-oss"]
    model_labels = ["Gemma-4-31B", "GPT-OSS-120B"]
    regimes = ["FullSync", "Delayed", "ConflictingView"]
    labels = ["FullSync\ncontrol", "Delayed", "Conflicting\nview"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), sharey=True)
    for ax, model, model_label in zip(axes, models, model_labels):
        x = np.arange(len(regimes))
        width = 0.25
        oracle = [
            number(rows, model, regime, "off", "oracle_unsafe_total")
            for regime in regimes
        ]
        executed_off = [
            number(rows, model, regime, "off", "unsafe_executed_total")
            for regime in regimes
        ]
        executed_on = [
            number(rows, model, regime, "on", "unsafe_executed_total")
            for regime in regimes
        ]
        bars = [
            ax.bar(x - width, oracle, width, color=GRAY, label="Oracle-unsafe attempts"),
            ax.bar(x, executed_off, width, color=RED, label="Executed: gate OFF"),
            ax.bar(x + width, executed_on, width, color=GREEN, label="Executed: gate ON"),
        ]
        for group in bars:
            for bar in group:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 3,
                    str(int(bar.get_height())),
                    ha="center",
                    fontsize=9,
                )
        ax.set_xticks(x, labels)
        ax.set_title(model_label)
        ax.set_ylabel("Unsafe writes pooled over 3 seeds")
        ax.set_ylim(0, max(oracle + executed_off + executed_on) * 1.20 + 5)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left")
    fig.suptitle(
        "RAVEL CommitGate Blocks Oracle-Unsafe Writes Under Shared-State Drift",
        fontsize=18,
        weight="bold",
    )
    fig.text(
        0.5,
        0.01,
        "Corrected oracle-based measurement. Gate-ON misses are counted; infrastructure runs are excluded.",
        ha="center",
        fontsize=9,
        color="#5F6B7A",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    save(fig, "fig01_corrected_unsafe_writes.png")


def plot_rates_and_overblock(rows: list[dict[str, str]]) -> None:
    models = ["openai/g4", "openai/gpt-oss"]
    model_labels = ["Gemma-4-31B", "GPT-OSS-120B"]
    adverse = ["Delayed", "ConflictingView"]

    off_rates = []
    on_rates = []
    overblock = []
    for model in models:
        off_num = sum(
            number(rows, model, regime, "off", "unsafe_executed_total")
            for regime in adverse
        )
        off_den = sum(
            number(rows, model, regime, "off", "oracle_unsafe_total")
            for regime in adverse
        )
        on_num = sum(
            number(rows, model, regime, "on", "unsafe_executed_total")
            for regime in adverse
        )
        on_den = sum(
            number(rows, model, regime, "on", "oracle_unsafe_total")
            for regime in adverse
        )
        off_rates.append(100 * off_num / off_den if off_den else 0)
        on_rates.append(100 * on_num / on_den if on_den else 0)
        overblock.append(number(rows, model, "FullSync", "on", "overblock_total"))

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    x = np.arange(len(models))
    width = 0.34
    axes[0].bar(x - width / 2, off_rates, width, color=RED, label="Gate OFF")
    axes[0].bar(x + width / 2, on_rates, width, color=GREEN, label="Gate ON")
    for index in range(len(models)):
        axes[0].text(index - width / 2, off_rates[index] + 2, f"{off_rates[index]:.0f}%", ha="center")
        axes[0].text(index + width / 2, on_rates[index] + 2, f"{on_rates[index]:.0f}%", ha="center")
    axes[0].set_xticks(x, model_labels)
    axes[0].set_ylim(0, 112)
    axes[0].set_ylabel("Oracle-unsafe writes executed (%)")
    axes[0].set_title("Adverse-Regime Unsafe Execution Rate")
    axes[0].legend(frameon=False)

    bars = axes[1].bar(model_labels, overblock, color=[BLUE, AMBER], width=0.55)
    for bar in bars:
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.25,
            str(int(bar.get_height())),
            ha="center",
        )
    axes[1].set_ylim(0, max(overblock) + 2.5)
    axes[1].set_ylabel("Conservative blocks in FullSync")
    axes[1].set_title("Clean-Control Overblock")
    fig.suptitle("Safety Benefit and Residual Conservatism", fontsize=18, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, "fig02_safety_rate_and_overblock.png")


def plot_fieldmask(rows: list[dict[str, str]]) -> None:
    models = ["gemma4", "gptoss"]
    model_labels = ["Gemma-4-31B", "GPT-OSS-120B"]
    regimes = ["FullSync", "Delayed", "RoleAwareFieldMask", "ConflictingView"]
    labels = ["FullSync", "Delayed", "FieldMask", "ConflictView"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4), sharey=True)
    for ax, model, model_label in zip(axes, models, model_labels):
        x = np.arange(len(regimes))
        width = 0.34
        off = [number(rows, model, regime, "off", "unsafe") for regime in regimes]
        on = [number(rows, model, regime, "on", "unsafe") for regime in regimes]
        off_bars = ax.bar(x - width / 2, off, width, color=RED, label="Gate OFF")
        on_bars = ax.bar(x + width / 2, on, width, color=GREEN, label="Gate ON")
        for group in (off_bars, on_bars):
            for bar in group:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.8,
                    str(int(bar.get_height())),
                    ha="center",
                    fontsize=9,
                )
        ax.set_xticks(x, labels, rotation=15)
        ax.set_title(model_label)
        ax.set_ylabel("Unsafe writes committed (n=50)")
        ax.set_ylim(0, max(off + on) + 7)
    axes[0].legend(frameon=False)
    fig.suptitle(
        "FieldMask Extension: CommitGate Blocks Blind and Stale Writes",
        fontsize=18,
        weight="bold",
    )
    fig.text(
        0.5,
        0.01,
        "V2 extension result. Interpret separately from the corrected oracle-based primary analysis.",
        ha="center",
        fontsize=9,
        color="#5F6B7A",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    save(fig, "fig03_fieldmask_extension.png")


def plot_token_cost(
    corrected: list[dict[str, str]],
    v2: list[dict[str, str]],
) -> None:
    corrected_models = ["openai/g4", "openai/gpt-oss"]
    labels = ["Gemma-4-31B", "GPT-OSS-120B"]
    corrected_regimes = ["FullSync", "Delayed", "ConflictingView"]
    v2_models = ["gemma4", "gptoss"]
    v2_regimes = ["FullSync", "Delayed", "RoleAwareFieldMask", "ConflictingView"]

    corrected_overhead = []
    v2_overhead = []
    for model in corrected_models:
        on = np.mean(
            [number(corrected, model, regime, "on", "tok_per_task") for regime in corrected_regimes]
        )
        off = np.mean(
            [number(corrected, model, regime, "off", "tok_per_task") for regime in corrected_regimes]
        )
        corrected_overhead.append(100 * (on / off - 1))
    for model in v2_models:
        on = np.mean([number(v2, model, regime, "on", "tok_per_task") for regime in v2_regimes])
        off = np.mean([number(v2, model, regime, "off", "tok_per_task") for regime in v2_regimes])
        v2_overhead.append(100 * (on / off - 1))

    fig, ax = plt.subplots(figsize=(9, 5.2))
    x = np.arange(len(labels))
    width = 0.34
    bars1 = ax.bar(x - width / 2, corrected_overhead, width, color=BLUE, label="Corrected primary")
    bars2 = ax.bar(x + width / 2, v2_overhead, width, color=AMBER, label="V2 with FieldMask")
    for group in (bars1, bars2):
        for bar in group:
            value = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + (0.25 if value >= 0 else -0.55),
                f"{value:+.1f}%",
                ha="center",
                fontsize=10,
            )
    ax.axhline(0, color=INK, lw=1)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Mean token overhead: gate ON vs OFF")
    ax.set_title("CommitGate Token-Cost Overhead")
    ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, "fig04_token_overhead.png")


def main() -> None:
    configure()
    corrected = read_csv(CORRECTED)
    v2 = read_csv(V2)
    plot_corrected_headline(corrected)
    plot_rates_and_overblock(corrected)
    plot_fieldmask(v2)
    plot_token_cost(corrected, v2)
    print(f"wrote 4 figures to {FIGURES}")


if __name__ == "__main__":
    main()
