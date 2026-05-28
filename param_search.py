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
import time
from concurrent.futures import FIRST_COMPLETED, CancelledError, ProcessPoolExecutor, wait
from itertools import product
from math import isqrt
from pathlib import Path

from tqdm import tqdm

from para_alg_impl import ParameterValidationError, compute_parameters


# ====================================================================
# FINAL MIN-Combined per (target, goal) — synced with memory.md & param_ideal.jsonl
# 254 ideal params total. Run `extract_ideal.py` to regenerate.
# Sigma-grid rule: never refine sigma with a step smaller than 0.05.
# Structural jumps in q / alpha_h / (ell,m) remain fair game, but sub-0.05
# sigma micro-tuning is now treated as search noise and should be rejected.
#
# target=128 (n=256) Goal A (UF) ✅ Comb=1864
#   q=7681 ell=3 m=2 sigma=0.510 alpha_h=128 → LWE=133.74 UF=139.87
#   (Pk=848 Sign=1016; q<2^13 signed-int friendly)
#
# target=128 (n=256) Goal B (sUF) ✅ Comb=2397
#   q=349697 ell=4 m=2 sigma=0.527 alpha_h=1024 → LWE=133.15 sUF=133.15
#   (Pk=1232 Sign=1165; iter35-37 local refinement inside the 19-bit q bucket)
#
# target=256 (n=512) Goal A (UF) ✅ Comb=4059
#   q=57089 ell=3 m=2 sigma=0.636 alpha_h=2048 → LWE=261.34 UF=261.34
#   (Pk=2080 Sign=1979)
#
# target=256 (n=512) Goal B (sUF) ✅ Comb=4395
#   q=133121 ell=3 m=2 sigma=0.907 alpha_h=1024 → LWE=261.02 sUF=261.05
#   (Pk=2336 Sign=2059; first hit in the 18-bit q bucket)
#
# target=512 (n=1024) Goal A (UF) ✅ Comb=7269
#   q=8058881 ell=3 m=1 sigma=0.6075 alpha_h=256 → LWE=517.13 UF=517.42
#   (Pk=3008 Sign=4261; iter38 hit along the 8.06M ridge)
#
# target=512 (n=1024) Goal B (sUF) ✅ Comb=9092
#   q=306689 ell=3 m=2 sigma=0.688 alpha_h=4096 → LWE=519.76 sUF=517.13
#   (Pk=4928 Sign=4164; iter49 pushed the frontier into the next lower sign bucket)
# ====================================================================

LOW_Q_128_GOAL_B_Q = [4481, 4993, 6529, 7297, 7681, 7937, 9473, 9601]
DEAD_4392_256_GOAL_B_Q = [133121, 133633, 134401]

PARAM_GROUPS: list[dict] = [
    # Iter-65: small-step follow-up only.
    # 1) Formalize the 128/Goal-B 13-bit coarse ridge after discarding the
    #    sub-0.05 sigma probe file.
    # 2) Recheck the 256/Goal-B 4392-byte dead line on the exact 0.90 grid so
    #    the "no overlap" conclusion is backed by a clean jsonl artifact.
    {
        "target_security": 128, "n": [256],
        "q":       LOW_Q_128_GOAL_B_Q,
        "ell":     [3], "m": [3],
        "sigma":   [0.55, 0.60, 0.65],
        "alpha_h": [1024],
    },
    {
        "target_security": 256, "n": [512],
        "q":       DEAD_4392_256_GOAL_B_Q,
        "ell":     [3], "m": [2],
        "sigma":   [0.90],
        "alpha_h": [1024],
    },
]

PARAM_KEYS = ("n", "q", "ell", "m", "sigma", "alpha_h")

TAG_SOURCES = [
    ("lwe",     "LWE_security_bit"),
    ("sis_uf",  "SIS_UF_security_bit"),
    ("sis_suf", "SIS_sUF_security_bit"),
]

EARLY_STOP_MARGIN = 10_000  # essentially off: rely on sub-group LWE pruning instead
HEARTBEAT_SECONDS = 10
SIGMA_MIN_STEP = 0.05

# Sub-group pruning: per (target, ell, m) probe LWE range.
# After SUB_PROBE_MIN samples in a sub-group, if max(LWE_seen) < target+5 - SUB_PROBE_SLACK
# or min(LWE_seen) > target+12 + SUB_PROBE_SLACK, prune the rest of that sub-group.
SUB_PROBE_MIN = 8
SUB_PROBE_SLACK = 10
SUB_PROBE_SEED = 42

DERIVED_INPUT_FIELDS = ("bk", "alpha_1", "r", "mu_s", "v_s", "bs", "bv", "sigma_h", "a_h")


def thresholds_for(target_security: int) -> list[int]:
    return [target_security, target_security + 5]


def validate_sigma_groups() -> None:
    for group in PARAM_GROUPS:
        sigma_values = sorted({float(value) for value in group["sigma"]})
        for left, right in zip(sigma_values, sigma_values[1:]):
            if right - left < SIGMA_MIN_STEP - 1e-12:
                raise ValueError(
                    f"sigma grid too fine for target={group['target_security']}: "
                    f"{left} -> {right} violates min step {SIGMA_MIN_STEP}"
                )


def is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    limit = isqrt(value)
    factor = 3
    while factor <= limit:
        if value % factor == 0:
            return False
        factor += 2
    return True


def validate_q_groups() -> None:
    for group in PARAM_GROUPS:
        for n in group["n"]:
            ntt_stride = n // 2
            for q in group["q"]:
                if q % ntt_stride != 1:
                    raise ValueError(
                        f"invalid NTT modulus for target={group['target_security']}: "
                        f"q={q} is not congruent to 1 mod {ntt_stride}"
                    )
                if not is_prime(q):
                    raise ValueError(
                        f"invalid NTT prime for target={group['target_security']}: "
                        f"q={q} is composite"
                    )


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
    validate_sigma_groups()
    validate_q_groups()
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

        pending = set(futures)
        with tqdm(total=len(futures), desc="search") as progress:
            while pending:
                ready, pending = wait(
                    pending,
                    timeout=HEARTBEAT_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                if not ready:
                    tqdm.write(
                        f"[heartbeat] completed={progress.n}/{len(futures)} pending={len(pending)}"
                    )
                    continue

                for fut in ready:
                    progress.update(1)
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
