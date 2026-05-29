#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from gen_html import render_html_rows
from para_alg_impl import ParameterValidationError, compute_parameters
from result_dedup import record_key


    # "n": 256,512,1024
    # "q": 7681,12289,23297,40961,65537,133121,65537,133121,254977,525313,1048577,2097153,4194304,8388608
    # ,16780289,33550337,16780289,33550337,67108865,134217729,268435457,536870913,1073741825,2147483649,4294957057
    # "ell": 3,2,1
    # "m": 3,2,1
    # "sigma": 0.7,0.8,0.9,1,1.5,2,2.5,3,4,5,6,7,8,11,15,20
    # "alpha_h": 1,2,8,16,64,128,256,512,1024,4096,8192,16384,1048576


TEST_PARAMS = {
    "n": 256,
    "q": 23297,
    "ell": 3,
    "m": 2,
    "sigma": 0.7071067811865476,
    "alpha_h": 512,
}

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


def upsert_record(path: Path, new_record: dict) -> list[dict]:
    rows = load_jsonl(path)
    new_key = record_key(new_record)
    if new_key is None:
        rows.append(new_record)
        return rows

    replaced = False
    updated_rows: list[dict] = []
    for row in rows:
        if not replaced and record_key(row) == new_key:
            updated_rows.append(new_record)
            replaced = True
            continue
        updated_rows.append(row)

    if not replaced:
        updated_rows.append(new_record)
    return updated_rows


def build_success_record(artifacts) -> dict:
    target_security = TARGET_SECURITY_BY_N[TEST_PARAMS["n"]]
    inputs = dict(TEST_PARAMS)
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


def build_failure_record(reason: str) -> dict:
    target_security = TARGET_SECURITY_BY_N[TEST_PARAMS["n"]]
    inputs = dict(TEST_PARAMS)
    inputs["target_security"] = target_security
    return {
        "inputs": inputs,
        "reason": reason,
        "tags": [f"target_security={target_security}", "rough", "invalid"],
        "source": "test.py",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def save_report(record: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = upsert_record(JSONL_PATH, record)
    write_jsonl(JSONL_PATH, rows)
    render_html_rows(rows, HTML_PATH, delete_api_url=DELETE_API_PATH)


def main() -> None:
    try:
        artifacts = compute_parameters(**TEST_PARAMS)
    except ParameterValidationError as exc:
        record = build_failure_record(str(exc))
        save_report(record)
        print(f"invalid: {exc}")
        print(f"Saved report to: {HTML_PATH}")
        return

    payload = build_success_record(artifacts)
    save_report(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Saved report to: {HTML_PATH}")


if __name__ == "__main__":
    main()


