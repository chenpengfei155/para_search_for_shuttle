#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import CancelledError, ProcessPoolExecutor, as_completed
from itertools import product
from pathlib import Path

from tqdm import tqdm

from para_alg_impl import ParameterValidationError, compute_parameters


PARAM_GROUPS: list[dict] = [
    {
        "target_security": 128,
        "n": 256,
        "q": [7681, 11777, 17921, 28289, 43649, 65537, 98561, 148609, 222977, 334721],
    },
    {
        "target_security": 256,
        "n": 512,
        "q": [12289, 19457, 30977, 49409, 75521, 113921, 172801, 259841, 393473, 590593],
    },
    {
        "target_security": 512,
        "n": 1024,
        "q": [23041, 36353, 58369, 95233, 143873, 216577, 326657, 495617, 746497, 1123841],
    },
]

COMMON_GRID: dict[str, list] = {
    "ell":     [3],
    "m":       [2],
    "sigma":   [round(0.7 + 0.1 * i, 1) for i in range(19)],   # 0.7..2.5 step 0.1
    "alpha_h": [128, 256, 512, 1024, 2048],
}

PARAM_KEYS = ("n", "q", "ell", "m", "sigma", "alpha_h")

TAG_SOURCES = [
    ("lwe",     "LWE_security_bit"),
    ("sis_uf",  "SIS_UF_security_bit"),
    ("sis_suf", "SIS_sUF_security_bit"),
]

EARLY_STOP_MARGIN = 20

DERIVED_INPUT_FIELDS = ("bk", "alpha_1", "r", "mu_s", "v_s", "bs", "bv", "sigma_h", "a_h")


def thresholds_for(target_security: int) -> list[int]:
    return [target_security, target_security + 5]


def iter_param_combinations() -> list[dict]:
    common_keys = list(COMMON_GRID.keys())
    tasks: list[dict] = []
    for group in PARAM_GROUPS:
        for q in group["q"]:
            for values in product(*(COMMON_GRID[k] for k in common_keys)):
                params = {"n": group["n"], "q": q}
                params.update(dict(zip(common_keys, values)))
                params["_target_security"] = group["target_security"]
                tasks.append(params)
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


def load_done(jsonl_path: Path) -> set[tuple]:
    done: set[tuple] = set()
    if not jsonl_path.exists():
        return done
    with jsonl_path.open("r", encoding="utf-8") as f:
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

    with out_path.open("a", buffering=1, encoding="utf-8") as fout, \
         ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for params in todo:
            ts = params["_target_security"]
            group_futures.setdefault(ts, set())
            group_stopped.setdefault(ts, False)
            fut = pool.submit(run_one, params)
            futures[fut] = params
            group_futures[ts].add(fut)

        for fut in tqdm(as_completed(futures), total=len(futures), desc="search"):
            params = futures[fut]
            ts = params["_target_security"]
            group_futures[ts].discard(fut)
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

            if (
                not group_stopped[ts]
                and "outputs" in rec
                and is_early_stop_hit(rec["outputs"], ts)
            ):
                group_stopped[ts] = True
                cancelled = 0
                for f in list(group_futures[ts]):
                    if f.cancel():
                        cancelled += 1
                tqdm.write(
                    f"[early-stop] target_security={ts} hit (all securities > {ts + EARLY_STOP_MARGIN}); "
                    f"cancelled {cancelled} pending tasks in this group"
                )


if __name__ == "__main__":
    main()
