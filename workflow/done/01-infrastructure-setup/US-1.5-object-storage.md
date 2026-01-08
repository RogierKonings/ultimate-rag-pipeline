# US-1.5: Object Storage (MinIO/S3)

> **Epic:** Infrastructure Setup  
> **Priority:** High  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** None

## Objective

Deploy S3-compatible object storage (MinIO) for storing raw documents and large binary objects.

## Architecture Reference

- **Technology:** MinIO / S3 (per `docs/architecture.md` - Object Storage)
- **Port:** 9000 (API), 9001 (Console)
- **Purpose:** Raw document storage, backup storage

## Implementation Tasks

### 1. Create Docker Compose Configuration

Add to `docker-compose.yml`:

```yaml
minio:
  image: minio/minio:RELEASE.2024-01-01T16-36-33Z
  container_name: rag-minio
  ports:
    - "9000:9000"
    - "9001:9001"
  environment:
    MINIO_ROOT_USER: ${MINIO_ROOT_USER:-minioadmin}
    MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-minioadmin123}
  command: server /data --console-address ":9001"
  volumes:
    - minio_data:/data
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
    interval: 10s
    timeout: 5s
    retries: 5
```

### 2. Create Kubernetes Deployment

Create `k8s/minio/statefulset.yaml`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: minio
  namespace: rag-pipeline
spec:
  serviceName: minio
  replicas: 4  # For erasure coding
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      containers:
      - name: minio
        image: minio/minio:RELEASE.2024-01-01T16-36-33Z
        args:
        - server
        - http://minio-{0...3}.minio.rag-pipeline.svc.cluster.local/data
        - --console-address
        - ":9001"
        ports:
        - containerPort: 9000
          name: api
        - containerPort: 9001
          name: console
        env:
        - name: MINIO_ROOT_USER
          valueFrom:
            secretKeyRef:
              name: minio-secrets
              key: root-user
        - name: MINIO_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: minio-secrets
              key: root-password
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        volumeMounts:
        - name: minio-data
          mountPath: /data
        livenessProbe:
          httpGet:
            path: /minio/health/live
            port: 9000
          initialDelaySeconds: 30
          periodSeconds: 10
  volumeClaimTemplates:
  - metadata:
      name: minio-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

### 3. Create Bucket Initialization Script

Create `scripts/init-minio-buckets.py`:

```python
from minio import Minio
from minio.error import S3Error
import os

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")

BUCKETS = [
    {
        "name": "documents",
        "policy": "private",
        "lifecycle_days": None,  # No expiration
    },
    {
        "name": "temp-uploads",
        "policy": "private",
        "lifecycle_days": 1,  # Expire after 1 day
    },
    {
        "name": "backups",
        "policy": "private",
        "lifecycle_days": 30,  # Expire after 30 days
    },
]

def init_buckets():
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,  # Set True for production with TLS
    )
    
    for bucket_config in BUCKETS:
        bucket_name = bucket_config["name"]
        
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            print(f"Created bucket: {bucket_name}")
        else:
            print(f"Bucket already exists: {bucket_name}")
        
        # Set lifecycle policy if specified
        if bucket_config["lifecycle_days"]:
            lifecycle_config = f"""<?xml version="1.0" encoding="UTF-8"?>
            <LifecycleConfiguration>
                <Rule>
                    <ID>expire-rule</ID>
                    <Status>Enabled</Status>
                    <Expiration>
                        <Days>{bucket_config["lifecycle_days"]}</Days>
                    </Expiration>
                </Rule>
            </LifecycleConfiguration>"""
            # Note: MinIO SDK lifecycle API differs
            print(f"Lifecycle policy set for {bucket_name}: {bucket_config['lifecycle_days']} days")

if __name__ == "__main__":
    init_buckets()
```

### 4. Create S3 Client Wrapper

Create `services/shared/storage/s3_client.py`:

```python
from minio import Minio
from minio.error import S3Error
from typing import Optional, BinaryIO
import os
import hashlib
from datetime import timedelta

class S3Storage:
    def __init__(self):
        self.client = Minio(
            endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )
        self.default_bucket = os.getenv("MINIO_DEFAULT_BUCKET", "documents")
    
    def upload_file(
        self,
        file_data: BinaryIO,
        object_name: str,
        bucket_name: Optional[str] = None,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict] = None,
    ) -> str:
        """Upload a file to S3."""
        bucket = bucket_name or self.default_bucket
        
        # Get file size
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)
        
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=file_data,
            length=file_size,
            content_type=content_type,
            metadata=metadata or {},
        )
        
        return f"s3://{bucket}/{object_name}"
    
    def download_file(
        self,
        object_name: str,
        bucket_name: Optional[str] = None,
    ) -> bytes:
        """Download a file from S3."""
        bucket = bucket_name or self.default_bucket
        
        response = self.client.get_object(bucket, object_name)
        data = response.read()
        response.close()
        response.release_conn()
        
        return data
    
    def get_presigned_url(
        self,
        object_name: str,
        bucket_name: Optional[str] = None,
        expires: int = 3600,
    ) -> str:
        """Generate presigned URL for download."""
        bucket = bucket_name or self.default_bucket
        
        return self.client.presigned_get_object(
            bucket_name=bucket,
            object_name=object_name,
            expires=timedelta(seconds=expires),
        )
    
    def delete_file(
        self,
        object_name: str,
        bucket_name: Optional[str] = None,
    ) -> None:
        """Delete a file from S3."""
        bucket = bucket_name or self.default_bucket
        self.client.remove_object(bucket, object_name)
    
    def file_exists(
        self,
        object_name: str,
        bucket_name: Optional[str] = None,
    ) -> bool:
        """Check if file exists."""
        bucket = bucket_name or self.default_bucket
        try:
            self.client.stat_object(bucket, object_name)
            return True
        except S3Error:
            return False
    
    def list_files(
        self,
        prefix: str = "",
        bucket_name: Optional[str] = None,
    ) -> list[dict]:
        """List files with prefix."""
        bucket = bucket_name or self.default_bucket
        
        objects = self.client.list_objects(bucket, prefix=prefix, recursive=True)
        return [
            {
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified,
            }
            for obj in objects
        ]
    
    @staticmethod
    def generate_object_name(
        tenant_id: str,
        filename: str,
        document_id: Optional[str] = None,
    ) -> str:
        """Generate structured object name."""
        if document_id:
            return f"{tenant_id}/{document_id}/{filename}"
        
        # Generate hash for deduplication
        hash_val = hashlib.md5(filename.encode()).hexdigest()[:8]
        return f"{tenant_id}/{hash_val}_{filename}"
    
    def health_check(self) -> bool:
        """Check S3 connectivity."""
        try:
            self.client.list_buckets()
            return True
        except Exception:
            return False
```

## Acceptance Criteria

- [ ] MinIO deployed with web console accessible on port 9001
- [ ] Buckets created: `documents`, `temp-uploads`, `backups`
- [ ] Lifecycle policies configured (temp: 1 day, backups: 30 days)
- [ ] Server-side encryption enabled in production
- [ ] Access credentials managed via environment variables
- [ ] Python client wrapper with upload/download/delete methods
- [ ] Presigned URL generation for secure downloads

## Verification Commands

```bash
# Check MinIO health
curl http://localhost:9000/minio/health/live

# Access console at http://localhost:9001

# Using mc CLI
mc alias set local http://localhost:9000 minioadmin minioadmin123
mc ls local
mc mb local/test-bucket
mc cp testfile.txt local/test-bucket/
mc ls local/test-bucket/
```

## Files to Create

1. `docker-compose.yml` (minio service entry)
2. `k8s/minio/statefulset.yaml`
3. `k8s/minio/service.yaml`
4. `k8s/minio/secrets.yaml`
5. `scripts/init-minio-buckets.py`
6. `services/shared/storage/__init__.py`
7. `services/shared/storage/s3_client.py`
