#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_JSONL_PATHS = (
    SCRIPT_DIR / "results" / "param_all.jsonl",
    SCRIPT_DIR / "results" / "param_ideal.jsonl",
    SCRIPT_DIR / "results" / "local_test" / "test_runs.jsonl",
    SCRIPT_DIR / "search" / "results" / "search_smoke_test" / "shard_0.jsonl",
    SCRIPT_DIR / "search" / "results" / "search_smoke_test" / "shard_1.jsonl",
)
INPUT_FIELD_PRIORITY = (
    "target_security",
    "n",
    "q",
    "ell",
    "m",
    "sigma_1",
    "sigma_2",
    "alpha_h",
    "bk",
    "alpha_1",
    "r",
    "mu_s",
    "v_s",
    "bs",
    "bv",
    "sigma_h",
    "a_h",
)
SIGMA_HARD_CONSTRAINT_TAG = "min(sigma_1,sigma_2)>=1"
LEGACY_SIGMA_HARD_CONSTRAINT_TAGS = {"sigma>=1"}


def resolve_targets(raw_targets: list[str]) -> list[Path]:
    if not raw_targets:
        return [path for path in DEFAULT_JSONL_PATHS if path.exists()]

    resolved: list[Path] = []
    for raw_target in raw_targets:
        path = Path(raw_target)
        if not path.is_absolute():
            path = SCRIPT_DIR / path
        if path.is_dir():
            resolved.extend(sorted(path.rglob("*.jsonl")))
            continue
        resolved.append(path)

    seen: set[Path] = set()
    unique_paths: list[Path] = []
    for path in resolved:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    return unique_paths


def normalize_inputs(inputs: dict) -> tuple[dict, bool]:
    sigma_1 = inputs.get("sigma_1")
    sigma_2 = inputs.get("sigma_2")
    legacy_sigma = inputs.get("sigma")
    changed = False

    if sigma_1 is None and legacy_sigma is not None:
        sigma_1 = legacy_sigma
        changed = True
    if sigma_2 is None and legacy_sigma is not None:
        sigma_2 = legacy_sigma
        changed = True

    normalized_inputs = dict(inputs)
    if "sigma" in normalized_inputs:
        normalized_inputs.pop("sigma")
        changed = True
    if sigma_1 is not None and normalized_inputs.get("sigma_1") != sigma_1:
        normalized_inputs["sigma_1"] = sigma_1
        changed = True
    if sigma_2 is not None and normalized_inputs.get("sigma_2") != sigma_2:
        normalized_inputs["sigma_2"] = sigma_2
        changed = True

    if not changed:
        return inputs, False

    ordered_inputs: dict = {}
    remaining = dict(normalized_inputs)
    for key in INPUT_FIELD_PRIORITY:
        if key in remaining:
            ordered_inputs[key] = remaining.pop(key)
    ordered_inputs.update(remaining)
    return ordered_inputs, True


def normalize_tags(tags: list[str], inputs: dict) -> tuple[list[str], bool]:
    normalized: list[str] = []
    seen: set[str] = set()
    changed = False

    for tag in tags:
        mapped_tag = SIGMA_HARD_CONSTRAINT_TAG if tag in LEGACY_SIGMA_HARD_CONSTRAINT_TAGS else tag
        if mapped_tag != tag:
            changed = True
        if mapped_tag in seen:
            changed = True
            continue
        normalized.append(mapped_tag)
        seen.add(mapped_tag)

    sigma_1 = inputs.get("sigma_1")
    sigma_2 = inputs.get("sigma_2")
    if (
        isinstance(sigma_1, (int, float))
        and isinstance(sigma_2, (int, float))
        and min(sigma_1, sigma_2) >= 1
        and SIGMA_HARD_CONSTRAINT_TAG not in seen
    ):
        normalized.append(SIGMA_HARD_CONSTRAINT_TAG)
        changed = True

    return normalized, changed


def normalize_record(record: dict) -> tuple[dict, bool]:
    changed = False
    normalized_record = dict(record)

    inputs = normalized_record.get("inputs")
    if isinstance(inputs, dict):
        normalized_inputs, inputs_changed = normalize_inputs(inputs)
        if inputs_changed:
            normalized_record["inputs"] = normalized_inputs
            inputs = normalized_inputs
            changed = True

    tags = normalized_record.get("tags")
    if isinstance(tags, list) and isinstance(inputs, dict):
        normalized_tags, tags_changed = normalize_tags(tags, inputs)
        if tags_changed:
            normalized_record["tags"] = normalized_tags
            changed = True

    return normalized_record, changed


def migrate_jsonl(path: Path) -> tuple[int, int]:
    if not path.exists():
        print(f"skip missing {path}")
        return 0, 0

    total_records = 0
    changed_records = 0
    output_lines: list[str] = []

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                output_lines.append(raw_line.rstrip("\n"))
                continue

            total_records += 1
            normalized_record, record_changed = normalize_record(record)
            if record_changed:
                changed_records += 1
            output_lines.append(json.dumps(normalized_record, ensure_ascii=False))

    if changed_records > 0:
        path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    print(f"{path}: updated {changed_records} / {total_records} record(s)")
    return total_records, changed_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy single-sigma JSONL records to dual-sigma schema.")
    parser.add_argument(
        "targets",
        nargs="*",
        help="jsonl files or directories to migrate (defaults to known project artifacts)",
    )
    args = parser.parse_args()

    paths = resolve_targets(args.targets)
    if not paths:
        raise SystemExit("no jsonl targets found")

    total_records = 0
    changed_records = 0
    for path in paths:
        records, changed = migrate_jsonl(path)
        total_records += records
        changed_records += changed

    print(f"migrated {changed_records} / {total_records} record(s) across {len(paths)} file(s)")


if __name__ == "__main__":
    main()