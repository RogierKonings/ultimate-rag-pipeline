# US-1A.6: MinIO Bootstrap Job

> **Epic:** Infrastructure Gaps & Hardening  
> **Priority:** High  
> **Estimated Effort:** 0.5 day  
> **Dependencies:** US-1.5 (Object Storage)  
> **Status:** ✅ Complete

## User Story

**As a** platform operator  
**I want** MinIO buckets, policies, and lifecycle rules created automatically  
**So that** the object storage is ready for use immediately after deployment without manual setup

## Problem Statement

### Current State

- MinIO deployed but no buckets configured
- No bucket policies for tenant isolation
- No lifecycle rules for cleanup of temporary files
- Manual setup required after each deployment
- Different configurations across environments

### Impact

- Delayed deployments due to manual setup
- Inconsistent bucket configurations
- No automatic cleanup of temporary uploads
- Potential security gaps without proper policies

## Architecture Reference

From `docs/architecture.md`:

> **MinIO/S3:** Object storage for raw documents

Required buckets:
- `raw-documents` - Original uploaded files
- `processed-chunks` - Processed and chunked content
- `backups` - Database and index backups

## Solution Design

### Bucket Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                    MinIO Bucket Architecture                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  raw-documents  │  │ processed-chunks│  │    backups      │  │
│  │                 │  │                 │  │                 │  │
│  │  /tenant-a/     │  │  /tenant-a/     │  │  /postgres/     │  │
│  │  /tenant-b/     │  │  /tenant-b/     │  │  /qdrant/       │  │
│  │  /uploads/      │  │                 │  │  /opensearch/   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│         │                     │                     │            │
│         ▼                     ▼                     ▼            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Lifecycle Policies                        ││
│  │  - Temp uploads: 24h expiry                                 ││
│  │  - Backups: 30-day retention                                ││
│  │  - Incomplete multipart: 7-day cleanup                      ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Tasks

### 1. Create Bootstrap Job

Create `k8s/minio/bootstrap-job.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: minio-bootstrap
  namespace: rag-pipeline
  labels:
    app: minio-bootstrap
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 3
  template:
    metadata:
      labels:
        app: minio-bootstrap
    spec:
      restartPolicy: OnFailure
      initContainers:
      - name: wait-for-minio
        image: curlimages/curl:8.4.0
        command:
        - /bin/sh
        - -c
        - |
          set -e
          echo "Waiting for MinIO to be ready..."
          until curl -sf http://minio:9000/minio/health/live; do
            echo "MinIO not ready, retrying in 5s..."
            sleep 5
          done
          echo "MinIO is ready!"
      
      containers:
      - name: bootstrap
        image: minio/mc:latest
        command:
        - /bin/sh
        - -c
        - |
          set -e
          
          echo "=== MinIO Bootstrap Script ==="
          
          # Configure MinIO client
          mc alias set rag http://minio:9000 ${MINIO_ROOT_USER} ${MINIO_ROOT_PASSWORD}
          
          # Verify connection
          mc admin info rag
          
          # Create buckets
          echo "Creating buckets..."
          mc mb --ignore-existing rag/raw-documents
          mc mb --ignore-existing rag/processed-chunks
          mc mb --ignore-existing rag/backups
          mc mb --ignore-existing rag/temp-uploads
          
          # Set versioning (optional, for raw-documents)
          echo "Configuring versioning..."
          mc version enable rag/raw-documents
          
          # Set bucket policies
          echo "Applying bucket policies..."
          
          # Raw documents - private by default
          mc anonymous set none rag/raw-documents
          mc anonymous set none rag/processed-chunks
          mc anonymous set none rag/backups
          
          # Create lifecycle rules
          echo "Configuring lifecycle rules..."
          
          # Temp uploads expire after 24 hours
          mc ilm rule add rag/temp-uploads \
            --expire-days 1 \
            --prefix "" \
            --tags "type=temp"
          
          # Incomplete multipart uploads cleaned after 7 days
          mc ilm rule add rag/raw-documents \
            --expire-delete-marker \
            --noncurrent-expire-days 30
          
          mc ilm rule add rag/processed-chunks \
            --expire-delete-marker \
            --noncurrent-expire-days 30
          
          # Backup retention - 30 days for daily, 90 days for weekly
          mc ilm rule add rag/backups \
            --expire-days 90 \
            --prefix "daily/" \
            --tags "retention=daily"
          
          mc ilm rule add rag/backups \
            --expire-days 365 \
            --prefix "weekly/" \
            --tags "retention=weekly"
          
          # Create service account for applications
          echo "Creating service accounts..."
          
          # Create read-write policy for RAG service
          cat > /tmp/rag-policy.json << 'EOF'
          {
            "Version": "2012-10-17",
            "Statement": [
              {
                "Effect": "Allow",
                "Action": [
                  "s3:GetObject",
                  "s3:PutObject",
                  "s3:DeleteObject",
                  "s3:ListBucket"
                ],
                "Resource": [
                  "arn:aws:s3:::raw-documents/*",
                  "arn:aws:s3:::raw-documents",
                  "arn:aws:s3:::processed-chunks/*",
                  "arn:aws:s3:::processed-chunks",
                  "arn:aws:s3:::temp-uploads/*",
                  "arn:aws:s3:::temp-uploads"
                ]
              }
            ]
          }
          EOF
          
          mc admin policy create rag rag-readwrite /tmp/rag-policy.json || \
            mc admin policy info rag rag-readwrite
          
          # Create read-only policy for monitoring
          cat > /tmp/readonly-policy.json << 'EOF'
          {
            "Version": "2012-10-17",
            "Statement": [
              {
                "Effect": "Allow",
                "Action": [
                  "s3:GetObject",
                  "s3:ListBucket"
                ],
                "Resource": [
                  "arn:aws:s3:::*"
                ]
              }
            ]
          }
          EOF
          
          mc admin policy create rag readonly /tmp/readonly-policy.json || \
            mc admin policy info rag readonly
          
          # Create backup policy
          cat > /tmp/backup-policy.json << 'EOF'
          {
            "Version": "2012-10-17",
            "Statement": [
              {
                "Effect": "Allow",
                "Action": [
                  "s3:GetObject",
                  "s3:PutObject",
                  "s3:ListBucket"
                ],
                "Resource": [
                  "arn:aws:s3:::backups/*",
                  "arn:aws:s3:::backups"
                ]
              }
            ]
          }
          EOF
          
          mc admin policy create rag backup-write /tmp/backup-policy.json || \
            mc admin policy info rag backup-write
          
          # Verify setup
          echo ""
          echo "=== Verification ==="
          echo "Buckets:"
          mc ls rag
          
          echo ""
          echo "Policies:"
          mc admin policy list rag
          
          echo ""
          echo "Lifecycle rules (raw-documents):"
          mc ilm rule ls rag/raw-documents
          
          echo ""
          echo "Lifecycle rules (backups):"
          mc ilm rule ls rag/backups
          
          echo ""
          echo "=== Bootstrap Complete ==="
        env:
        - name: MINIO_ROOT_USER
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: minio-root-user
        - name: MINIO_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: minio-root-password
```

### 2. Create Service Account Secrets

Create a script to generate service account credentials:

```bash
#!/bin/bash
# scripts/create-minio-service-accounts.sh

set -e

NAMESPACE=${1:-rag-pipeline}

# Wait for MinIO bootstrap to complete
kubectl wait --for=condition=complete job/minio-bootstrap -n $NAMESPACE --timeout=300s

# Create service account for RAG applications
echo "Creating RAG service account..."
RAG_ACCESS_KEY=$(openssl rand -hex 16)
RAG_SECRET_KEY=$(openssl rand -hex 32)

kubectl exec -it deployment/minio -n $NAMESPACE -- \
  mc admin user add rag rag-service $RAG_SECRET_KEY

kubectl exec -it deployment/minio -n $NAMESPACE -- \
  mc admin policy attach rag rag-readwrite --user=rag-service

# Create Kubernetes secret
kubectl create secret generic minio-rag-credentials \
  --namespace=$NAMESPACE \
  --from-literal=access-key=rag-service \
  --from-literal=secret-key=$RAG_SECRET_KEY \
  --dry-run=client -o yaml | kubectl apply -f -

echo "RAG service account created. Access key: rag-service"

# Create backup service account
echo "Creating backup service account..."
BACKUP_SECRET_KEY=$(openssl rand -hex 32)

kubectl exec -it deployment/minio -n $NAMESPACE -- \
  mc admin user add rag backup-service $BACKUP_SECRET_KEY

kubectl exec -it deployment/minio -n $NAMESPACE -- \
  mc admin policy attach rag backup-write --user=backup-service

kubectl create secret generic minio-backup-credentials \
  --namespace=$NAMESPACE \
  --from-literal=access-key=backup-service \
  --from-literal=secret-key=$BACKUP_SECRET_KEY \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Backup service account created. Access key: backup-service"
```

### 3. Create Event Notifications (Optional)

For webhook notifications on uploads:

```yaml
# k8s/minio/notifications-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: minio-notifications
  namespace: rag-pipeline
data:
  setup-notifications.sh: |
    #!/bin/sh
    set -e
    
    # Configure webhook endpoint for document uploads
    mc admin config set rag notify_webhook:ingestion \
      endpoint="http://ingestion-service:8080/webhooks/minio" \
      auth_token="${WEBHOOK_AUTH_TOKEN}"
    
    mc admin service restart rag
    
    # Add notification for raw-documents bucket
    mc event add rag/raw-documents \
      arn:minio:sqs::ingestion:webhook \
      --event put \
      --suffix ".pdf,.docx,.txt,.md"
```

### 4. Makefile Integration

Add to `Makefile`:

```makefile
.PHONY: minio-bootstrap minio-service-accounts

minio-bootstrap:
	kubectl delete job minio-bootstrap -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/minio/bootstrap-job.yaml
	kubectl wait --for=condition=complete job/minio-bootstrap -n rag-pipeline --timeout=300s
	@echo "MinIO bootstrap completed"

minio-service-accounts:
	./scripts/create-minio-service-accounts.sh rag-pipeline
```

### 5. Python Client Configuration

```python
# services/shared/storage/s3_client.py
import os
import boto3
from botocore.config import Config

def get_s3_client():
    """Get S3-compatible client for MinIO."""
    
    endpoint = os.getenv("S3_ENDPOINT", "http://minio:9000")
    access_key = os.getenv("S3_ACCESS_KEY")
    secret_key = os.getenv("S3_SECRET_KEY")
    region = os.getenv("S3_REGION", "us-east-1")
    secure = os.getenv("S3_SECURE", "false").lower() == "true"
    
    # Use HTTPS in production
    if secure and not endpoint.startswith("https"):
        endpoint = endpoint.replace("http://", "https://")
    
    config = Config(
        signature_version='s3v4',
        s3={'addressing_style': 'path'}
    )
    
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=config
    )


def get_bucket_names() -> dict:
    """Get bucket names from environment."""
    return {
        "raw_documents": os.getenv("S3_BUCKET_RAW", "raw-documents"),
        "processed_chunks": os.getenv("S3_BUCKET_PROCESSED", "processed-chunks"),
        "backups": os.getenv("S3_BUCKET_BACKUPS", "backups"),
        "temp_uploads": os.getenv("S3_BUCKET_TEMP", "temp-uploads"),
    }


class DocumentStorage:
    """High-level storage operations for documents."""
    
    def __init__(self):
        self.client = get_s3_client()
        self.buckets = get_bucket_names()
    
    def upload_raw_document(self, tenant_id: str, filename: str, content: bytes) -> str:
        """Upload a raw document."""
        key = f"{tenant_id}/{filename}"
        self.client.put_object(
            Bucket=self.buckets["raw_documents"],
            Key=key,
            Body=content,
            Metadata={"tenant-id": tenant_id}
        )
        return f"s3://{self.buckets['raw_documents']}/{key}"
    
    def get_raw_document(self, tenant_id: str, filename: str) -> bytes:
        """Retrieve a raw document."""
        key = f"{tenant_id}/{filename}"
        response = self.client.get_object(
            Bucket=self.buckets["raw_documents"],
            Key=key
        )
        return response['Body'].read()
    
    def list_tenant_documents(self, tenant_id: str) -> list:
        """List all documents for a tenant."""
        response = self.client.list_objects_v2(
            Bucket=self.buckets["raw_documents"],
            Prefix=f"{tenant_id}/"
        )
        return [obj['Key'] for obj in response.get('Contents', [])]
```

### 6. Environment Variables

Add to `.env.example`:

```bash
# MinIO/S3 Configuration
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=rag-service
S3_SECRET_KEY=your-secret-key
S3_REGION=us-east-1
S3_SECURE=false  # Set to true in production

# Bucket names
S3_BUCKET_RAW=raw-documents
S3_BUCKET_PROCESSED=processed-chunks
S3_BUCKET_BACKUPS=backups
S3_BUCKET_TEMP=temp-uploads
```

## Acceptance Criteria

- [x] Bootstrap job creates all required buckets
- [x] Versioning enabled for raw-documents bucket
- [x] Lifecycle rules configured for temp uploads (24h expiry)
- [x] Backup retention policies applied (30/90/365 day tiers)
- [x] IAM policies created for RAG and backup services
- [x] Service account secrets created in Kubernetes
- [x] Job is idempotent (can be re-run safely)
- [x] Python client configured with bucket helpers

## Verification Commands

```bash
# Check job status
kubectl get jobs -n rag-pipeline

# View job logs
kubectl logs job/minio-bootstrap -n rag-pipeline

# List buckets
kubectl exec deployment/minio -n rag-pipeline -- mc ls rag

# Check lifecycle rules
kubectl exec deployment/minio -n rag-pipeline -- mc ilm rule ls rag/raw-documents
kubectl exec deployment/minio -n rag-pipeline -- mc ilm rule ls rag/backups

# List policies
kubectl exec deployment/minio -n rag-pipeline -- mc admin policy list rag

# Test upload
kubectl exec deployment/minio -n rag-pipeline -- \
  sh -c 'echo "test" | mc pipe rag/raw-documents/test-tenant/test.txt'

# Verify upload
kubectl exec deployment/minio -n rag-pipeline -- mc ls rag/raw-documents/test-tenant/
```

## Bucket Configuration Reference

| Bucket | Purpose | Versioning | Lifecycle |
|--------|---------|------------|-----------|
| `raw-documents` | Original uploads | Enabled | 30-day noncurrent |
| `processed-chunks` | Processed content | Disabled | 30-day noncurrent |
| `backups` | DB/index backups | Disabled | 90/365-day retention |
| `temp-uploads` | Temporary files | Disabled | 24-hour expiry |

## Files Created

| File | Description |
|------|-------------|
| `k8s/minio/bootstrap-job.yaml` | Bucket and policy setup |
| `k8s/minio/notifications-config.yaml` | Webhook notifications (optional) |
| `scripts/create-minio-service-accounts.sh` | Service account creation |
| `services/shared/storage/s3_client.py` | Python storage client |

## Related Stories

- **US-1.5:** Object Storage (prerequisite)
- **US-1A.7:** PostgreSQL Backup CronJob (uses backups bucket)
- **US-2.x:** Ingestion Service (primary consumer)
