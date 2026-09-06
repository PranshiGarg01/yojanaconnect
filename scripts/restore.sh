#!/bin/bash
# Restores the database from a backup file created by backup.sh.
# Usage: ./scripts/restore.sh backups/yojanaconnect_backup_20260101_120000.sql

set -e
cd "$(dirname "$0")/.."
export $(grep -v '^#' .env | xargs)

if [ -z "$1" ]; then
    echo "Usage: ./scripts/restore.sh <path-to-backup-file.sql>"
    exit 1
fi

echo "Restoring $1 into $DB_NAME ..."
PGPASSWORD=$DB_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" < "$1"
echo "Restore complete."