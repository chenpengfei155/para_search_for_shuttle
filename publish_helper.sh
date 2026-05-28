#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

publish results/param_ideal.data.json SHUTTLE/param_ideal.data.json
publish results/param_ideal.html SHUTTLE/param_ideal.html
publish results/param_all.data.json SHUTTLE/param_all.data.json
publish results/param_all.html SHUTTLE/param_all.html