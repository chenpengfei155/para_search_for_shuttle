#!/usr/bin/env python3
"""One-off migration: recompute the size fields (and the size-algorithm derived
parameters) for every result record using the *current* para_alg_impl algorithm,
while leaving the (expensive) LWE/SIS security estimates untouched.

Background: commit 17cb14f changed the parameter-generation algorithm
(floor_power_of_two for alpha_1, the bk/r formulas), which shifts r/alpha_1 and
therefore SignBytes/CombinedBytes. We recompute those from the raw inputs and
tag each updated record with SizeAlg=new and SecAlg=old so the report makes the
mixed provenance explicit.

Processes every *.jsonl and *.data.json under results/ in place. The HTML reports
are data-driven (they fetch the .data.json at runtime and render tags.join(', ')),
so updating the data files is enough for the new tags to show up in the table and
the tag-filter panel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import para_alg_impl

# Skip the lattice estimator: we only want the cheap parameter + size
# computation here. With the estimator disabled, build_estimator_objects returns
# None and the security estimates come back None (we ignore them and keep the
# stored old values).
para_alg_impl.ESTIMATOR_AVAILABLE = False

from para_alg_impl import compute_parameters, ParameterValidationError  # noqa: E402

RESULTS_DIR = SCRIPT_DIR / "results"

# inputs fields produced by the parameter/size algorithm (everything except the
# raw knobs n/q/ell/m/sigma/alpha_h/target_security).
DERIVED_FIELDS = ("bk", "alpha_1", "r", "mu_s", "v_s", "bs", "bv", "sigma_h", "a_h")
RAW_FIELDS = ("n", "q", "ell", "m", "sigma", "alpha_h")

SIZE_TAG = "SizeAlg=new"
SEC_TAG = "SecAlg=old"

stats = {
    "files": 0,
    "records": 0,
    "updated": 0,
    "skipped_no_outputs": 0,
    "skipped_error": 0,
}
errors: list[tuple[str, str, dict]] = []


def recompute_record(rec: dict, fname: str) -> bool:
    """Update rec in place. Return True if its sizes were recomputed."""
    inputs = rec.get("inputs")
    outputs = rec.get("outputs")
    # Failed / malformed records (no outputs dict) are left untouched & untagged.
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        stats["skipped_no_outputs"] += 1
        return False

    try:
        n = int(inputs["n"])
        q = int(inputs["q"])
        ell = int(inputs["ell"])
        m = int(inputs["m"])
        sigma = float(inputs["sigma"])
        alpha_h = int(inputs["alpha_h"])
    except (KeyError, TypeError, ValueError) as exc:
        stats["skipped_error"] += 1
        errors.append((fname, f"bad inputs: {exc!r}", dict(inputs)))
        return False

    try:
        res = compute_parameters(n, q, ell, m, sigma, alpha_h).result
    except ParameterValidationError as exc:
        stats["skipped_error"] += 1
        errors.append((fname, str(exc), {k: inputs.get(k) for k in RAW_FIELDS}))
        return False

    # Refresh the size-algorithm derived parameters in inputs.
    for key in DERIVED_FIELDS:
        if key in inputs:
            inputs[key] = getattr(res, key)

    # Recompute only the size outputs; leave LWE/SIS security as-is (old).
    outputs["PkBytes"] = res.pk_bytes
    outputs["SignBytes"] = res.sign_bytes
    outputs["CombinedBytes"] = res.combined_bytes

    tags = rec.get("tags")
    if not isinstance(tags, list):
        tags = []
    if SIZE_TAG not in tags:
        tags.append(SIZE_TAG)
    if SEC_TAG not in tags:
        tags.append(SEC_TAG)
    rec["tags"] = tags

    stats["updated"] += 1
    return True


def process_jsonl(path: Path) -> None:
    out_lines: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            stats["records"] += 1
            recompute_record(rec, path.name)
            out_lines.append(json.dumps(rec, ensure_ascii=False))
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    stats["files"] += 1


def process_data_json(path: Path) -> None:
    arr = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(arr, list):
        return
    for rec in arr:
        if isinstance(rec, dict):
            stats["records"] += 1
            recompute_record(rec, path.name)
    path.write_text(json.dumps(arr, ensure_ascii=False), encoding="utf-8")
    stats["files"] += 1


def main() -> int:
    for path in sorted(RESULTS_DIR.rglob("*.jsonl")):
        process_jsonl(path)
    for path in sorted(RESULTS_DIR.rglob("*.data.json")):
        process_data_json(path)

    print(json.dumps(stats, indent=2))
    if errors:
        print(f"\n{len(errors)} record(s) could not be recomputed (left unchanged):")
        for fname, msg, ctx in errors[:50]:
            print(f"  [{fname}] {msg} :: {ctx}")
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
