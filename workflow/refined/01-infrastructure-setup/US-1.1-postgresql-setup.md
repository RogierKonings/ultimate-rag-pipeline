# US-1.1: PostgreSQL Setup

> **Epic:** Infrastructure Setup  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** None

## Objective

Deploy PostgreSQL 16+ database for storing document metadata, user data, and audit logs.

## Architecture Reference

- **Technology:** PostgreSQL 16+ (per `docs/architecture.md` Technology Stack)
- **Port:** 5432
- **Purpose:** ACID-compliant metadata store with JSON support

## Implementation Tasks

### 1. Create Docker Compose Configuration

Create `docker-compose.yml` entry for local development:

```yaml
postgres:
  image: postgres:16-alpine
  container_name: rag-postgres
  ports:
    - "5432:5432"
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-raguser}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-ragpass}
    POSTGRES_DB: ${POSTGRES_DB:-ragpipeline}
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./init-scripts:/docker-entrypoint-initdb.d
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U raguser -d ragpipeline"]
    interval: 10s
    timeout: 5s
    retries: 5
```

### 2. Create Kubernetes Deployment

Create `k8s/postgres/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: rag-pipeline
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        ports:
        - containerPort: 5432
        env:
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
        - name: POSTGRES_DB
          value: ragpipeline
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-storage
        persistentVolumeClaim:
          claimName: postgres-pvc
```

### 3. Create PgBouncer Connection Pooling

Create `k8s/pgbouncer/deployment.yaml` for connection pooling:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pgbouncer
  namespace: rag-pipeline
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pgbouncer
  template:
    spec:
      containers:
      - name: pgbouncer
        image: edoburu/pgbouncer:1.21.0
        ports:
        - containerPort: 5432
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: database-url
        - name: POOL_MODE
          value: "transaction"
        - name: MAX_CLIENT_CONN
          value: "100"
```

### 4. Set Up Database Migrations

Install and configure Alembic for migrations:

```bash
# In services/shared or each service
pip install alembic sqlalchemy[asyncio] asyncpg
alembic init migrations
```

Create initial migration structure:

```
services/
└── shared/
    └── database/
        ├── __init__.py
        ├── connection.py      # SQLAlchemy async engine
        ├── models/
        │   ├── __init__.py
        │   ├── base.py        # Base model class
        │   ├── document.py    # Document metadata model
        │   └── audit.py       # Audit log model
        └── migrations/
            ├── env.py
            ├── versions/
            └── alembic.ini
```

### 5. Create Core Database Models

`services/shared/database/models/document.py`:

```python
from sqlalchemy import Column, String, DateTime, JSON, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from .base import Base
import uuid

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)  # file, web, api, database
    title = Column(String(500))
    content_hash = Column(String(64), nullable=False)  # SHA-256
    metadata = Column(JSON, default={})
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    visibility = Column(String(20), default="private")  # public, private, group
    allowed_groups = Column(JSON, default=[])
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    
    __table_args__ = (
        Index("ix_documents_tenant_id", "tenant_id"),
        Index("ix_documents_source_id", "source_id"),
        Index("ix_documents_content_hash", "content_hash"),
    )
```

### 6. Document Backup Procedures

Create `scripts/postgres-backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/backups/postgres"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/ragpipeline_${TIMESTAMP}.sql.gz"

pg_dump -h $POSTGRES_HOST -U $POSTGRES_USER $POSTGRES_DB | gzip > $BACKUP_FILE

# Retain last 7 days
find $BACKUP_DIR -type f -mtime +7 -delete
```

## Acceptance Criteria

- [ ] PostgreSQL 16+ deployed and accessible on port 5432
- [ ] Connection pooling via PgBouncer configured
- [ ] Database migrations framework (Alembic) initialized
- [ ] Core tables created: `documents`, `chunks`, `audit_logs`
- [ ] Backup script created and documented
- [ ] Health check endpoint responds successfully
- [ ] Environment variables documented in `.env.example`

## Verification Commands

```bash
# Test local connection
docker-compose exec postgres psql -U raguser -d ragpipeline -c "SELECT version();"

# Run migrations
alembic upgrade head

# Verify tables exist
docker-compose exec postgres psql -U raguser -d ragpipeline -c "\dt"
```

## Files to Create

1. `docker-compose.yml` (postgres service entry)
2. `k8s/postgres/deployment.yaml`
3. `k8s/postgres/service.yaml`
4. `k8s/postgres/pvc.yaml`
5. `k8s/pgbouncer/deployment.yaml`
6. `services/shared/database/connection.py`
7. `services/shared/database/models/document.py`
8. `services/shared/database/models/audit.py`
9. `services/shared/database/migrations/env.py`
10. `scripts/postgres-backup.sh`
