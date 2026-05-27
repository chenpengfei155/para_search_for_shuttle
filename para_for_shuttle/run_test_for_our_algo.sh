#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

cd "$SCRIPT_DIR"
python3 test_for_our_algo.py "$@"