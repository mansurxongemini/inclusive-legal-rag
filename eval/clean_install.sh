#!/usr/bin/env bash
# The README's local setup, step by step, in a fresh clone of the current commit (outside the repository):
# venv, dependencies, .env, test suite, knowledge base (one act from Lex.uz), server, /health and one question.
# The OpenRouter key is passed in the environment of the commands (read from this checkout's .env), never written.
#
#   eval/clean_install.sh /tmp/clean-rag        # exit 0 when every step worked
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:?usage: eval/clean_install.sh <empty folder>}"
rm -rf "$DEST"
BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
step() { echo; echo "== $*"; }

step "1. clone ($BRANCH @ $(git -C "$REPO" rev-parse --short HEAD)) and venv"
git clone -q --branch "$BRANCH" "$REPO" "$DEST"
cd "$DEST"
python3 -m venv .venv
step "2. dependencies"
.venv/bin/pip install -q -r requirements-dev.txt -c requirements.lock
.venv/bin/pip check
step "3. .env"
cp .env.example .env
step "4. tests"
.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -1
KEY="$("$REPO/.venv/bin/python" -c "import sys; sys.path.insert(0, '$REPO'); import os; os.chdir('$REPO'); from src.config import settings; print(settings.OPENROUTER_API_KEY)")"
step "5. knowledge base: one act from Lex.uz"
OPENROUTER_API_KEY="$KEY" SPEND_SCOPE=eval .venv/bin/python scripts/build_disability_corpus.py refresh \
    --law-ids law_disability_2020 --store-dir data/store 2>&1 | grep "refresh:"
.venv/bin/python scripts/audit_corpus.py >/dev/null && echo "corpus audit: ok"
step "6. server, /health, one question"
PORT=8793
OPENROUTER_API_KEY="$KEY" SPEND_SCOPE=eval HUQUQPLUS_SYNC_ENABLED=false \
    .venv/bin/python -m uvicorn src.api.app:app --host 127.0.0.1 --port $PORT > server.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
for _ in $(seq 1 120); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.5; done
curl -s "http://127.0.0.1:$PORT/health"; echo
curl -s -X POST "http://127.0.0.1:$PORT/api/v1/query" -H 'content-type: application/json' \
    -d '{"question": "I guruh nogironligi bo'"'"'lgan xodim haftasiga necha soat ishlaydi?"}' \
    | "$REPO/.venv/bin/python" -c "import json,sys; d=json.load(sys.stdin); print('answer ok:', bool(d.get('answer')), '| cited:', [c['canonical_id'] for c in d.get('citations', [])], '| refusal:', d.get('is_refusal'))"
grep -q "$KEY" server.log && { echo "KEY LEAKED INTO THE LOG"; exit 1; } || echo "key not in the server log"
echo; echo "CLEAN INSTALL OK"
