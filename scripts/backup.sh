#!/bin/bash
# Backs up the database using PostgreSQL's native pg_dump tool.
# Reads DB credentials from .env so nothing is hardcoded.

set -e
cd "$(dirname "$0")/.."
export $(grep -v '^#' .env | xargs)

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backups/yojanaconnect_backup_${TIMESTAMP}.sql"
mkdir -p backups

echo "Backing up $DB_NAME to $BACKUP_FILE ..."
PGPASSWORD=$DB_PASSWORD pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"
echo "Done. Backup saved to $BACKUP_FILE"