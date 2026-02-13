#!/usr/bin/env bash
# Time-gated runtime import check — runs once per week on push.
# Stores last-run timestamp in .import_check_timestamp.
# Exit 0 (pass) if already checked recently; runs full check otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TIMESTAMP_FILE="$APP_DIR/.import_check_timestamp"
INTERVAL_SECONDS=$((7 * 24 * 3600))  # 7 days

# Find bench Python
BENCH_DIR="$(cd "$APP_DIR/../.." && pwd)"
PYTHON="$BENCH_DIR/env/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "⚠️  Bench Python not found at $PYTHON — skipping import check"
    exit 0
fi

# Check if we've run recently
if [ -f "$TIMESTAMP_FILE" ]; then
    last_run=$(cat "$TIMESTAMP_FILE")
    now=$(date +%s)
    elapsed=$(( now - last_run ))
    if [ "$elapsed" -lt "$INTERVAL_SECONDS" ]; then
        days_ago=$(( elapsed / 86400 ))
        echo "⏭️  Runtime import check: last run ${days_ago}d ago (runs weekly)"
        exit 0
    fi
fi

echo "🔍 Running weekly runtime import validation..."
if "$PYTHON" "$SCRIPT_DIR/check_all_imports.py"; then
    # Record successful run
    date +%s > "$TIMESTAMP_FILE"
    echo "✅ Import check passed — next check in 7 days"
else
    echo "❌ Import errors found — fix before pushing"
    exit 1
fi
