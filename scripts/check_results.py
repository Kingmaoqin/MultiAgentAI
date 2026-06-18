#!/usr/bin/env python3
"""Quick results aggregator. Run any time to see current experiment state."""
import json
import sys
from pathlib import Path

RESULTS_ROOT = Path("/home/xqin5/multiaiagent/results")
DOMAINS = ["airline", "retail", "telecom"]
REGIMES = ["FullSync", "Delayed", "FieldMask"]


def load_sims(path: Path) -> list[dict]:
    try:
        d = json.loads(path.read_text())
        return d.get("simulations") or []
    except Exception:
        return []


def sim_summary(sims: list[dict], n_expected: int) -> dict:
    rewards = [s.get("reward_info", {}) or {} for s in sims]
    r_vals = [r.get("reward") for r in rewards]
    valid = [r for r in r_vals if r is not None and str(r) != "None"]
    n_pass = sum(1 for r in valid if float(r) >= 1.0)
    mean_r = sum(float(r) for r in valid) / len(valid) if valid else None
    infra_err = sum(1 for s in sims if s.get("termination_reason") == "infrastructure_error")
    timeout_err = sum(1 for s in sims if s.get("termination_reason") == "max_steps")
    return {
        "n_done": len(sims),
        "n_expected": n_expected,
        "n_pass": n_pass,
        "n_valid": len(valid),
        "mean_reward": mean_r,
        "pass_rate": n_pass / n_expected if n_expected else None,
        "infra_errors": infra_err,
        "timeout_errors": timeout_err,
    }


def fmt_row(label: str, s: dict, log_tail: str = "") -> str:
    done = s["n_done"]
    exp = s["n_expected"]
    mr = s["mean_reward"]
    pr = s["pass_rate"]
    ie = s["infra_errors"]
    te = s["timeout_errors"]
    mr_str = f"{mr:.3f}" if mr is not None else " N/A "
    pr_str = f"{100*pr:.0f}%" if pr is not None else " N/A "
    errs = f" [infra={ie},tmout={te}]" if ie or te else ""
    return f"  {label:<40} {done:>3}/{exp:<3} {mr_str:<8} {pr_str:<8}{errs}"


print("\n" + "="*80)
print("EXPERIMENT RESULTS SNAPSHOT")
print("="*80)
print(f"  {'Condition':<40} {'Done':>7} {'Mean R':<8} {'Pass%':<8}")
print("-"*80)

# Dev baselines
n_expected = {"airline": 10, "retail": 14, "telecom": 14}
for domain in DOMAINS:
    rpath = RESULTS_ROOT / "dev_baseline" / domain / "results.json"
    sims = load_sims(rpath)
    s = sim_summary(sims, n_expected[domain])
    print(fmt_row(f"Baseline (llm_agent_gt) [{domain}]", s))

print()

# RAVEL experiment results
for domain in DOMAINS:
    for regime in REGIMES:
        regime_dir = RESULTS_ROOT / "ravel_exp" / domain / f"ravel_{regime.lower()}"
        rpath = regime_dir / "results.json"
        sims = load_sims(rpath)
        s = sim_summary(sims, n_expected[domain])
        label = f"RAVEL-{regime} [{domain}]"
        print(fmt_row(label, s))
    print()

print("="*80)

# Quick log tail for in-progress runs
print("\nIN-PROGRESS LOGS (last status line):")
log_files = list((RESULTS_ROOT / "dev_baseline").rglob("run.log")) + \
            list((RESULTS_ROOT / "ravel_exp").glob("*.log"))
for lf in sorted(log_files):
    try:
        lines = lf.read_text().splitlines()
        status_lines = [l for l in lines[-20:] if "Status:" in l or "complete" in l.lower()]
        if status_lines:
            last = status_lines[-1]
            print(f"  {lf.parent.name}/{lf.name}: {last[:100]}")
    except Exception:
        pass
