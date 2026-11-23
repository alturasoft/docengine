#!/usr/bin/env bash
# ==============================================================================
# DocEngine — Cleanup orphaned temporary upload files older than 24 hours
# Schedule via cron (e.g., 0 3 * * * /opt/docengine/deploy/cleanup-uploads.sh)
# ==============================================================================
set -euo pipefail

UPLOADS_DIR="${DOCENGINE_OUTPUT_OUTPUT_DIR:-/opt/docengine/outputs}/_uploads"

if [[ -d "${UPLOADS_DIR}" ]]; then
    find "${UPLOADS_DIR}" -type f -mmin +1440 -delete
fi
