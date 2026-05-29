#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEX_FILE="para_alg_describe.tex"
PDF_FILE="para_alg_describe.pdf"

if command -v xelatex >/dev/null 2>&1; then
    LATEX_BIN="xelatex"
elif command -v lualatex >/dev/null 2>&1; then
    LATEX_BIN="lualatex"
else
    echo "Neither xelatex nor lualatex was found." >&2
    exit 1
fi

cd "$SCRIPT_DIR"
"$LATEX_BIN" -interaction=nonstopmode -halt-on-error "$TEX_FILE"
echo "Built: $SCRIPT_DIR/$PDF_FILE"