#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path

from result_dedup import plateau_key, plateau_preference_key, record_key


SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
AGGREGATE_NAMES = {"param_all.jsonl", "param_ideal.jsonl"}


def load_jsonl(path: Path) -> list[dict]:
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


def winner_identity(record: dict, source_name: str) -> tuple:
    with_source = dict(record)
    with_source["source"] = source_name
    return plateau_preference_key(with_source) + (source_name,)


def main() -> None:
    if not RESULTS_DIR.exists():
        raise SystemExit(f"missing {RESULTS_DIR}")

    raw_paths = sorted(
        path
        for path in RESULTS_DIR.glob("*.jsonl")
        if path.name not in AGGREGATE_NAMES
    )

    raw_rows = {path: load_jsonl(path) for path in raw_paths}
    winners: dict[tuple, tuple[tuple, str, tuple]] = {}

    for path, rows in raw_rows.items():
        for record in rows:
            group_key = plateau_key(record)
            exact_key = record_key(record)
            if group_key is None or exact_key is None:
                continue
            candidate = winner_identity(record, path.name)
            current = winners.get(group_key)
            if current is None or candidate > current[0]:
                winners[group_key] = (candidate, path.name, exact_key)

    total_removed = 0
    touched_files = 0
    for path, rows in raw_rows.items():
        seen_exact: set[tuple] = set()
        kept_rows: list[dict] = []
        removed = 0

        for record in rows:
            exact_key = record_key(record)
            if exact_key is not None:
                if exact_key in seen_exact:
                    removed += 1
                    continue
                seen_exact.add(exact_key)

            group_key = plateau_key(record)
            if group_key is None or exact_key is None:
                kept_rows.append(record)
                continue

            _, winner_source, winner_exact = winners[group_key]
            if path.name == winner_source and exact_key == winner_exact:
                kept_rows.append(record)
                continue

            removed += 1

        if removed > 0:
            write_jsonl(path, kept_rows)
            touched_files += 1
        total_removed += removed
        print(f"{path.name}: kept {len(kept_rows)}, removed {removed}")

    print(f"compacted {len(raw_paths)} raw jsonl files; touched {touched_files}; removed {total_removed} rows")


if __name__ == "__main__":
    main()