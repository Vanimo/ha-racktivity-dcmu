#!/usr/bin/env bash
# The checks CI runs. CI, the Claude Code hook and developers all use this script.
#
#   tools/check.sh            # lint, formatting, types, tests
#
# Python: $PYTHON if set, else ./venv or ./.venv, else python3 on PATH.
# Install the tools with: pip install -r requirements_test.txt
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${PYTHON:-}" ]]; then
  for candidate in venv/bin/python .venv/bin/python; do
    [[ -x "$candidate" ]] && PYTHON="$candidate" && break
  done
  PYTHON="${PYTHON:-python3}"
fi

for module in ruff mypy pytest; do
  if ! "$PYTHON" -m "$module" --version >/dev/null 2>&1; then
    echo "check.sh: '$module' is not installed for $PYTHON." >&2
    echo "Run: $PYTHON -m pip install -r requirements_test.txt (or set PYTHON=...)" >&2
    exit 1
  fi
done

step() { echo "== $1"; shift; "$@"; }
step "Lint"        "$PYTHON" -m ruff check .
step "Formatting"  "$PYTHON" -m ruff format --check .
step "Type check"  "$PYTHON" -m mypy custom_components/racktivity_dcmu
step "Tests"       "$PYTHON" -m pytest -q
