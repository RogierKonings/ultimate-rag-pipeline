#!/bin/bash
#
# PostgreSQL Backup Script for RAG Pipeline
#
# Creates compressed backups with timestamp and manages retention.
# Backups are stored in the specified backup directory.
#
# Usage:
#   ./postgres-backup.sh
#
# Environment Variables:
#   POSTGRES_HOST     - Database host (default: localhost)
#   POSTGRES_PORT     - Database port (default: 5432)
#   POSTGRES_USER     - Database user (default: raguser)
#   POSTGRES_DB       - Database name (default: ragpipeline)
#   PGPASSWORD        - Database password (required)
#   BACKUP_DIR        - Backup directory (default: /backups/postgres)
#   RETENTION_DAYS    - Days to retain backups (default: 7)
#

set -euo pipefail

# Configuration with defaults
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-raguser}"
POSTGRES_DB="${POSTGRES_DB:-ragpipeline}"
BACKUP_DIR="${BACKUP_DIR:-/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Check required environment
if [ -z "${PGPASSWORD:-}" ]; then
    log "ERROR: PGPASSWORD environment variable is required"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

log "Starting backup of database '${POSTGRES_DB}' from ${POSTGRES_HOST}:${POSTGRES_PORT}"

# Create backup with compression
if pg_dump \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --format=plain \
    --no-owner \
    --no-privileges \
    | gzip > "${BACKUP_FILE}"; then
    
    BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    log "Backup completed successfully: ${BACKUP_FILE} (${BACKUP_SIZE})"
else
    log "ERROR: Backup failed"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# Cleanup old backups
log "Cleaning up backups older than ${RETENTION_DAYS} days"
DELETED_COUNT=$(find "${BACKUP_DIR}" -name "${POSTGRES_DB}_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -delete -print | wc -l)
log "Deleted ${DELETED_COUNT} old backup(s)"

# List remaining backups
log "Current backups:"
ls -lh "${BACKUP_DIR}"/${POSTGRES_DB}_*.sql.gz 2>/dev/null || log "No backups found"

log "Backup process completed"
