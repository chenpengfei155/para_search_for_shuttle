#!/usr/bin/env python3
"""Re-mine ALL existing results/*.jsonl under a configurable acceptance band.

User's current goal: band = [target+5, target+30]  (was +12 in extract_ideal).
Two tracks reported per (target, goal):
    - general: sigma_1 and sigma_2 on the 0.05 grid, min(sigma_1, sigma_2) >= 0.5
    - hard: sigma_1 and sigma_2 on the 0.05 grid, min(sigma_1, sigma_2) >= 1.0

Pure analysis of existing computed records; no estimator calls.
"""
from __future__ import annotations

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
EXCLUDE = {"param_ideal.jsonl"}  # param_ideal is a tagged subset; everything else is raw/union

LO = 5
SIGMA_STEP = 0.05


def sigma_pair(inputs: dict) -> tuple[float | None, float | None]:
    sigma_1 = inputs.get("sigma_1")
    sigma_2 = inputs.get("sigma_2")
    legacy_sigma = inputs.get("sigma")
    if sigma_1 is None:
        sigma_1 = legacy_sigma
    if sigma_2 is None:
        sigma_2 = legacy_sigma
    return sigma_1, sigma_2


def sigma_on_grid(v) -> bool:
    if not isinstance(v, (int, float)):
        return False
    s = v / SIGMA_STEP
    return abs(s - round(s)) <= 1e-9


def load_all() -> dict[tuple, dict]:
    """Union of every result record, deduped by exact input key."""
    seen: dict[tuple, dict] = {}
    for path in sorted(RESULTS_DIR.glob("*.jsonl")):
        if path.name in EXCLUDE:
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
                i = rec.get("inputs") or {}
                o = rec.get("outputs")
                if o is None:
                    continue
                sigma_1, sigma_2 = sigma_pair(i)
                key = (i.get("n"), i.get("q"), i.get("ell"), i.get("m"),
                       sigma_1, sigma_2, i.get("alpha_h"))
                if None in key:
                    continue
                seen[key] = rec
    return seen


def best_under(records, hi_off: int, sigma_min: float):
    """Return {(target, goal): best_record} minimizing CombinedBytes."""
    best: dict[tuple, dict] = {}
    for rec in records:
        i = rec["inputs"]
        o = rec["outputs"]
        t = i.get("target_security")
        sigma_1, sigma_2 = sigma_pair(i)
        if (
            t is None
            or not sigma_on_grid(sigma_1)
            or not sigma_on_grid(sigma_2)
            or min(sigma_1, sigma_2) < sigma_min - 1e-9
        ):
            continue
        lo, hi = t + LO, t + hi_off
        l = o.get("LWE_security_bit")
        uf = o.get("SIS_UF_security_bit")
        suf = o.get("SIS_sUF_security_bit")
        cb = o.get("CombinedBytes")
        if cb is None or l is None:
            continue

        def inb(v):
            return isinstance(v, (int, float)) and lo <= v <= hi

        if inb(l) and inb(uf):
            k = (t, "A")
            if k not in best or cb < best[k]["outputs"]["CombinedBytes"]:
                best[k] = rec
        if inb(l) and inb(suf):
            k = (t, "B")
            if k not in best or cb < best[k]["outputs"]["CombinedBytes"]:
                best[k] = rec
    return best


def fmt(rec):
    i = rec["inputs"]
    o = rec["outputs"]
    sigma_1, sigma_2 = sigma_pair(i)
    return (f"Comb={o['CombinedBytes']:<6} q={i['q']:<10} ell={i['ell']} m={i['m']} "
            f"sigma_1={sigma_1:<6} sigma_2={sigma_2:<6} a_h={i['alpha_h']:<5} "
            f"L={o['LWE_security_bit']:.2f} UF={o['SIS_UF_security_bit']:.2f} "
            f"sUF={o['SIS_sUF_security_bit']:.2f} Pk={o['PkBytes']} Sign={o['SignBytes']}")


def main():
    recs = list(load_all().values())
    print(f"loaded {len(recs)} unique computed records\n")

    for hi_off in (12, 30):
        print(f"================ BAND [+5, +{hi_off}] ================")
        for sigma_min, label in ((0.5, "min(sigma_1,sigma_2)>=0.5 (general)"), (1.0, "min(sigma_1,sigma_2)>=1.0 (hard)")):
            print(f"  --- {label} ---")
            best = best_under(recs, hi_off, sigma_min)
            for t in (128, 256, 512):
                for g in ("A", "B"):
                    k = (t, g)
                    if k in best:
                        print(f"    t={t} Goal {g}: {fmt(best[k])}")
                    else:
                        print(f"    t={t} Goal {g}: (none)")
        print()


if __name__ == "__main__":
    main()
