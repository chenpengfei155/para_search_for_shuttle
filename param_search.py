#!/usr/bin/env python3

from __future__ import annotations

# Force single-threaded BLAS/OpenMP inside each worker. The lattice-estimator
# uses numpy/sage which otherwise spawns many threads per process — with 13
# worker processes that produces 50+ contended threads on 14 cores, giving
# only ~15% effective CPU utilization. Must be set BEFORE numpy is imported.
import os as _os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    _os.environ.setdefault(_v, "1")

import argparse
import json
import os
import random
from concurrent.futures import CancelledError, ProcessPoolExecutor, as_completed
from itertools import product
from pathlib import Path

from tqdm import tqdm

from para_alg_impl import ParameterValidationError, compute_parameters


# ====================================================================
# CONFIRMED VIABLE ZONES (synced with memory.md "VIABLE ZONES" section)
# All 6 cells (target × goal) hit. 43 unique ideal params written to
# results/param_ideal.jsonl. Run `extract_ideal.py` to regenerate.
#
# target=128 (n=256) Goal A (UF) ✅ (27 records)
#   zone1: ell=3 m=2, q∈{17921,28289}, sigma∈[0.80,1.05], alpha_h∈{128,256}
#   zone2: ell=4 m=2, q=1500929, sigma∈[1.05,1.20], alpha_h=4096
#   居中代表: q=1500929 ell=4 m=2 sigma=1.10 alpha_h=4096 → LWE=134.67 UF=133.74
#
# target=128 (n=256) Goal B (sUF) ✅ (2 records)
#   ell=4 m=2, q=1123841, sigma∈{1.05,1.10}, alpha_h=1024
#   居中代表: sigma=1.05 → LWE=137.09 sUF=139.58
#
# target=256 (n=512) Goal A (UF) ✅ (7 records)
#   ell=3 m=2 alpha_h=4096, q∈{393473,414209,425473}, sigma∈[1.55,1.70]
#   居中代表: q=414209 sigma=1.70 → LWE=267.96 UF=266.60
#
# target=256 (n=512) Goal B (sUF) ✅ (5 records)
#   ell=3 m=2 alpha_h=1024, q∈{151553,160001,170497,201473}, sigma∈[1.00,1.20]
#   居中代表: q=201473 sigma=1.20 → LWE=266.02 sUF=264.55
#
# target=512 (n=1024) Goal A (UF) ✅ (1 record)
#   q=12000257 ell=3 m=1 sigma=0.70 alpha_h=256 → LWE=521.80 UF=519.47
#
# target=512 (n=1024) Goal B (sUF) ✅ (1 record)
#   q=326657 ell=3 m=2 sigma=0.70 alpha_h=4096 → LWE=518.01 sUF=520.05
# ====================================================================

PARAM_GROUPS: list[dict] = [
    # Iter-19: pinpoint Goal A. iter18 q=393473 s=1.70 a=4096 → LWE=269.30 UF=265.43 ✅
    # LWE just 1.3 bits over band. Fine-tune sigma + q in narrow zone.
    {
        "target_security": 256, "n": [512],
        "q":       [393473, 414209, 425473, 444929, 460289, 471041, 490241, 503297],
        "ell":     [3], "m": [2],
        "sigma":   [1.55, 1.60, 1.65, 1.70, 1.75],
        "alpha_h": [4096],
    },
]

PARAM_KEYS = ("n", "q", "ell", "m", "sigma", "alpha_h")

TAG_SOURCES = [
    ("lwe",     "LWE_security_bit"),
    ("sis_uf",  "SIS_UF_security_bit"),
    ("sis_suf", "SIS_sUF_security_bit"),
]

EARLY_STOP_MARGIN = 10_000  # essentially off: rely on sub-group LWE pruning instead

# Sub-group pruning: per (target, ell, m) probe LWE range.
# After SUB_PROBE_MIN samples in a sub-group, if max(LWE_seen) < target+5 - SUB_PROBE_SLACK
# or min(LWE_seen) > target+12 + SUB_PROBE_SLACK, prune the rest of that sub-group.
SUB_PROBE_MIN = 8
SUB_PROBE_SLACK = 10
SUB_PROBE_SEED = 42

DERIVED_INPUT_FIELDS = ("bk", "alpha_1", "r", "mu_s", "v_s", "bs", "bv", "sigma_h", "a_h")


def thresholds_for(target_security: int) -> list[int]:
    return [target_security, target_security + 5]


def sub_group_key(params: dict) -> tuple:
    return (params["_target_security"], params["ell"], params["m"], params["n"])


def iter_param_combinations() -> list[dict]:
    """Build tasks list. Within each (target, ell, m, n) sub-group the order is
    shuffled with a fixed seed so the first few completions span q/sigma/alpha_h
    diversely (drives sub-group pruning to fire early)."""
    rng = random.Random(SUB_PROBE_SEED)
    sub_buckets: dict[tuple, list[dict]] = {}
    for group in PARAM_GROUPS:
        for values in product(*(group[k] for k in PARAM_KEYS)):
            params = dict(zip(PARAM_KEYS, values))
            params["_target_security"] = group["target_security"]
            sub_buckets.setdefault(sub_group_key(params), []).append(params)
    for bucket in sub_buckets.values():
        rng.shuffle(bucket)
    # Interleave sub-buckets so all sub-groups make progress in parallel
    tasks: list[dict] = []
    while any(sub_buckets.values()):
        for key in list(sub_buckets.keys()):
            if sub_buckets[key]:
                tasks.append(sub_buckets[key].pop())
    return tasks


def params_key(params: dict) -> tuple:
    return (
        params["n"],
        params["q"],
        params["ell"],
        params["m"],
        float(params["sigma"]),
        params["alpha_h"],
    )


def is_early_stop_hit(outputs: dict, target_security: int) -> bool:
    limit = target_security + EARLY_STOP_MARGIN
    for _, field in TAG_SOURCES:
        bits = outputs.get(field)
        if bits is None or bits <= limit:
            return False
    return True


def compute_tags(outputs: dict, target_security: int) -> list[str]:
    tags: list[str] = [f"target_security={target_security}", "rough"]
    for prefix, field in TAG_SOURCES:
        bits = outputs.get(field)
        if bits is None:
            continue
        for thr in thresholds_for(target_security):
            if bits > thr:
                tags.append(f"{prefix}>{thr}")
    return tags


def run_one(params: dict) -> dict:
    target_security = params.pop("_target_security")
    inputs = dict(params)
    inputs["target_security"] = target_security
    try:
        artifacts = compute_parameters(**params)
    except ParameterValidationError as exc:
        return {
            "inputs": inputs,
            "reason": str(exc),
            "tags": [f"target_security={target_security}", "rough"],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "inputs": inputs,
            "reason": repr(exc),
            "tags": [f"target_security={target_security}", "rough"],
        }
    result = artifacts.result
    for field in DERIVED_INPUT_FIELDS:
        inputs[field] = getattr(result, field)
    outputs = result.to_dict()
    return {
        "inputs": inputs,
        "outputs": outputs,
        "tags": compute_tags(outputs, target_security),
    }


def load_done(out_path: Path) -> set[tuple]:
    """Build the dedup set by scanning every jsonl in the results directory,
    so prior iterations (e.g. iter1.jsonl, iter2.jsonl) all count as cached."""
    done: set[tuple] = set()
    results_dir = out_path.parent
    if not results_dir.exists():
        return done
    for path in sorted(results_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ip = rec.get("inputs")
                if not isinstance(ip, dict):
                    continue
                if not all(k in ip for k in PARAM_KEYS):
                    continue
                done.add(params_key(ip))
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-core parameter search.")
    parser.add_argument(
        "--out",
        default="results/param_search.jsonl",
        help="output jsonl path (relative to script dir if not absolute)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="number of worker processes",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parent / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out_path)

    all_params = iter_param_combinations()
    todo = [p for p in all_params if params_key(p) not in done]

    print(
        f"total={len(all_params)}, done={len(done)}, todo={len(todo)}, workers={args.workers}"
    )
    if not todo:
        print("nothing to do.")
        return

    group_futures: dict[int, set] = {}
    group_stopped: dict[int, bool] = {}
    sub_futures: dict[tuple, set] = {}
    sub_lwe: dict[tuple, list[float]] = {}
    sub_pruned: dict[tuple, bool] = {}

    with out_path.open("a", buffering=1, encoding="utf-8") as fout, \
         ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for params in todo:
            ts = params["_target_security"]
            sk = sub_group_key(params)
            group_futures.setdefault(ts, set())
            group_stopped.setdefault(ts, False)
            sub_futures.setdefault(sk, set())
            sub_lwe.setdefault(sk, [])
            sub_pruned.setdefault(sk, False)
            fut = pool.submit(run_one, params)
            futures[fut] = params
            group_futures[ts].add(fut)
            sub_futures[sk].add(fut)

        for fut in tqdm(as_completed(futures), total=len(futures), desc="search"):
            params = futures[fut]
            ts = params["_target_security"]
            sk = sub_group_key(params)
            group_futures[ts].discard(fut)
            sub_futures[sk].discard(fut)
            try:
                rec = fut.result()
            except CancelledError:
                continue
            except Exception as exc:  # noqa: BLE001
                inputs = {k: params[k] for k in PARAM_KEYS}
                inputs["target_security"] = ts
                rec = {
                    "inputs": inputs,
                    "reason": repr(exc),
                    "tags": [f"target_security={ts}", "rough"],
                }
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

            outputs = rec.get("outputs")
            if outputs is not None:
                lwe = outputs.get("LWE_security_bit")
                if lwe is not None:
                    sub_lwe[sk].append(lwe)

                if not group_stopped[ts] and is_early_stop_hit(outputs, ts):
                    group_stopped[ts] = True
                    cancelled = 0
                    for f in list(group_futures[ts]):
                        if f.cancel():
                            cancelled += 1
                    tqdm.write(
                        f"[early-stop] target={ts} all securities > {ts + EARLY_STOP_MARGIN}; "
                        f"cancelled {cancelled} pending tasks in this target group"
                    )

            # Sub-group pruning by LWE-range probe
            if (
                not sub_pruned[sk]
                and len(sub_lwe[sk]) >= SUB_PROBE_MIN
            ):
                lo_goal = ts + 5
                hi_goal = ts + 12
                seen_max = max(sub_lwe[sk])
                seen_min = min(sub_lwe[sk])
                unreachable_high = seen_max < lo_goal - SUB_PROBE_SLACK
                unreachable_low = seen_min > hi_goal + SUB_PROBE_SLACK
                if unreachable_high or unreachable_low:
                    sub_pruned[sk] = True
                    cancelled = 0
                    for f in list(sub_futures[sk]):
                        if f.cancel():
                            cancelled += 1
                    direction = "below" if unreachable_high else "above"
                    tqdm.write(
                        f"[sub-prune] target={ts} ell={sk[1]} m={sk[2]} n={sk[3]}: "
                        f"LWE range [{seen_min:.1f},{seen_max:.1f}] {direction} goal [{lo_goal},{hi_goal}]; "
                        f"cancelled {cancelled} pending in this sub-group"
                    )


if __name__ == "__main__":
    main()
