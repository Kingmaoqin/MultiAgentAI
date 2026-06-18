#!/usr/bin/env python3
"""Full multi-agent RAVEL experiment runner (post-approval).

Runs the RAVELTeamAgent over a full dev-split domain for one regime.
Architecture is APPROVED (architecture_acceptance.json overall_status=PASS); this
is the fuller experiment beyond the gated 2-task pilot.

Usage (from tau2-clean worktree, uv env):
    uv run python scripts/run_mas_full.py --domain airline --regime FullSync \
        --model-api-base http://127.0.0.1:8005/v1 --model-name openai/g4 \
        --output-dir results/mas_experiment/gemma4
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/xqin5/multiaiagent/src")

from tau2.data_model.simulation import TextRunConfig
from tau2.registry import registry
from tau2.runner.batch import run_domain

from ravel_mas.team_agent import create_ravel_team_agent

SPLITS = Path("/home/xqin5/multiaiagent/artifacts/task_audit/splits_dev.csv")


def load_tasks(domain: str) -> list[str]:
    rows = list(csv.DictReader(SPLITS.open()))
    return [r["task_id"] for r in rows if r["domain"] == domain]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, choices=["airline", "retail", "telecom"])
    ap.add_argument("--regime", required=True,
                    choices=["FullSync", "Delayed", "FieldMask",
                             "RoleAwareFieldMask", "ConflictingView"])
    ap.add_argument("--model-api-base", required=True)
    ap.add_argument("--model-name", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--max-concurrency", type=int, default=1)
    args = ap.parse_args()

    regime = "RoleAwareFieldMask" if args.regime == "FieldMask" else args.regime
    tasks = load_tasks(args.domain)
    agent_name = f"ravel_team_{args.domain}_{regime.lower()}"

    def factory(tools, domain_policy, **kwargs):
        kwargs["regime"] = regime
        return create_ravel_team_agent(tools, domain_policy, **kwargs)
    registry.register_agent_factory(factory, agent_name)

    out_dir = Path(args.output_dir) / args.domain / regime.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    margs = {"temperature": 0.0, "api_base": args.model_api_base, "api_key": "EMPTY"}
    agent_args = {**margs, "domain": args.domain, "regime": regime}

    split = "full" if args.domain == "telecom" else "base"
    config = TextRunConfig(
        domain=args.domain, agent=agent_name, user="user_simulator",
        llm_agent=args.model_name, llm_args_agent=agent_args,
        llm_user=args.model_name, llm_args_user=margs,
        max_concurrency=args.max_concurrency, max_steps=args.max_steps,
        timeout=args.timeout, seed=20260615, save_to=str(out_dir),
        log_level="WARNING", num_trials=1, task_ids=tasks,
        task_split_name=split, auto_resume=True,
    )

    print(f"\n=== MAS {args.model_name} {args.domain} {regime} "
          f"({len(tasks)} tasks, max_steps={args.max_steps}) ===", flush=True)
    t0 = time.time()
    results = run_domain(config)
    elapsed = time.time() - t0

    sims = getattr(results, "simulations", None) or []
    rewards = [s.reward_info.reward if s.reward_info else None for s in sims]
    valid = [r for r in rewards if r is not None]
    n_pass = sum(1 for r in valid if r >= 1.0)
    summary = {
        "model": args.model_name, "domain": args.domain, "regime": regime,
        "n_tasks": len(tasks), "n_sims": len(sims), "n_valid": len(valid),
        "n_pass": n_pass, "pass_rate": (n_pass / len(tasks)) if tasks else None,
        "elapsed_s": round(elapsed, 1),
        "per_task": [{
            "task_id": s.task_id,
            "reward": s.reward_info.reward if s.reward_info else None,
            "termination": str(s.termination_reason),
            "duration": round(s.duration or 0, 1),
        } for s in sims],
    }
    (out_dir / "exp_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"RESULT {args.domain}/{regime}: pass={n_pass}/{len(tasks)} ({elapsed:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
