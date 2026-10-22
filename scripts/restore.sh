#!/usr/bin/env bash
# Restore data/store from a backup folder or archive made by backup.sh. The server must be stopped.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-.venv/bin/python}" scripts/restore_store.py "$@"
