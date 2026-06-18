#!/usr/bin/env python3
"""Gated §16 pilot — RAVELTeamAgent on real tau2 with a real model.

Limits (Contract §16): 1 model, 2 tasks, 2 conditions (FullSync + ConflictingView),
<=2 reps. Run ONLY after architecture tests + mutation tests + both reviews APPROVED.

Usage (from the tau2-clean worktree, uv env):
    uv run python /home/xqin5/multiaiagent/scripts/mas_pilot.py \
        --model-api-base http://127.0.0.1:8005/v1 --model-name openai/g4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAVEL_SRC = Path("/home/xqin5/multiaiagent/src")
sys.path.insert(0, str(RAVEL_SRC))

from tau2.data_model.simulation import TextRunConfig
from tau2.registry import registry
from tau2.runner.batch import run_domain

from ravel_mas.team_agent import create_ravel_team_agent

PILOT_TASKS = ["32", "7"]          # 2 airline dev tasks
CONDITIONS = ["FullSync", "ConflictingView"]
OUT = Path("/home/xqin5/multiaiagent/results/mas_pilot")


def register(regime: str, name: str):
    def factory(tools, domain_policy, **kwargs):
        kwargs["regime"] = regime
        return create_ravel_team_agent(tools, domain_policy, **kwargs)
    registry.register_agent_factory(factory, name)


def run_condition(regime: str, api_base: str, model_name: str,
                  max_steps: int, timeout: int) -> dict:
    agent_name = f"ravel_team_{regime.lower()}"
    register(regime, agent_name)
    out_dir = OUT / regime.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    model_args = {"temperature": 0.0, "api_base": api_base, "api_key": "EMPTY"}
    agent_args = {**model_args, "domain": "airline", "regime": regime}

    config = TextRunConfig(
        domain="airline", agent=agent_name, user="user_simulator",
        llm_agent=model_name, llm_args_agent=agent_args,
        llm_user=model_name, llm_args_user=model_args,
        max_concurrency=1, max_steps=max_steps, timeout=timeout,
        seed=20260615, save_to=str(out_dir), log_level="WARNING",
        num_trials=1, task_ids=PILOT_TASKS, task_split_name="base",
        auto_resume=True,
    )
    t0 = time.time()
    results = run_domain(config)
    elapsed = time.time() - t0
    sims = getattr(results, "simulations", None) or []
    per_task = []
    for s in sims:
        per_task.append({
            "task_id": s.task_id,
            "reward": s.reward_info.reward if s.reward_info else None,
            "termination": str(s.termination_reason),
            "duration": round(s.duration or 0, 1),
        })
    summary = {
        "regime": regime, "agent": agent_name, "n_tasks": len(PILOT_TASKS),
        "elapsed_s": round(elapsed, 1), "per_task": per_task,
    }
    (out_dir / "pilot_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-api-base", required=True)
    ap.add_argument("--model-name", required=True)
    ap.add_argument("--max-steps", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for regime in CONDITIONS:
        print(f"\n=== PILOT condition: {regime} ===")
        results[regime] = run_condition(
            regime, args.model_api_base, args.model_name,
            args.max_steps, args.timeout)
        print(json.dumps(results[regime], indent=2))

    (OUT / "pilot_all.json").write_text(json.dumps(results, indent=2))
    print("\n=== PILOT COMPLETE ===")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
