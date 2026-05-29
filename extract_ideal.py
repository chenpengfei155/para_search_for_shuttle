#!/usr/bin/env python3
"""Scan all results/*.jsonl, keep records matching Goal A (LWE & SIS_UF in band)
or Goal B (LWE & SIS_sUF in band), collapse repeated sigma plateaus, and write
to results/param_ideal.jsonl. Adds a `goal` tag to each record."""
from __future__ import annotations

import json
from pathlib import Path

from result_dedup import pick_plateau_representatives, record_key

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
OUT_PATH = RESULTS_DIR / "param_ideal.jsonl"
SOURCE_GLOB = "*.jsonl"
EXCLUDE_NAMES = {"param_all.jsonl", "param_ideal.jsonl"}

GOAL_LO_OFFSET = 5
GOAL_HI_OFFSET = 30  # acceptance band upper edge (user goal: lambda+5 <= sec <= lambda+30)
SIGMA_MIN_STEP = 0.05


def in_band(value, lo, hi):
    return value is not None and lo <= value <= hi


def sigma_on_grid(value: object, step: float = SIGMA_MIN_STEP) -> bool:
    if not isinstance(value, (int, float)):
        return False
    scaled = value / step
    return abs(scaled - round(scaled)) <= 1e-9


def main():
    if not RESULTS_DIR.exists():
        raise SystemExit(f"missing {RESULTS_DIR}")

    seen: dict[tuple, dict] = {}  # exact input key -> enriched record

    for path in sorted(RESULTS_DIR.glob(SOURCE_GLOB)):
        if path.name in EXCLUDE_NAMES:
            continue
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "outputs" not in rec:
                    continue
                i = rec.get("inputs") or {}
                o = rec["outputs"]
                if not sigma_on_grid(i.get("sigma")):
                    continue
                t = i.get("target_security")
                if t is None:
                    continue
                lo, hi = t + GOAL_LO_OFFSET, t + GOAL_HI_OFFSET
                l = o.get("LWE_security_bit")
                uf = o.get("SIS_UF_security_bit")
                suf = o.get("SIS_sUF_security_bit")
                goals = []
                if in_band(l, lo, hi) and in_band(uf, lo, hi):
                    goals.append("UF")
                if in_band(l, lo, hi) and in_band(suf, lo, hi):
                    goals.append("sUF")
                if not goals:
                    continue

                k = record_key(rec)
                if k is None:
                    continue
                if k in seen:
                    # merge goal tags
                    existing = set(seen[k].get("goals", []))
                    existing.update(goals)
                    seen[k]["goals"] = sorted(existing)
                    continue
                enriched = dict(rec)
                enriched["goals"] = goals
                enriched["source"] = path.name
                seen[k] = enriched

    collapsed_records = pick_plateau_representatives(list(seen.values()))
    out_records = sorted(
        collapsed_records,
        key=lambda r: (r["inputs"]["target_security"], r["inputs"]["n"],
                       r["inputs"]["ell"], r["inputs"]["m"],
                       r["inputs"]["q"], r["inputs"]["sigma"],
                       r["inputs"]["alpha_h"]),
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for r in out_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # summary
    from collections import Counter
    by_target_goal = Counter()
    for r in out_records:
        t = r["inputs"]["target_security"]
        for g in r["goals"]:
            by_target_goal[(t, g)] += 1
    print(f"wrote {len(out_records)} unique ideal params -> {OUT_PATH}")
    for (t, g), n in sorted(by_target_goal.items()):
        print(f"  target={t} Goal {g}: {n}")


if __name__ == "__main__":
    main()
