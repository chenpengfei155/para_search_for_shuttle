#!/usr/bin/env python3

from __future__ import annotations

# Force one BLAS/OpenMP thread per worker process so multi-process search can
# actually use all CPU cores instead of oversubscribing them.
import os as _os

for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    _os.environ.setdefault(_var, "1")

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
from datetime import datetime
from itertools import product
import math
from math import isqrt
import os
from pathlib import Path

from gen_html import render_html_rows
from para_alg_impl import ParameterValidationError, R_SCALING, compute_parameters, floor_power_of_two
from result_dedup import record_key

SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_DIR = SCRIPT_DIR / "results" / "local_test"
JSONL_PATH = REPORT_DIR / "test_runs.jsonl"
HTML_PATH = REPORT_DIR / "test_runs.html"
META_PATH = REPORT_DIR / "test_runs.meta.json"
DELETE_API_PATH = "/api/local-test/delete"
LIVE_REFRESH_INTERVAL_MS = 2000
TARGET_SECURITY_BY_N = {256: 128, 512: 256, 1024: 512}
DERIVED_INPUT_FIELDS = ("bk", "alpha_1", "r", "mu_s", "v_s", "bs", "bv", "sigma_h", "a_h")
TAG_SOURCES = (
    ("lwe", "LWE_security_bit"),
    ("sis_uf", "SIS_UF_security_bit"),
    ("sis_suf", "SIS_sUF_security_bit"),
)
DEFAULT_WORKERS = max(1, os.cpu_count() or 1)

N_VALUES = [256, 512, 1024]
Q_VALUES = [
    7681,
    12289,
    23297,
    40961,
    65537,
    133121,
    254977,
    525313,
    1048577,
    2097153,
    4194304,
    8388608,
    16780289,
    33550337,
    67108865,
    134217729,
    268435457,
    536870913,
    1073741825,
    2147483649,
    4294957057,
]
ELL_VALUES = [3, 2, 1]
M_VALUES = [3, 2, 1]
SIGMA_VALUES = [0.7, 
0.8, 0.9, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 11, 
15, 20]
ALPHA_H_VALUES = [1, 2,
 8, 16, 64, 128, 256, 512, 1024, 4096, 8192, 16384,
  1048576]


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(text)
    temp_path.replace(path)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    write_text_atomic(path, payload)


def write_report_meta(path: Path, meta: dict) -> None:
    write_text_atomic(path, json.dumps(meta, ensure_ascii=False))


def thresholds_for(target_security: int) -> list[int]:
    return [target_security, target_security + 5]


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


def valid_q_values_for_n(n: int) -> list[int]:
    lambda_bits = n // 2
    return [q for q in Q_VALUES if q > 1 and (q - 1) % lambda_bits == 0 and is_prime(q)]


def alpha_h_passes_prefilter(n: int, ell: int, m: int, sigma_1: float, sigma_2: float, alpha_h: int) -> bool:
    if alpha_h <= 0 or alpha_h & (alpha_h - 1):
        return False

    bk = math.sqrt(1 + ell * n * sigma_1**2 + m * n * sigma_2**2)
    alpha_1 = floor_power_of_two(math.sqrt((ell * n * sigma_1**2 + m * n * sigma_2**2) / (ell + n)))
    r = math.ceil(R_SCALING[n // 2] * math.sqrt(alpha_1**2 - 1 + bk**2))
    return alpha_h <= 40 * r


def task_key(params: dict) -> tuple:
    return (
        params["n"],
        params["q"],
        params["ell"],
        params["m"],
        params["sigma_1"],
        params["sigma_2"],
        params["alpha_h"],
    )


def dedupe_rows(rows: list[dict]) -> list[dict]:
    keyed_rows: dict[tuple, dict] = {}
    passthrough_rows: list[dict] = []
    for row in rows:
        key = record_key(row)
        if key is None:
            passthrough_rows.append(row)
            continue
        keyed_rows[key] = row
    return sort_rows(passthrough_rows + list(keyed_rows.values()))


def build_tasks(limit: int | None = None, skip_keys: set[tuple] | None = None) -> list[dict]:
    tasks: list[dict] = []
    candidate_count = 0
    for n in N_VALUES:
        for q in valid_q_values_for_n(n):
            for ell, m, sigma, alpha_h in product(ELL_VALUES, M_VALUES, SIGMA_VALUES, ALPHA_H_VALUES):
                candidate_count += 1
                params = {
                    "n": n,
                    "q": q,
                    "ell": ell,
                    "m": m,
                    "sigma_1": sigma,
                    "sigma_2": sigma,
                    "alpha_h": alpha_h,
                }
                if not alpha_h_passes_prefilter(n, ell, m, sigma, sigma, alpha_h):
                    if limit is not None and candidate_count >= limit:
                        return tasks
                    continue
                if skip_keys is None or task_key(params) not in skip_keys:
                    tasks.append(params)
                if limit is not None and candidate_count >= limit:
                    return tasks
    return tasks


def detect_goals(outputs: dict, target_security: int) -> list[str]:
    lo = target_security + 5
    hi = target_security + 12
    lwe = outputs.get("LWE_security_bit")
    sis_uf = outputs.get("SIS_UF_security_bit")
    sis_suf = outputs.get("SIS_sUF_security_bit")

    goals: list[str] = []
    if lwe is not None and sis_uf is not None and lo <= lwe <= hi and lo <= sis_uf <= hi:
        goals.append("UF")
    if lwe is not None and sis_suf is not None and lo <= lwe <= hi and lo <= sis_suf <= hi:
        goals.append("sUF")
    return goals


def compute_tags(outputs: dict, target_security: int, goals: list[str]) -> list[str]:
    tags = [f"target_security={target_security}", "rough"]
    tags.extend(f"goal={goal}" for goal in goals)
    for prefix, field in TAG_SOURCES:
        bits = outputs.get(field)
        if bits is None:
            continue
        for threshold in thresholds_for(target_security):
            if bits > threshold:
                tags.append(f"{prefix}>{threshold}")
    return tags


def build_success_record(params: dict, artifacts) -> dict:
    target_security = TARGET_SECURITY_BY_N[params["n"]]
    inputs = dict(params)
    inputs["target_security"] = target_security
    for field in DERIVED_INPUT_FIELDS:
        inputs[field] = getattr(artifacts.result, field)

    outputs = artifacts.result.to_dict()
    goals = detect_goals(outputs, target_security)
    return {
        "inputs": inputs,
        "outputs": outputs,
        "goals": goals,
        "tags": compute_tags(outputs, target_security, goals),
        "source": "test.py",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_failure_record(params: dict, error: Exception) -> dict:
    target_security = TARGET_SECURITY_BY_N.get(params["n"])
    inputs = dict(params)
    if target_security is not None:
        inputs["target_security"] = target_security
    return {
        "inputs": inputs,
        "reason": str(error),
        "source": "test.py",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_report_meta(task_count: int, processed_count: int, state: str) -> dict:
    return {
        "task_count": task_count,
        "processed_count": processed_count,
        "state": state,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda record: (
            (record.get("inputs") or {}).get("target_security", 10**9),
            (record.get("inputs") or {}).get("n", 10**9),
            (record.get("inputs") or {}).get("q", 10**18),
            (record.get("inputs") or {}).get("ell", 10**9),
            (record.get("inputs") or {}).get("m", 10**9),
            (record.get("inputs") or {}).get("sigma_1", (record.get("inputs") or {}).get("sigma", 10**9)),
            (record.get("inputs") or {}).get("sigma_2", (record.get("inputs") or {}).get("sigma", 10**9)),
            (record.get("inputs") or {}).get("alpha_h", 10**18),
        ),
    )


def compute_one(params: dict) -> dict | None:
    try:
        artifacts = compute_parameters(**params)
    except ParameterValidationError as error:
        return build_failure_record(params, error)
    return build_success_record(params, artifacts)


def save_report(rows: list[dict], meta: dict, rewrite_html: bool) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ordered_rows = dedupe_rows(rows)
    write_jsonl(JSONL_PATH, ordered_rows)
    write_report_meta(META_PATH, meta)
    render_html_rows(
        ordered_rows,
        HTML_PATH,
        delete_api_url=DELETE_API_PATH,
        collapse_plateaus=False,
        meta_url=META_PATH.name,
        live_refresh_interval_ms=LIVE_REFRESH_INTERVAL_MS,
        rewrite_html=rewrite_html,
    )


def run_batch(tasks: list[dict], workers: int, existing_rows: list[dict]) -> tuple[int, list[dict]]:
    if not tasks:
        save_report(existing_rows, build_report_meta(0, 0, "completed"), rewrite_html=True)
        return 0, existing_rows

    all_rows = list(existing_rows)
    processed_count = 0
    task_count = len(tasks)
    valid_count = sum(1 for row in existing_rows if row.get("outputs") is not None)
    max_pending = max(1, workers * 4)

    save_report(all_rows, build_report_meta(task_count, 0, "running"), rewrite_html=True)

    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            task_iter = iter(tasks)
            pending: set = set()

            while len(pending) < min(task_count, max_pending):
                try:
                    pending.add(executor.submit(compute_one, next(task_iter)))
                except StopIteration:
                    break

            while pending:
                completed, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    result = future.result()
                    processed_count += 1
                    if result is not None:
                        all_rows.append(result)
                        if result.get("outputs") is not None:
                            valid_count += 1

                    state = "completed" if processed_count == task_count else "running"
                    save_report(
                        all_rows,
                        build_report_meta(task_count, processed_count, state),
                        rewrite_html=False,
                    )

                    if processed_count % 200 == 0 or processed_count == task_count:
                        print(f"processed {processed_count}/{task_count} combinations; valid={valid_count}")

                    try:
                        pending.add(executor.submit(compute_one, next(task_iter)))
                    except StopIteration:
                        pass
    except KeyboardInterrupt:
        save_report(
            all_rows,
            build_report_meta(task_count, processed_count, "interrupted"),
            rewrite_html=False,
        )
        raise

    return len(tasks), all_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enumerate all legal parameter combinations and publish them to the local report.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="worker processes to use; default is all CPU cores")
    parser.add_argument("--limit", type=int, help="only process the first N q-filtered combinations (useful for smoke tests)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.workers <= 0:
        raise SystemExit("--workers must be positive")

    existing_rows = dedupe_rows(load_jsonl(JSONL_PATH))
    existing_keys = {
        key
        for row in existing_rows
        if (key := record_key(row)) is not None
    }
    tasks = build_tasks(limit=args.limit, skip_keys=existing_keys)
    task_count, all_rows = run_batch(tasks, args.workers, existing_rows)
    valid_rows = [row for row in all_rows if row.get("outputs") is not None]

    summary = {
        "workers": args.workers,
        "cached_record_count": len(existing_rows),
        "task_count": task_count,
        "valid_record_count": len(valid_rows),
        "report_path": str(HTML_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved report to: {HTML_PATH}")


if __name__ == "__main__":
    main()


