#!/usr/bin/env python3
"""Generate preregistered task splits for RAVEL (Proposal §3.3).

Produces deterministic dev/pilot/held_out splits using a fixed seed.
Splits are derived from the included_tasks.csv produced by task_audit.py.

Outputs:
    artifacts/task_audit/splits_dev.csv
    artifacts/task_audit/splits_pilot.csv
    artifacts/task_audit/splits_held_out.csv
    artifacts/task_audit/split_manifest.json

Sizes per domain (§5.7):
    dev:      30 tasks (used for prompt/schema/logging debugging; NOT for test claims)
    pilot:    20 tasks (power analysis; frozen after pilot; NOT mixed into held-out)
    held_out: remainder, target ≥60 (telecom) or ≥50 (airline/retail after dev+pilot)

Usage:
    python scripts/generate_splits.py \
        --included-csv artifacts/task_audit/included_tasks.csv \
        --output-dir artifacts/task_audit \
        --seed 20260615
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path


SPLIT_SIZES = {
    "airline": {"dev": 10, "pilot": 10},
    "retail": {"dev": 14, "pilot": 14},
    "telecom": {"dev": 14, "pilot": 14},
}


def _sha256_csv(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_included(csv_path: Path) -> dict[str, list[dict]]:
    """Load included tasks grouped by domain."""
    by_domain: dict[str, list[dict]] = {}
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            domain = row["domain"]
            by_domain.setdefault(domain, []).append(row)
    return by_domain


def generate_splits(
    tasks: list[dict],
    domain: str,
    seed: int,
    dev_size: int,
    pilot_size: int,
) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    shuffled = list(tasks)
    rng.shuffle(shuffled)
    dev = shuffled[:dev_size]
    pilot = shuffled[dev_size: dev_size + pilot_size]
    held_out = shuffled[dev_size + pilot_size:]
    return {"dev": dev, "pilot": pilot, "held_out": held_out}


def main() -> int:
    parser = argparse.ArgumentParser(description="RAVEL split generation (§3.3)")
    parser.add_argument(
        "--included-csv",
        type=Path,
        default=Path("/home/xqin5/multiaiagent/artifacts/task_audit/included_tasks.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/home/xqin5/multiaiagent/artifacts/task_audit"),
    )
    parser.add_argument("--seed", type=int, default=20260615)
    args = parser.parse_args()

    if not args.included_csv.exists():
        print(f"ERROR: included_tasks.csv not found at {args.included_csv}", file=sys.stderr)
        print("Run scripts/task_audit.py first.", file=sys.stderr)
        return 1

    source_hash = _sha256_csv(args.included_csv)
    by_domain = load_included(args.included_csv)

    split_manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "source_csv": str(args.included_csv),
        "source_hash": source_hash,
        "domains": {},
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for split_name in ("dev", "pilot", "held_out"):
        all_split_rows: list[dict] = []
        for domain, tasks in by_domain.items():
            sizes = SPLIT_SIZES.get(domain, {"dev": 10, "pilot": 10})
            splits = generate_splits(
                tasks, domain, args.seed,
                dev_size=sizes["dev"],
                pilot_size=sizes["pilot"],
            )
            domain_tasks = splits[split_name]
            for row in domain_tasks:
                row["task_split"] = split_name
            all_split_rows.extend(domain_tasks)

            if split_name not in split_manifest["domains"].get(domain, {}):
                split_manifest["domains"].setdefault(domain, {})
            split_manifest["domains"][domain][split_name] = len(domain_tasks)

        out_path = args.output_dir / f"splits_{split_name}.csv"
        if all_split_rows:
            fieldnames = list(all_split_rows[0].keys())
            with out_path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_split_rows)
            print(f"  {split_name}: {len(all_split_rows)} tasks → {out_path}")
        else:
            print(f"  WARNING: no tasks for split {split_name}")

    manifest_path = args.output_dir / "split_manifest.json"
    with manifest_path.open("w") as fh:
        json.dump(split_manifest, fh, indent=2)
    print(f"\nSplit manifest: {manifest_path}")
    for domain, splits in split_manifest["domains"].items():
        print(f"  {domain}: dev={splits.get('dev',0)}, pilot={splits.get('pilot',0)}, held_out={splits.get('held_out',0)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
