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
from concurrent.futures import ProcessPoolExecutor
import json
from datetime import datetime
from itertools import product
from math import isqrt
import os
from pathlib import Path

from gen_html import render_html_rows
from para_alg_impl import ParameterValidationError, compute_parameters

SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_DIR = SCRIPT_DIR / "results" / "local_test"
JSONL_PATH = REPORT_DIR / "test_runs.jsonl"
HTML_PATH = REPORT_DIR / "test_runs.html"
DELETE_API_PATH = "/api/local-test/delete"
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
SIGMA_VALUES = [0.7, 0.8, 0.9, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 11, 15, 20]
ALPHA_H_VALUES = [1, 2, 8, 16, 64, 128, 256, 512, 1024, 4096, 8192, 16384, 1048576]


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
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def build_tasks(limit: int | None = None) -> list[dict]:
    tasks: list[dict] = []
    for n in N_VALUES:
        for q in valid_q_values_for_n(n):
            for ell, m, sigma, alpha_h in product(ELL_VALUES, M_VALUES, SIGMA_VALUES, ALPHA_H_VALUES):
                tasks.append(
                    {
                        "n": n,
                        "q": q,
                        "ell": ell,
                        "m": m,
                        "sigma_1": sigma,
                        "sigma_2": sigma,
                        "alpha_h": alpha_h,
                    }
                )
    if limit is not None:
        return tasks[:limit]
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
    except ParameterValidationError:
        return None
    return build_success_record(params, artifacts)


def save_report(rows: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ordered_rows = sort_rows(rows)
    write_jsonl(JSONL_PATH, ordered_rows)
    render_html_rows(ordered_rows, HTML_PATH, delete_api_url=DELETE_API_PATH, collapse_plateaus=False)


def run_batch(workers: int, limit: int | None = None) -> tuple[int, list[dict]]:
    tasks = build_tasks(limit=limit)
    if not tasks:
        return 0, []

    chunksize = max(1, len(tasks) // max(1, workers * 4))
    valid_rows: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, result in enumerate(executor.map(compute_one, tasks, chunksize=chunksize), start=1):
            if result is not None:
                valid_rows.append(result)
            if index % 200 == 0 or index == len(tasks):
                print(f"processed {index}/{len(tasks)} combinations; valid={len(valid_rows)}")

    return len(tasks), valid_rows


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

    task_count, valid_rows = run_batch(args.workers, limit=args.limit)
    save_report(valid_rows)

    summary = {
        "workers": args.workers,
        "task_count": task_count,
        "valid_record_count": len(valid_rows),
        "report_path": str(HTML_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved report to: {HTML_PATH}")


if __name__ == "__main__":
    main()


