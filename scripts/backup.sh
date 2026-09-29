#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${1:-./data/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TARGET_ARCHIVE="${BACKUP_DIR}/legal_rag_backup_${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

echo "[*] Creating atomic knowledge base backup..."
tar -czf "${TARGET_ARCHIVE}" -C "./data" store/

echo "[✓] Backup created successfully: ${TARGET_ARCHIVE}"
echo "    Size: $(du -sh "${TARGET_ARCHIVE}" | cut -f1)"
