#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$PROJECT_ROOT/.env.test" ]; then
    source "$PROJECT_ROOT/.env.test"
else
    echo "ERROR: .env.test file not found!"
    echo "Expected: $PROJECT_ROOT/.env.test"
    exit 1
fi

echo "=========================================="
echo "Initializing Test Database"
echo "=========================================="

BACKUP_FILE="${BACKUP_DIR}/${DB_BACKUP_FILE}"

if [ -f "$BACKUP_FILE" ]; then
    echo "Found backup file: $BACKUP_FILE"
    echo "Restoring database backup..."

    pg_restore \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --no-owner \
        --no-privileges \
        --verbose \
        "$BACKUP_FILE" 2>&1 | grep -v "^pg_restore: warning:" || true

    echo "Database restoration completed!"
    echo "=========================================="
else
    echo "WARNING: Backup file not found at $BACKUP_FILE"
    echo "Database will be initialized empty."
    echo "=========================================="
fi
