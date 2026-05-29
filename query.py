#!/usr/bin/env python3
"""Query existing results for a given (target, ell, m) and optional q / sigma filters.
Prints every matching computed record sorted by CombinedBytes, flagging band membership
under [target+5, target+30]. Use --sigma as symmetric shorthand for sigma_1=sigma_2.
Pure analysis, no estimator."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
EXCLUDE = {"param_ideal.jsonl"}
LO, HI = 5, 30


def sigma_pair(inputs: dict) -> tuple[float | None, float | None]:
    sigma_1 = inputs.get("sigma_1")
    sigma_2 = inputs.get("sigma_2")
    legacy_sigma = inputs.get("sigma")
    if sigma_1 is None:
        sigma_1 = legacy_sigma
    if sigma_2 is None:
        sigma_2 = legacy_sigma
    return sigma_1, sigma_2


def load_all():
    seen = {}
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
    return list(seen.values())


def num(v):
    return v if isinstance(v, (int, float)) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--t", type=int, required=True)
    ap.add_argument("--ell", type=int)
    ap.add_argument("--m", type=int)
    ap.add_argument("--q", type=int, nargs="*")
    ap.add_argument("--sigma", type=float, nargs="*")
    ap.add_argument("--sigma-1", type=float, nargs="*", dest="sigma_1")
    ap.add_argument("--sigma-2", type=float, nargs="*", dest="sigma_2")
    ap.add_argument("--ah", type=int, nargs="*")
    ap.add_argument("--maxcomb", type=int, default=10**9)
    args = ap.parse_args()

    rows = []
    for rec in load_all():
        i = rec["inputs"]
        o = rec["outputs"]
        sigma_1, sigma_2 = sigma_pair(i)
        if i.get("target_security") != args.t:
            continue
        if args.ell is not None and i.get("ell") != args.ell:
            continue
        if args.m is not None and i.get("m") != args.m:
            continue
        if args.q and i.get("q") not in args.q:
            continue
        if args.sigma and not any(round(sigma_1, 6) == round(s, 6) and round(sigma_2, 6) == round(s, 6) for s in args.sigma):
            continue
        if args.sigma_1 and round(sigma_1, 6) not in [round(s, 6) for s in args.sigma_1]:
            continue
        if args.sigma_2 and round(sigma_2, 6) not in [round(s, 6) for s in args.sigma_2]:
            continue
        if args.ah and i.get("alpha_h") not in args.ah:
            continue
        if o.get("CombinedBytes", 10**9) > args.maxcomb:
            continue
        rows.append(rec)

    lo, hi = args.t + LO, args.t + HI
    rows.sort(key=lambda r: r["outputs"].get("CombinedBytes", 10**9))
    print(f"band [{lo},{hi}]  ({len(rows)} records)")
    for rec in rows:
        i, o = rec["inputs"], rec["outputs"]
        sigma_1, sigma_2 = sigma_pair(i)
        l, uf, suf = num(o.get("LWE_security_bit")), num(o.get("SIS_UF_security_bit")), num(o.get("SIS_sUF_security_bit"))
        def tag(v):
            return "in" if (v is not None and lo <= v <= hi) else ".."
        ga = "A" if (l and lo <= l <= hi and uf and lo <= uf <= hi) else " "
        gb = "B" if (l and lo <= l <= hi and suf and lo <= suf <= hi) else " "
        ls = f"{l:.2f}" if l is not None else "None"
        ufs = f"{uf:.2f}" if uf is not None else "None"
        sufs = f"{suf:.2f}" if suf is not None else "None"
        print(f"  [{ga}{gb}] Comb={o['CombinedBytes']:<6} q={i['q']:<10} σ1={sigma_1:<6} σ2={sigma_2:<6} a_h={i['alpha_h']:<5} "
              f"L={ls:>8}({tag(l)}) UF={ufs:>8}({tag(uf)}) sUF={sufs:>8}({tag(suf)}) Pk={o['PkBytes']} Sn={o['SignBytes']}")


if __name__ == "__main__":
    main()
