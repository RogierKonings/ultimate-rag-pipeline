# PostgreSQL Backup and Restore Procedures

## Overview

This document describes the backup and restore procedures for the RAG pipeline PostgreSQL database. Backups are critical for disaster recovery and should be tested regularly.

## Backup Strategy

| Type | Frequency | Retention | Storage Path |
|------|-----------|-----------|--------------|
| Daily | Every day at 02:00 UTC | 30 days | `backups/postgres/daily/` |
| Weekly | Sundays at 02:00 UTC | 90 days | `backups/postgres/weekly/` |
| Monthly | 1st of month at 02:00 UTC | 365 days | `backups/postgres/monthly/` |
| Latest | Always current | N/A | `backups/postgres/latest.dump` |

The backup type is automatically determined based on the day:
- **1st of month** → Monthly backup (1 year retention)
- **Sundays** → Weekly backup (90 day retention)
- **All other days** → Daily backup (30 day retention)

## Backup Procedures

### Local Development

```bash
# Create a backup
./scripts/postgres-backup.sh

# Or using docker-compose
docker-compose exec postgres pg_dump -U raguser -d ragpipeline | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Kubernetes

#### Manual Backup

```bash
# Get the postgres pod name
POSTGRES_POD=$(kubectl get pods -n rag-pipeline -l app=postgres -o jsonpath='{.items[0].metadata.name}')

# Create backup
kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  pg_dump -U raguser -d ragpipeline --format=plain --no-owner --no-privileges \
  | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz
```

#### Automated Backups (CronJob)

The `postgres-backup-cronjob.yaml` runs daily backups at 2:00 AM UTC. Backups are stored in the MinIO `backups` bucket with tiered retention.

```bash
# Deploy backup CronJob
make postgres-backup

# Check backup job status
kubectl get cronjobs -n rag-pipeline

# View recent backup job runs
kubectl get jobs -n rag-pipeline -l app=postgres-backup

# Check logs of last backup
kubectl logs -n rag-pipeline -l app=postgres-backup --tail=50

# Trigger manual backup
make postgres-backup-manual

# List backups by tier
kubectl exec deployment/minio -n rag-pipeline -- mc ls rag/backups/postgres/daily/
kubectl exec deployment/minio -n rag-pipeline -- mc ls rag/backups/postgres/weekly/
kubectl exec deployment/minio -n rag-pipeline -- mc ls rag/backups/postgres/monthly/
```

---

## Restore Procedures

### Prerequisites

1. Access to the backup file (`.sql.gz`)
2. Database credentials
3. Target database must be accessible

### Local Development Restore

```bash
# Stop dependent services
docker-compose stop ingestion-service retrieval-service orchestrator-service

# Restore from backup
gunzip -c backup_20260104.sql.gz | docker-compose exec -T postgres psql -U raguser -d ragpipeline

# Or drop and recreate database for clean restore
docker-compose exec postgres psql -U raguser -d postgres -c "DROP DATABASE IF EXISTS ragpipeline;"
docker-compose exec postgres psql -U raguser -d postgres -c "CREATE DATABASE ragpipeline;"
gunzip -c backup_20260104.sql.gz | docker-compose exec -T postgres psql -U raguser -d ragpipeline

# Restart services
docker-compose start ingestion-service retrieval-service orchestrator-service
```

### Kubernetes Restore

#### Step 1: Scale Down Dependent Services

```bash
# Scale down services that connect to the database
kubectl scale deployment -n rag-pipeline ingestion-service --replicas=0
kubectl scale deployment -n rag-pipeline retrieval-service --replicas=0
kubectl scale deployment -n rag-pipeline orchestrator-service --replicas=0
kubectl scale deployment -n rag-pipeline pgbouncer --replicas=0

# Wait for pods to terminate
kubectl wait --for=delete pod -l app=ingestion-service -n rag-pipeline --timeout=60s
```

#### Step 2: Restore the Database

```bash
# Get postgres pod name
POSTGRES_POD=$(kubectl get pods -n rag-pipeline -l app=postgres -o jsonpath='{.items[0].metadata.name}')

# Option A: Restore to existing database (preserves structure, may have conflicts)
gunzip -c backup_20260104.sql.gz | kubectl exec -i -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d ragpipeline

# Option B: Clean restore (drop and recreate database)
kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ragpipeline' AND pid <> pg_backend_pid();"

kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d postgres -c "DROP DATABASE IF EXISTS ragpipeline;"

kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d postgres -c "CREATE DATABASE ragpipeline;"

gunzip -c backup_20260104.sql.gz | kubectl exec -i -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d ragpipeline
```

#### Step 3: Verify Restore

```bash
# Check table counts
kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d ragpipeline -c "SELECT 'documents' as table_name, COUNT(*) FROM documents UNION ALL SELECT 'chunks', COUNT(*) FROM chunks UNION ALL SELECT 'audit_logs', COUNT(*) FROM audit_logs;"

# Check for any errors in the restore
kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d ragpipeline -c "SELECT * FROM pg_stat_user_tables;"
```

#### Step 4: Scale Services Back Up

```bash
kubectl scale deployment -n rag-pipeline pgbouncer --replicas=2
kubectl scale deployment -n rag-pipeline ingestion-service --replicas=2
kubectl scale deployment -n rag-pipeline retrieval-service --replicas=3
kubectl scale deployment -n rag-pipeline orchestrator-service --replicas=3

# Verify all pods are running
kubectl get pods -n rag-pipeline
```

---

## Restore from MinIO Backup

If backups are stored in MinIO:

```bash
# Download backup from MinIO
kubectl run -n rag-pipeline mc-client --rm -it --image=minio/mc --restart=Never -- \
  sh -c "mc alias set minio http://minio:9000 \$MINIO_ACCESS_KEY \$MINIO_SECRET_KEY && \
         mc cp minio/backups/ragpipeline_20260104_020000.sql.gz /tmp/backup.sql.gz && \
         cat /tmp/backup.sql.gz" > backup.sql.gz

# Then follow the restore steps above
```

---

## Disaster Recovery Checklist

### Before Disaster (Preparation)

- [ ] Verify daily backup CronJob is running
- [ ] Test restore procedure monthly
- [ ] Ensure backup storage has sufficient space
- [ ] Document current database version and size

### During Disaster Recovery

1. [ ] Assess the damage and determine recovery point
2. [ ] Identify the correct backup to restore
3. [ ] Notify stakeholders of downtime
4. [ ] Scale down dependent services
5. [ ] Perform restore
6. [ ] Verify data integrity
7. [ ] Re-index Qdrant and OpenSearch if needed
8. [ ] Scale up services
9. [ ] Perform smoke tests
10. [ ] Document incident

### After Recovery

- [ ] Create post-incident report
- [ ] Update procedures if needed
- [ ] Consider additional safeguards

---

## Troubleshooting

### Common Issues

**Error: "database is being accessed by other users"**
```bash
# Terminate all connections before restore
kubectl exec -n rag-pipeline $POSTGRES_POD -- \
  psql -U raguser -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ragpipeline';"
```

**Error: "permission denied" during restore**
```bash
# Ensure you're using the correct user
# The backup script uses --no-owner --no-privileges to avoid this
```

**Restore is slow**
- For large databases, consider `pg_restore` with `--jobs` for parallel restore
- Use `pg_dump --format=custom` for backups intended for parallel restore

---

## Related Documents

- [Kubernetes Setup](kubernetes-setup.md)
- [Infrastructure Architecture](../architecture.md)
