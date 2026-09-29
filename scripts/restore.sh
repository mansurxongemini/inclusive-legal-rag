#!/usr/bin/env bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <path_to_backup_archive.tar.gz>"
  exit 1
fi

ARCHIVE_PATH="$1"
if [ ! -f "${ARCHIVE_PATH}" ]; then
  echo "[!] Backup archive does not exist: ${ARCHIVE_PATH}"
  exit 1
fi

echo "[*] Restoring knowledge base from ${ARCHIVE_PATH}..."
mkdir -p "./data"
tar -xzf "${ARCHIVE_PATH}" -C "./data"

echo "[✓] Restore completed successfully!"
ls -la "./data/store"
