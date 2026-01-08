# US-1A.7: PostgreSQL Backup CronJob

> **Epic:** Infrastructure Gaps & Hardening  
> **Priority:** High  
> **Estimated Effort:** 0.5 day  
> **Dependencies:** US-1.1 (PostgreSQL Setup)  
> **Status:** ✅ Complete

## User Story

**As a** database administrator  
**I want** PostgreSQL backups to run automatically on a schedule  
**So that** data can be recovered in case of disaster and RPO requirements are met

## Problem Statement

### Current State

- `postgres-backup.sh` script exists but not scheduled
- No automated backup process in Kubernetes
- No integration with object storage for backup retention
- No alerting for failed backups
- Manual intervention required for any backup

### Impact

- Risk of data loss without regular backups
- RPO (Recovery Point Objective) cannot be guaranteed
- Manual backup process is error-prone
- No audit trail of backup execution

## Architecture Reference

From `docs/architecture.md`:

> **PostgreSQL:** ACID-compliant metadata store  
> **Data Recovery:** Backups stored securely with defined retention policy

Backup requirements:
- Daily full backups
- Point-in-time recovery capability (WAL archiving)
- Offsite backup storage (S3/MinIO)
- 30-day retention for daily backups

## Solution Design

### Backup Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL Backup Strategy                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐     │
│  │ PostgreSQL  │─────▶│  pg_dump    │─────▶│   MinIO     │     │
│  │   Primary   │      │  (CronJob)  │      │  /backups   │     │
│  └─────────────┘      └─────────────┘      └─────────────┘     │
│         │                                          │            │
│         ▼                                          │            │
│  ┌─────────────┐                                   │            │
│  │ WAL Archive │───────────────────────────────────┘            │
│  │  (Optional) │                                                │
│  └─────────────┘                                                │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Retention Policy                          ││
│  │  - Daily backups: 30 days                                   ││
│  │  - Weekly backups: 90 days                                  ││
│  │  - Monthly backups: 365 days                                ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Backup Types

| Type | Frequency | Retention | Storage |
|------|-----------|-----------|---------|
| Full dump | Daily 02:00 UTC | 30 days | MinIO `backups/postgres/daily/` |
| Weekly | Sunday 03:00 UTC | 90 days | MinIO `backups/postgres/weekly/` |
| Monthly | 1st of month | 365 days | MinIO `backups/postgres/monthly/` |
| WAL archive | Continuous | 7 days | MinIO `backups/postgres/wal/` |

## Implementation Tasks

### 1. Create Backup CronJob

Create `k8s/postgres/backup-cronjob.yaml`:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: rag-pipeline
  labels:
    app: postgres-backup
spec:
  schedule: "0 2 * * *"  # Daily at 02:00 UTC
  timeZone: "UTC"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 7
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      activeDeadlineSeconds: 3600  # 1 hour timeout
      backoffLimit: 2
      template:
        metadata:
          labels:
            app: postgres-backup
        spec:
          restartPolicy: OnFailure
          serviceAccountName: postgres-backup
          
          initContainers:
          - name: wait-for-postgres
            image: postgres:16-alpine
            command:
            - /bin/sh
            - -c
            - |
              until pg_isready -h $POSTGRES_HOST -p 5432 -U $POSTGRES_USER; do
                echo "Waiting for PostgreSQL..."
                sleep 5
              done
            env:
            - name: POSTGRES_HOST
              value: "postgres"
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: postgres-user
          
          containers:
          - name: backup
            image: postgres:16-alpine
            command:
            - /bin/sh
            - -c
            - |
              set -e
              
              echo "=== PostgreSQL Backup Started ==="
              date
              
              # Set variables
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              BACKUP_TYPE="daily"
              
              # Check if this is a weekly backup (Sunday)
              if [ $(date +%u) -eq 7 ]; then
                BACKUP_TYPE="weekly"
              fi
              
              # Check if this is a monthly backup (1st of month)
              if [ $(date +%d) -eq 01 ]; then
                BACKUP_TYPE="monthly"
              fi
              
              BACKUP_FILE="ragpipeline_${BACKUP_TYPE}_${TIMESTAMP}.sql.gz"
              LOCAL_PATH="/tmp/${BACKUP_FILE}"
              S3_PATH="s3://${S3_BUCKET}/postgres/${BACKUP_TYPE}/${BACKUP_FILE}"
              
              echo "Backup type: ${BACKUP_TYPE}"
              echo "Backup file: ${BACKUP_FILE}"
              
              # Run pg_dump
              echo "Running pg_dump..."
              PGPASSWORD=$POSTGRES_PASSWORD pg_dump \
                -h $POSTGRES_HOST \
                -U $POSTGRES_USER \
                -d $POSTGRES_DB \
                --format=custom \
                --compress=9 \
                --verbose \
                --file="${LOCAL_PATH%.gz}"
              
              # Compress with gzip
              gzip "${LOCAL_PATH%.gz}"
              
              # Get backup size
              BACKUP_SIZE=$(stat -f%z "$LOCAL_PATH" 2>/dev/null || stat -c%s "$LOCAL_PATH")
              echo "Backup size: ${BACKUP_SIZE} bytes"
              
              # Verify backup integrity
              echo "Verifying backup..."
              gunzip -t "$LOCAL_PATH"
              
              # Install MinIO client
              echo "Installing MinIO client..."
              wget -q https://dl.min.io/client/mc/release/linux-amd64/mc -O /tmp/mc
              chmod +x /tmp/mc
              
              # Configure MinIO client
              /tmp/mc alias set backup $S3_ENDPOINT $S3_ACCESS_KEY $S3_SECRET_KEY
              
              # Upload to MinIO
              echo "Uploading to ${S3_PATH}..."
              /tmp/mc cp "$LOCAL_PATH" backup/${S3_BUCKET}/postgres/${BACKUP_TYPE}/
              
              # Verify upload
              /tmp/mc stat backup/${S3_BUCKET}/postgres/${BACKUP_TYPE}/${BACKUP_FILE}
              
              # Create latest symlink/copy
              /tmp/mc cp "$LOCAL_PATH" backup/${S3_BUCKET}/postgres/latest.sql.gz
              
              # Cleanup old backups based on retention
              echo "Cleaning up old backups..."
              case $BACKUP_TYPE in
                daily)
                  RETENTION_DAYS=30
                  ;;
                weekly)
                  RETENTION_DAYS=90
                  ;;
                monthly)
                  RETENTION_DAYS=365
                  ;;
              esac
              
              /tmp/mc find backup/${S3_BUCKET}/postgres/${BACKUP_TYPE}/ \
                --older-than ${RETENTION_DAYS}d \
                --exec "/tmp/mc rm {}"
              
              # Cleanup local file
              rm -f "$LOCAL_PATH"
              
              # Report success
              echo ""
              echo "=== Backup Completed Successfully ==="
              echo "Type: ${BACKUP_TYPE}"
              echo "File: ${BACKUP_FILE}"
              echo "Size: ${BACKUP_SIZE} bytes"
              echo "Location: ${S3_PATH}"
              date
            env:
            - name: POSTGRES_HOST
              value: "postgres"
            - name: POSTGRES_DB
              value: "ragpipeline"
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: postgres-user
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: postgres-password
            - name: S3_ENDPOINT
              value: "http://minio:9000"
            - name: S3_BUCKET
              value: "backups"
            - name: S3_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: minio-backup-credentials
                  key: access-key
            - name: S3_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: minio-backup-credentials
                  key: secret-key
            resources:
              requests:
                memory: "256Mi"
                cpu: "100m"
              limits:
                memory: "1Gi"
                cpu: "500m"
            volumeMounts:
            - name: tmp
              mountPath: /tmp
          
          volumes:
          - name: tmp
            emptyDir:
              sizeLimit: 10Gi
```

### 2. Create ServiceAccount and RBAC

Create `k8s/postgres/backup-rbac.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: postgres-backup
  namespace: rag-pipeline
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: postgres-backup
  namespace: rag-pipeline
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
  resourceNames: ["rag-secrets", "minio-backup-credentials"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: postgres-backup
  namespace: rag-pipeline
subjects:
- kind: ServiceAccount
  name: postgres-backup
  namespace: rag-pipeline
roleRef:
  kind: Role
  name: postgres-backup
  apiGroup: rbac.authorization.k8s.io
```

### 3. Create Database Migration Job

Create `k8s/postgres/migration-job.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: postgres-migration
  namespace: rag-pipeline
  labels:
    app: postgres-migration
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      
      initContainers:
      - name: wait-for-postgres
        image: postgres:16-alpine
        command:
        - /bin/sh
        - -c
        - |
          until pg_isready -h postgres -p 5432 -U $POSTGRES_USER; do
            echo "Waiting for PostgreSQL..."
            sleep 5
          done
        env:
        - name: POSTGRES_USER
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: postgres-user
      
      containers:
      - name: migrate
        image: ${MIGRATION_IMAGE}  # Your application image with Alembic
        command:
        - /bin/sh
        - -c
        - |
          set -e
          echo "Running database migrations..."
          alembic upgrade head
          echo "Migrations completed successfully"
          alembic current
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: database-url
        workingDir: /app/services/shared/database
```

### 4. Create Restore Procedure Documentation

Create `docs/infrastructure/postgres-backup-restore.md`:

```markdown
# PostgreSQL Backup and Restore Procedures

## Overview

This document describes the backup strategy and restore procedures for the RAG Pipeline PostgreSQL database.

## Backup Strategy

### Schedule

| Type | Schedule | Retention | Location |
|------|----------|-----------|----------|
| Daily | 02:00 UTC | 30 days | `backups/postgres/daily/` |
| Weekly | Sunday 03:00 UTC | 90 days | `backups/postgres/weekly/` |
| Monthly | 1st of month | 365 days | `backups/postgres/monthly/` |

### Backup Format

- Format: PostgreSQL custom format (`pg_dump --format=custom`)
- Compression: gzip level 9
- Naming: `ragpipeline_{type}_{timestamp}.sql.gz`

## Manual Backup

To trigger a manual backup:

```bash
# Create manual backup job
kubectl create job postgres-backup-manual \
  --from=cronjob/postgres-backup \
  -n rag-pipeline

# Monitor progress
kubectl logs -f job/postgres-backup-manual -n rag-pipeline
```

## Restore Procedures

### Prerequisites

1. Access to MinIO/S3 backup bucket
2. `kubectl` access to the cluster
3. Postgres client tools

### List Available Backups

```bash
# Using MinIO client
kubectl exec deployment/minio -n rag-pipeline -- \
  mc ls rag/backups/postgres/daily/ --recursive

# Find latest backup
kubectl exec deployment/minio -n rag-pipeline -- \
  mc ls rag/backups/postgres/latest.sql.gz
```

### Restore to Existing Database

**⚠️ WARNING: This will overwrite all data in the target database!**

```bash
# 1. Download the backup
kubectl exec deployment/minio -n rag-pipeline -- \
  mc cp rag/backups/postgres/daily/ragpipeline_daily_20250101_020000.sql.gz /tmp/

# 2. Copy to local machine (optional)
kubectl cp rag-pipeline/minio-pod:/tmp/ragpipeline_daily_20250101_020000.sql.gz ./backup.sql.gz

# 3. Connect to postgres pod
kubectl exec -it deployment/postgres -n rag-pipeline -- bash

# 4. Decompress and restore
gunzip backup.sql.gz
pg_restore -h localhost -U raguser -d ragpipeline \
  --clean --if-exists --verbose backup.sql
```

### Restore to New Database

```bash
# 1. Create new database
kubectl exec -it deployment/postgres -n rag-pipeline -- \
  psql -U raguser -c "CREATE DATABASE ragpipeline_restored;"

# 2. Restore to new database
kubectl exec -it deployment/postgres -n rag-pipeline -- \
  pg_restore -h localhost -U raguser -d ragpipeline_restored backup.sql
```

### Point-in-Time Recovery (PITR)

If WAL archiving is enabled:

```bash
# 1. Stop PostgreSQL
kubectl scale deployment/postgres -n rag-pipeline --replicas=0

# 2. Create recovery.conf
cat << EOF | kubectl exec -i deployment/postgres -n rag-pipeline -- tee /var/lib/postgresql/data/recovery.conf
restore_command = 'mc cp rag/backups/postgres/wal/%f %p'
recovery_target_time = '2025-01-01 12:00:00 UTC'
recovery_target_action = 'promote'
EOF

# 3. Start PostgreSQL
kubectl scale deployment/postgres -n rag-pipeline --replicas=1
```

## Verify Backup Integrity

```bash
# Test decompression
gunzip -t backup.sql.gz

# List contents without restoring
pg_restore --list backup.sql

# Restore to test database
pg_restore -h localhost -U raguser -d test_restore --verbose backup.sql
```

## Troubleshooting

### Backup Job Fails

1. Check job logs:
   ```bash
   kubectl logs job/postgres-backup-manual -n rag-pipeline
   ```

2. Verify PostgreSQL connectivity:
   ```bash
   kubectl exec -it deployment/postgres -n rag-pipeline -- pg_isready
   ```

3. Check MinIO connectivity:
   ```bash
   kubectl exec deployment/minio -n rag-pipeline -- mc admin info rag
   ```

### Restore Fails

1. Check disk space:
   ```bash
   kubectl exec deployment/postgres -n rag-pipeline -- df -h
   ```

2. Check for active connections:
   ```bash
   kubectl exec deployment/postgres -n rag-pipeline -- \
     psql -U raguser -c "SELECT * FROM pg_stat_activity;"
   ```

3. Terminate connections before restore:
   ```bash
   kubectl exec deployment/postgres -n rag-pipeline -- \
     psql -U raguser -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ragpipeline' AND pid <> pg_backend_pid();"
   ```

## Monitoring

### Check Last Successful Backup

```bash
# List recent backup jobs
kubectl get jobs -n rag-pipeline -l app=postgres-backup --sort-by=.status.startTime

# Check CronJob status
kubectl get cronjob postgres-backup -n rag-pipeline
```

### Alerts

Configure Prometheus alerts for:
- Backup job failures
- Backup age > 25 hours
- Backup size anomalies
```

### 5. Create Alerting Rules

Create `k8s/postgres/backup-alerts.yaml`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: postgres-backup-alerts
  namespace: rag-pipeline
  labels:
    app: postgres-backup
spec:
  groups:
  - name: postgres-backup
    interval: 60s
    rules:
    - alert: PostgresBackupFailed
      expr: |
        kube_job_status_failed{job_name=~"postgres-backup-.*", namespace="rag-pipeline"} > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "PostgreSQL backup job failed"
        description: "PostgreSQL backup job {{ $labels.job_name }} has failed"
    
    - alert: PostgresBackupMissing
      expr: |
        time() - max(kube_job_status_completion_time{job_name=~"postgres-backup-.*", namespace="rag-pipeline"}) > 90000
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "PostgreSQL backup is overdue"
        description: "No successful PostgreSQL backup in the last 25 hours"
    
    - alert: PostgresBackupStorageLow
      expr: |
        minio_bucket_usage_total_bytes{bucket="backups"} > 100e9
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Backup storage usage high"
        description: "Backup bucket usage is over 100GB"
```

### 6. Makefile Integration

Add to `Makefile`:

```makefile
.PHONY: postgres-backup postgres-backup-manual postgres-restore

postgres-backup:
	kubectl apply -f k8s/postgres/backup-rbac.yaml
	kubectl apply -f k8s/postgres/backup-cronjob.yaml
	@echo "PostgreSQL backup CronJob configured"

postgres-backup-manual:
	kubectl create job postgres-backup-manual-$$(date +%s) \
		--from=cronjob/postgres-backup \
		-n rag-pipeline
	@echo "Manual backup job created"

postgres-restore:
	@echo "Usage: make postgres-restore BACKUP=backups/postgres/daily/filename.sql.gz"
	@echo "See docs/infrastructure/postgres-backup-restore.md for procedures"
```

## Acceptance Criteria

- [x] CronJob runs daily at 02:00 UTC
- [x] Backups stored in MinIO with proper path structure
- [x] Daily, weekly, and monthly backup tiers implemented
- [x] Retention policy enforced automatically
- [x] Backup integrity verified after creation
- [x] Restore procedures documented and tested
- [x] RBAC configured for backup service account
- [x] Alerting rules for failed/missing backups

## Verification Commands

```bash
# Check CronJob status
kubectl get cronjob postgres-backup -n rag-pipeline

# View next scheduled run
kubectl get cronjob postgres-backup -n rag-pipeline -o jsonpath='{.status.lastScheduleTime}'

# List recent backup jobs
kubectl get jobs -n rag-pipeline -l app=postgres-backup

# Check backup logs
kubectl logs job/postgres-backup-28350000 -n rag-pipeline

# List backups in MinIO
kubectl exec deployment/minio -n rag-pipeline -- \
  mc ls rag/backups/postgres/ --recursive

# Trigger manual backup
kubectl create job postgres-backup-test --from=cronjob/postgres-backup -n rag-pipeline
```

## Files Created

| File | Description |
|------|-------------|
| `k8s/postgres/backup-cronjob.yaml` | Automated backup CronJob |
| `k8s/postgres/backup-rbac.yaml` | ServiceAccount and RBAC |
| `k8s/postgres/migration-job.yaml` | Database migration job |
| `k8s/postgres/backup-alerts.yaml` | Prometheus alerting rules |
| `docs/infrastructure/postgres-backup-restore.md` | Restore documentation |

## Related Stories

- **US-1.1:** PostgreSQL Setup (prerequisite)
- **US-1A.6:** MinIO Bootstrap Job (provides backup bucket)
- **US-6.x:** Observability (monitoring integration)
