#!/usr/bin/env bash
# Consistent backup of data/store (SQLite online backup + verified LanceDB copy). See scripts/backup_store.py --help.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-.venv/bin/python}" scripts/backup_store.py "$@"
