#!/usr/bin/env python3
"""Analysis helper: scan jsonl, find records in target+5..target+12 bands per goal."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(path):
    recs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="one or more jsonl files")
    ap.add_argument("--show", type=int, default=6, help="rows to show per category")
    args = ap.parse_args()

    recs = []
    for p in args.paths:
        recs.extend(load(p))

    print(f"loaded {len(recs)} records from {len(args.paths)} file(s)")

    by_target = defaultdict(list)
    for r in recs:
        if "outputs" not in r:
            continue
        by_target[r["inputs"]["target_security"]].append(r)

    for t in sorted(by_target):
        rs = by_target[t]
        lo, hi = t + 5, t + 12
        print(f"\n{'='*68}\ntarget={t}  [{lo}..{hi}]  records: {len(rs)}")

        # categorize
        in_uf, in_suf = [], []
        for r in rs:
            o = r["outputs"]
            l = o.get("LWE_security_bit") or 0
            uf = o.get("SIS_UF_security_bit") or 0
            suf = o.get("SIS_sUF_security_bit") or 0
            lwe_ok = lo <= l <= hi
            if lwe_ok and lo <= uf <= hi:
                in_uf.append(r)
            if lwe_ok and lo <= suf <= hi:
                in_suf.append(r)

        print(f"  UF goal hits (LWE+SIS_UF both in band): {len(in_uf)}")
        print(f"  sUF goal hits (LWE+SIS_sUF both in band): {len(in_suf)}")

        def show(category, items, sort_key=None):
            print(f"\n  -- {category} --")
            if not items:
                # show closest near-misses by some heuristic
                pass
            for r in items[: args.show]:
                i, o = r["inputs"], r["outputs"]
                print(
                    f"    n={i['n']:>4} q={i['q']:>7} ell={i['ell']} m={i['m']} sigma={i['sigma']:.2f} alpha_h={i['alpha_h']:>4}  "
                    f"| LWE={o['LWE_security_bit']:6.2f} UF={o['SIS_UF_security_bit']:6.2f} sUF={o['SIS_sUF_security_bit']:6.2f}  "
                    f"| Pk={o.get('PkBytes',0)} Sign={o.get('SignBytes',0)}"
                )

        show("UF in band", in_uf)
        show("sUF in band", in_suf)

        # gap analysis: nearest to each goal when no hits
        if not in_uf or not in_suf:
            print("\n  -- gap analysis --")
            target_center = (lo + hi) / 2

            def dist_uf(r):
                o = r["outputs"]
                l = o.get("LWE_security_bit") or 0
                uf = o.get("SIS_UF_security_bit") or 0
                # max distance from band on either axis
                return max(0, abs(l - target_center) - 3.5) + max(0, abs(uf - target_center) - 3.5)

            def dist_suf(r):
                o = r["outputs"]
                l = o.get("LWE_security_bit") or 0
                suf = o.get("SIS_sUF_security_bit") or 0
                return max(0, abs(l - target_center) - 3.5) + max(0, abs(suf - target_center) - 3.5)

            print("    closest to UF goal:")
            for r in sorted(rs, key=dist_uf)[:5]:
                i, o = r["inputs"], r["outputs"]
                print(
                    f"      q={i['q']:>7} ell={i['ell']} m={i['m']} sigma={i['sigma']:.2f} alpha_h={i['alpha_h']:>4}"
                    f" | LWE={o['LWE_security_bit']:6.2f} UF={o['SIS_UF_security_bit']:6.2f} sUF={o['SIS_sUF_security_bit']:6.2f}"
                )
            print("    closest to sUF goal:")
            for r in sorted(rs, key=dist_suf)[:5]:
                i, o = r["inputs"], r["outputs"]
                print(
                    f"      q={i['q']:>7} ell={i['ell']} m={i['m']} sigma={i['sigma']:.2f} alpha_h={i['alpha_h']:>4}"
                    f" | LWE={o['LWE_security_bit']:6.2f} UF={o['SIS_UF_security_bit']:6.2f} sUF={o['SIS_sUF_security_bit']:6.2f}"
                )

        # extrema for understanding axes
        lwe_vals = [r["outputs"]["LWE_security_bit"] for r in rs]
        uf_vals = [r["outputs"]["SIS_UF_security_bit"] for r in rs]
        suf_vals = [r["outputs"]["SIS_sUF_security_bit"] for r in rs]
        print(f"\n  -- ranges --  LWE:[{min(lwe_vals):.1f},{max(lwe_vals):.1f}]  UF:[{min(uf_vals):.1f},{max(uf_vals):.1f}]  sUF:[{min(suf_vals):.1f},{max(suf_vals):.1f}]")


if __name__ == "__main__":
    main()
