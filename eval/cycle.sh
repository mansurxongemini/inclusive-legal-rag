#!/usr/bin/env bash
# One regression cycle: the full test suite, the gold set (cached model responses) and the server check (memory,
# robustness). The result is one row of EVAL_HISTORY.md; the label carries the test and server-check counts.
#
#   eval/cycle.sh "cycle 3: what changed"
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LABEL="${1:-cycle}"
LOG=eval/reports/cycle_$(date +%Y%m%d_%H%M%S).log
mkdir -p eval/reports

TESTS=$($PY -m pytest -q -p no:cacheprovider 2>&1 | tail -1)
echo "pytest: $TESTS" | tee "$LOG"
SERVER=$($PY eval/check_server.py 2>&1 | tee -a "$LOG" | tail -1)
echo "server: $SERVER" | tee -a "$LOG"
SHORT_TESTS=$(echo "$TESTS" | sed -E 's/ in [0-9.]+s//; s/=//g; s/^ +//')
SHORT_SERVER=$(echo "$SERVER" | grep -oE '^[0-9]+/[0-9]+')
$PY eval/run_eval.py --max-spend "${MAX_SPEND:-0.5}" --label "$LABEL [tests: $SHORT_TESTS; server: $SHORT_SERVER]" \
    --history 2>&1 | grep -v "lance::\| INFO " | tee -a "$LOG" | tail -6
