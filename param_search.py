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
# FINAL MIN-Combined per (target, goal) — synced with memory.md §2 & param_ideal.jsonl
# Band = [target+5, target+30] (GOAL_HI_OFFSET=30, user 2026-05-29).
# Sigma-grid rule: sigma_1 and sigma_2 must be multiples of 0.05; no sub-0.05 micro-tuning.
#
# --- 2.1 GENERAL (sigma_1,sigma_2>=0.5, on-grid) ---
# t=128 A Comb=1866  q=4993  ell=3 m=2 s=0.50 a_h=128  L=144.83 UF=134.32 (Pk=848  Sn=1018)
# t=128 B Comb=2090  q=3329  ell=3 m=3 s=0.55 a_h=512  L=144.81 sUF=135.20 (Pk=1168 Sn=922)
# t=256 A Comb=3847  q=30977 ell=3 m=2 s=0.50 a_h=1024 L=266.01 UF=282.07 (Pk=1952 Sn=1895)
# t=256 B Comb=3855  q=32257 ell=3 m=2 s=0.50 a_h=512  L=263.38 sUF=261.63 (Pk=1952 Sn=1903)
# t=512 A Comb=7170  q=3002369 ell=3 m=1 s=0.50 a_h=128 L=522.68 UF=522.39 (Pk=2880 Sn=4290)
# t=512 B Comb=9107  q=326657  ell=3 m=2 s=0.70 a_h=4096 L=518.01 sUF=520.05 (Pk=4928 Sn=4179)
#
# --- 2.2 SIGMA>=1 (hard constraint, on-grid) ---
# t=128 A Comb=2090  q=28289   ell=3 m=2 s=1.00 a_h=256  L=136.10 UF=137.82 (Pk=976  Sn=1114)
# t=128 B Comb=2348  q=7681    ell=3 m=3 s=1.00 a_h=512  L=157.68 sUF=143.37 (Pk=1264 Sn=1084)
# t=256 A Comb=4295  q=130817  ell=3 m=2 s=1.00 a_h=2048 L=267.18 UF=277.98 (Pk=2208 Sn=2087)
# t=256 B Comb=4431  q=160001  ell=3 m=2 s=1.00 a_h=1024 L=261.70 sUF=263.68 (Pk=2336 Sn=2095)
# t=512 A Comb=7938  q=32000513 ell=3 m=1 s=1.00 a_h=256 L=534.36 UF=521.22 (Pk=3264 Sn=4674)
# t=512 B Comb=9343  q=495617  ell=3 m=2 s=1.00 a_h=4096 L=539.03 sUF=533.48 (Pk=4928 Sn=4415)
# ====================================================================

LOW_Q_128_GOAL_B_Q = [4481, 4993, 6529, 7297, 7681, 7937, 9473, 9601]
DEAD_4392_256_GOAL_B_Q = [133121, 133633, 134401]

PARAM_GROUPS: list[dict] = [
    # Iter-82: t=512 Goal B, probe ell=2 m=2 (sign -~900 via dropped ell*n/2 term).
    # Unlike 256A, dim-2048 LWE CAN reach 517 -- map L & sUF vs q to see if they
    # overlap in [517,542]. Pk same as ell=3 m=2 (depends on m).
    {
        "target_security": 512, "n": [1024],
        "q":       [32257, 65537, 133121, 326657, 658433],
        "ell":     [2], "m": [2],
        "sigma_1": [0.70, 1.00],
        "sigma_2": [0.70, 1.00],
        "alpha_h": [1024, 4096],
    },
]

PARAM_KEYS = ("n", "q", "ell", "m", "sigma_1", "sigma_2", "alpha_h")

TAG_SOURCES = [
    ("lwe",     "LWE_security_bit"),
    ("sis_uf",  "SIS_UF_security_bit"),
    ("sis_suf", "SIS_sUF_security_bit"),
]

EARLY_STOP_MARGIN = 10_000  # essentially off: rely on sub-group LWE pruning instead
HEARTBEAT_SECONDS = 10
SIGMA_MIN_STEP = 0.05

# Acceptance band: target+GOAL_LO_OFFSET <= security <= target+GOAL_HI_OFFSET.
# User goal (2026-05-29): lambda+5 <= sec <= lambda+30. Widened from +12 -> +30,
# which reopens many regions previously pruned/declared dead for being "too secure".
GOAL_LO_OFFSET = 5
GOAL_HI_OFFSET = 30

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
        for sigma_key in ("sigma_1", "sigma_2"):
            sigma_values = sorted({float(value) for value in group[sigma_key]})
            for left, right in zip(sigma_values, sigma_values[1:]):
                if right - left < SIGMA_MIN_STEP - 1e-12:
                    raise ValueError(
                        f"{sigma_key} grid too fine for target={group['target_security']}: "
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
    shuffled with a fixed seed so the first few completions span q/sigma_1/sigma_2/alpha_h
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
        float(params["sigma_1"]),
        float(params["sigma_2"]),
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
                        lo_goal = ts + GOAL_LO_OFFSET
                        hi_goal = ts + GOAL_HI_OFFSET
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
