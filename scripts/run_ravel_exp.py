#!/usr/bin/env python3
"""RAVEL paired experiment runner.

Registers the RAVEL agent with the tau2 registry and runs paired
baseline-vs-RAVEL experiments on the frozen dev/pilot split.

Usage:
    cd /home/xqin5/multiaiagent/worktrees/tau2-clean
    uv run python /home/xqin5/multiaiagent/scripts/run_ravel_exp.py \
        --domain airline \
        --split dev \
        --regimes FullSync Delayed FieldMask \
        --agent-type ravel \
        --max-concurrency 2 \
        --output-dir /home/xqin5/multiaiagent/results/ravel_exp

For baseline (no-RAVEL):
    uv run python /home/xqin5/multiaiagent/scripts/run_ravel_exp.py \
        --domain airline --split dev --agent-type baseline
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make ravel_core importable
# ---------------------------------------------------------------------------
RAVEL_SRC = Path(__file__).parent.parent / "src"
if str(RAVEL_SRC) not in sys.path:
    sys.path.insert(0, str(RAVEL_SRC))

# ---------------------------------------------------------------------------
# tau2 imports (must be in tau2-clean worktree venv)
# ---------------------------------------------------------------------------
from tau2.data_model.simulation import TextRunConfig
from tau2.registry import registry
from tau2.runner.batch import run_domain

# ---------------------------------------------------------------------------
# RAVEL imports
# ---------------------------------------------------------------------------
from ravel_core.ravel_agent import create_ravel_agent, DOMAIN_WRITE_TOOLS, RAVELAgent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPLITS_DIR = Path("/home/xqin5/multiaiagent/artifacts/task_audit")
RESULTS_BASE = Path("/home/xqin5/multiaiagent/results")
MODEL_API_BASE = "http://127.0.0.1:8190/v1"
MODEL_NAME = "openai/q"
MODEL_ARGS = {"temperature": 0.0, "api_base": MODEL_API_BASE, "api_key": "EMPTY"}

# These are overridden by --model-api-base / --model-name at runtime
_RUNTIME_API_BASE: str | None = None
_RUNTIME_MODEL_NAME: str | None = None

REGIMES = ["FullSync", "Delayed", "FieldMask", "ConflictingView"]


def load_split_tasks(domain: str, split: str) -> list[str]:
    """Load task IDs from the frozen split CSV."""
    split_file = SPLITS_DIR / f"splits_{split}.csv"
    if not split_file.exists():
        print(f"ERROR: split file not found: {split_file}", file=sys.stderr)
        sys.exit(1)
    with split_file.open() as f:
        rows = list(csv.DictReader(f))
    return [r["task_id"] for r in rows if r["domain"] == domain]


def register_ravel_agents():
    """Register all RAVEL agent variants with the global tau2 registry."""
    if "ravel_agent" in registry._agent_factories:
        return  # already registered

    for regime in REGIMES:
        name = f"ravel_{regime.lower()}"
        def _make_factory(r=regime):
            def factory(tools, domain_policy, **kwargs):
                kwargs["regime"] = r
                return create_ravel_agent(tools, domain_policy, **kwargs)
            return factory
        registry.register_agent_factory(_make_factory(), name)

    # Also register the generic ravel_agent (uses regime from kwargs)
    registry.register_agent_factory(create_ravel_agent, "ravel_agent")
    print("Registered RAVEL agent factories: " +
          ", ".join(["ravel_agent"] + [f"ravel_{r.lower()}" for r in REGIMES]))


def run_experiment(
    domain: str,
    task_ids: list[str],
    agent_name: str,
    regime: str,
    output_dir: Path,
    max_concurrency: int,
    max_steps: int,
    timeout: int,
    seed: int,
    agent_extra_args: dict,
):
    """Run one agent×regime experiment leg."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # RAVEL config embedded in llm_args_agent so factory can extract it
    eff_api_base = _RUNTIME_API_BASE or MODEL_API_BASE
    eff_model_name = _RUNTIME_MODEL_NAME or MODEL_NAME
    eff_model_args = {"temperature": 0.0, "api_base": eff_api_base, "api_key": "EMPTY"}
    agent_llm_args = {**eff_model_args, **agent_extra_args}

    # Telecom mms tasks live in the 'full' split; base split only has 114 tasks
    task_split = "full" if domain == "telecom" else "base"

    config = TextRunConfig(
        domain=domain,
        agent=agent_name,
        user="user_simulator",
        llm_agent=eff_model_name,
        llm_args_agent=agent_llm_args,
        llm_user=eff_model_name,
        llm_args_user=eff_model_args,
        max_concurrency=max_concurrency,
        max_steps=max_steps,
        timeout=timeout,
        seed=seed,
        save_to=str(output_dir),
        log_level="WARNING",
        num_trials=1,
        task_ids=task_ids,
        task_split_name=task_split,
        auto_resume=True,
    )

    print(f"\n{'='*60}")
    print(f"  Domain: {domain}  Agent: {agent_name}  Regime: {regime}")
    print(f"  Tasks: {len(task_ids)}  MaxSteps: {max_steps}  Seed: {seed}")
    print(f"  Output: {output_dir}")
    print(f"{'='*60}")

    t0 = time.time()
    results = run_domain(config)
    elapsed = time.time() - t0

    # Summarise results
    sims = getattr(results, "simulations", None) or []
    rewards = [s.reward_info.reward if s.reward_info else None for s in sims]
    valid_rewards = [r for r in rewards if r is not None]
    mean_r = sum(valid_rewards) / len(valid_rewards) if valid_rewards else None
    n_pass = sum(1 for r in valid_rewards if r >= 1.0)

    summary = {
        "domain": domain,
        "agent": agent_name,
        "regime": regime,
        "n_tasks": len(task_ids),
        "n_sims": len(sims),
        "n_valid": len(valid_rewards),
        "n_pass": n_pass,
        "pass_rate": n_pass / len(task_ids) if task_ids else None,
        "mean_reward": mean_r,
        "elapsed_s": round(elapsed, 1),
        "task_ids": task_ids,
        "per_task": [
            {
                "task_id": s.task_id,
                "reward": s.reward_info.reward if s.reward_info else None,
                "termination": str(s.termination_reason),
                "duration": round(s.duration or 0, 1),
            }
            for s in sims
        ],
    }

    summary_path = output_dir / "exp_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    mean_r_str = f"{mean_r:.3f}" if mean_r is not None else "N/A"
    print(f"\nResult: pass={n_pass}/{len(task_ids)} mean_reward={mean_r_str} ({elapsed:.0f}s)")
    return summary


def print_comparison(baseline_summary: dict, ravel_summaries: list[dict]):
    """Print baseline vs RAVEL comparison table."""
    print("\n" + "="*70)
    print("EXPERIMENT COMPARISON SUMMARY")
    print("="*70)
    print(f"{'Condition':<30} {'Pass':<8} {'Mean R':<10} {'Pass%':<8}")
    print("-"*70)

    def fmt(s):
        pr = s.get("pass_rate")
        mr = s.get("mean_reward")
        n = s.get("n_tasks", 0)
        np_ = s.get("n_pass", 0)
        return (
            f"{np_}/{n}" if n else "?",
            f"{mr:.3f}" if mr is not None else "N/A",
            f"{100*pr:.1f}%" if pr is not None else "N/A",
        )

    label = f"Baseline ({baseline_summary.get('domain')})"
    p, m, pct = fmt(baseline_summary)
    print(f"{label:<30} {p:<8} {m:<10} {pct:<8}")

    for s in ravel_summaries:
        label = f"RAVEL-{s.get('regime')} ({s.get('domain')})"
        p, m, pct = fmt(s)
        print(f"{label:<30} {p:<8} {m:<10} {pct:<8}")
    print("="*70)


def main():
    parser = argparse.ArgumentParser(description="RAVEL paired experiment runner")
    parser.add_argument("--domain", required=True, choices=["airline", "retail", "telecom"])
    parser.add_argument("--split", default="dev", choices=["dev", "pilot", "held_out"])
    parser.add_argument("--regimes", nargs="+", default=["FullSync"],
                        choices=REGIMES)
    parser.add_argument("--agent-type", default="ravel",
                        choices=["baseline", "ravel"],
                        help="baseline=llm_agent (no RAVEL), ravel=RAVEL variants")
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=480)
    parser.add_argument("--seed", type=int, default=20260615)
    parser.add_argument("--output-dir",
                        default="/home/xqin5/multiaiagent/results/ravel_exp")
    parser.add_argument("--delay", type=int, default=1, help="Delayed regime delay steps")
    parser.add_argument("--mask-fraction", type=float, default=0.3,
                        help="FieldMask regime mask fraction")
    parser.add_argument("--gate-disabled", action="store_true",
                        help="Disable CommitGate (evidence tracking only)")
    parser.add_argument("--model-api-base", default=None,
                        help="Override MODEL_API_BASE (e.g. http://127.0.0.1:8191/v1)")
    parser.add_argument("--model-name", default=None,
                        help="Override MODEL_NAME (e.g. openai/llama3)")
    args = parser.parse_args()

    # Apply runtime model overrides
    global _RUNTIME_API_BASE, _RUNTIME_MODEL_NAME
    if args.model_api_base:
        _RUNTIME_API_BASE = args.model_api_base
    if args.model_name:
        _RUNTIME_MODEL_NAME = args.model_name

    output_root = Path(args.output_dir)

    # Load frozen task split
    task_ids = load_split_tasks(args.domain, args.split)
    print(f"Loaded {len(task_ids)} {args.domain} tasks from {args.split} split")

    if not task_ids:
        print("ERROR: No tasks found for this domain/split combination", file=sys.stderr)
        sys.exit(1)

    # Register RAVEL agents
    register_ravel_agents()

    summaries = []

    if args.agent_type == "baseline":
        # Standard llm_agent (no GT hints, no RAVEL)
        out_dir = output_root / args.domain / "baseline_llm_agent"
        s = run_experiment(
            domain=args.domain,
            task_ids=task_ids,
            agent_name="llm_agent",
            regime="FullSync",
            output_dir=out_dir,
            max_concurrency=args.max_concurrency,
            max_steps=args.max_steps,
            timeout=args.timeout,
            seed=args.seed,
            agent_extra_args={},
        )
        summaries.append(s)

    else:
        # RAVEL variants per regime
        gate_enabled = not args.gate_disabled
        for regime in args.regimes:
            agent_name = f"ravel_{regime.lower()}"
            extra = {
                "domain": args.domain,
                "regime": regime,
                "delay": args.delay,
                "mask_fraction": args.mask_fraction,
                "gate_enabled": gate_enabled,
                "seed": args.seed,
            }
            out_dir = output_root / args.domain / f"ravel_{regime.lower()}"
            s = run_experiment(
                domain=args.domain,
                task_ids=task_ids,
                agent_name=agent_name,
                regime=regime,
                output_dir=out_dir,
                max_concurrency=args.max_concurrency,
                max_steps=args.max_steps,
                timeout=args.timeout,
                seed=args.seed,
                agent_extra_args=extra,
            )
            summaries.append(s)

    # Save all summaries
    all_summary_path = output_root / args.domain / "all_summaries.json"
    all_summary_path.parent.mkdir(parents=True, exist_ok=True)
    all_summary_path.write_text(json.dumps(summaries, indent=2))
    print(f"\nAll summaries → {all_summary_path}")


if __name__ == "__main__":
    main()
