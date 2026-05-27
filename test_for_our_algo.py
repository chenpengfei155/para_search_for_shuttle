#!/usr/bin/env python3

from __future__ import annotations

import json

from para_alg_impl import ParameterValidationError, compute_parameters


TEST_PARAMS = {
    "n": 256,
    "q": 13313,
    "ell": 3,
    "m": 2,
    "sigma": 0.7071067811865476,
    "alpha_h": 128,
}


def main() -> None:
    try:
        artifacts = compute_parameters(**TEST_PARAMS)
    except ParameterValidationError as exc:
        print(f"invalid: {exc}")
        return

    payload = {
        "inputs": TEST_PARAMS,
        "outputs": artifacts.result.to_dict(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()