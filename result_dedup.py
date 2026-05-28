from __future__ import annotations

from typing import Any


PARAM_KEY_FIELDS = ("n", "q", "ell", "m", "sigma", "alpha_h")
PLATEAU_INPUT_FIELDS = ("target_security", "n", "q", "ell", "m", "alpha_h")
PLATEAU_OUTPUT_FIELDS = ("PkBytes", "SignBytes", "CombinedBytes")


def record_key(record: dict) -> tuple | None:
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        return None
    if not all(field in inputs for field in PARAM_KEY_FIELDS):
        return None
    return tuple(inputs[field] for field in PARAM_KEY_FIELDS)


def plateau_key(record: dict) -> tuple | None:
    inputs = record.get("inputs")
    outputs = record.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        return None
    if not all(field in inputs for field in PLATEAU_INPUT_FIELDS):
        return None
    if not all(field in outputs for field in PLATEAU_OUTPUT_FIELDS):
        return None
    goals = tuple(sorted(record.get("goals", [])))
    return (
        goals,
        *(inputs[field] for field in PLATEAU_INPUT_FIELDS),
        *(outputs[field] for field in PLATEAU_OUTPUT_FIELDS),
    )


def plateau_preference_key(record: dict) -> tuple[Any, ...]:
    inputs = record.get("inputs") or {}
    outputs = record.get("outputs") or {}
    return (
        float(inputs.get("sigma", float("-inf"))),
        float(outputs.get("LWE_security_bit", float("-inf"))),
        float(outputs.get("SIS_UF_security_bit", float("-inf"))),
        float(outputs.get("SIS_sUF_security_bit", float("-inf"))),
        str(record.get("source") or ""),
    )


def pick_plateau_representatives(records: list[dict]) -> list[dict]:
    chosen: dict[tuple, tuple[int, dict]] = {}
    passthrough: list[tuple[int, dict]] = []

    for index, record in enumerate(records):
        key = plateau_key(record)
        if key is None:
            passthrough.append((index, record))
            continue
        existing = chosen.get(key)
        if existing is None or plateau_preference_key(record) > plateau_preference_key(existing[1]):
            keep_index = existing[0] if existing is not None else index
            chosen[key] = (keep_index, record)

    collapsed = passthrough + list(chosen.values())
    collapsed.sort(key=lambda item: item[0])
    return [record for _, record in collapsed]