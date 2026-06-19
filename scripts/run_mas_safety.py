#!/usr/bin/env python3
"""Write-safety experiment runner (RAVEL's core thesis).

Runs the multi-agent RAVEL system over a full domain task set for one
(regime, gate) condition, under Stage-A controlled staleness perturbation, and
records write-safety metrics + task pass rate.

Hypothesis: under adverse regimes (Delayed/ConflictingView) the deterministic
CommitService (gate ON) blocks writes proposed on stale evidence, so
unsafe_committed ~ 0; with the gate OFF those writes execute (unsafe_committed > 0).
FullSync (no perturbation) is the control: ~0 staleness either way.

Usage (tau2-clean worktree, uv):
  uv run python scripts/run_mas_safety.py --domain airline --regime ConflictingView \
      --gate on --model-api-base http://127.0.0.1:8005/v1 --model-name openai/g4 \
      --output-dir results/mas_safety/gemma4 --n-tasks 50
"""
from __future__ import annotations

import argparse, json, glob, sys, time
from pathlib import Path

sys.path.insert(0, "/home/xqin5/multiaiagent/src")
from tau2.data_model.simulation import TextRunConfig
from tau2.registry import registry
from tau2.runner.batch import run_domain
from ravel_mas.team_agent import create_ravel_team_agent

TAU2_DATA = Path("/home/xqin5/multiaiagent/worktrees/tau2-clean/data/tau2/domains")


def load_tasks(domain: str, n: int) -> list[str]:
    d = json.load(open(TAU2_DATA / domain / "tasks.json"))
    ids = [t["id"] for t in d]
    return ids[:n] if n > 0 else ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--regime", required=True,
                    choices=["FullSync", "Delayed", "ConflictingView", "RoleAwareFieldMask"])
    ap.add_argument("--gate", required=True, choices=["on", "off"])
    ap.add_argument("--model-api-base", required=True)
    ap.add_argument("--model-name", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--n-tasks", type=int, default=50)
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--max-concurrency", type=int, default=4)
    args = ap.parse_args()

    gate_on = args.gate == "on"
    tasks = load_tasks(args.domain, args.n_tasks)
    cond = f"{args.domain}_{args.regime.lower()}_gate{args.gate}"
    out_dir = Path(args.output_dir) / cond
    out_dir.mkdir(parents=True, exist_ok=True)
    agent_name = f"rt_{cond}"

    def factory(tools, domain_policy, **kw):
        kw["regime"] = args.regime
        return create_ravel_team_agent(tools, domain_policy, **kw)
    registry.register_agent_factory(factory, agent_name)

    margs = {"temperature": 0.0, "api_base": args.model_api_base, "api_key": "EMPTY"}
    agent_args = {**margs, "domain": args.domain, "regime": args.regime,
                  "gate_enabled": gate_on, "trace_dir": str(out_dir)}

    cfg = TextRunConfig(
        domain=args.domain, agent=agent_name, user="user_simulator",
        llm_agent=args.model_name, llm_args_agent=agent_args,
        llm_user=args.model_name, llm_args_user=margs,
        max_concurrency=args.max_concurrency, max_steps=args.max_steps,
        timeout=args.timeout, seed=20260615, save_to=str(out_dir),
        log_level="WARNING", num_trials=1, task_ids=tasks,
        task_split_name="base", auto_resume=True,
    )
    print(f"\n=== SAFETY {args.model_name} {cond} ({len(tasks)} tasks) ===", flush=True)
    t0 = time.time()
    results = run_domain(cfg)
    elapsed = time.time() - t0

    sims = getattr(results, "simulations", None) or []
    n_pass = sum(1 for s in sims if s.reward_info and s.reward_info.reward and s.reward_info.reward >= 1.0)

    # aggregate per-task safety files
    agg = {"write_attempts": 0, "stale_attempts": 0, "conflict_attempts": 0,
           "blind_attempts": 0, "blocked": 0, "committed": 0, "unsafe_committed": 0}
    tok = {"total_in": 0, "total_out": 0, "total_tokens": 0, "worker_calls": 0, "n_turns": 0}
    n_safety = 0
    for f in glob.glob(str(out_dir / "safety_*.json")):
        d = json.load(open(f)); n_safety += 1
        for k in agg:
            agg[k] += d.get(k, 0)
        t = d.get("tokens", {})
        for k in tok:
            tok[k] += t.get(k, 0)
    tok["tokens_per_task"] = round(tok["total_tokens"] / n_safety, 1) if n_safety else 0

    summary = {
        "model": args.model_name, "domain": args.domain, "regime": args.regime,
        "gate": args.gate, "n_tasks": len(tasks), "n_sims": len(sims),
        "n_pass": n_pass, "pass_rate": n_pass / len(tasks) if tasks else None,
        "n_safety_files": n_safety, "safety": agg, "tokens": tok,
        "unsafe_committed_rate": (agg["unsafe_committed"] / agg["write_attempts"]
                                  if agg["write_attempts"] else 0.0),
        "blocked_rate": (agg["blocked"] / agg["write_attempts"]
                         if agg["write_attempts"] else 0.0),
        "elapsed_s": round(elapsed, 1),
    }
    (out_dir / "condition_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"RESULT {cond}: pass={n_pass}/{len(tasks)} writes={agg['write_attempts']} "
          f"stale={agg['stale_attempts']} blind={agg['blind_attempts']} "
          f"blocked={agg['blocked']} unsafe={agg['unsafe_committed']} "
          f"tok/task={tok['tokens_per_task']} ({elapsed:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
