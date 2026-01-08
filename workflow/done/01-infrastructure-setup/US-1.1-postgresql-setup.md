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

### 4.1 Alembic Configuration

`services/shared/database/migrations/alembic.ini`:

```ini
[alembic]
script_location = %(here)s
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`services/shared/database/migrations/env.py`:

```python
import asyncio
from logging.config import fileConfig
import os

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import all models for autogenerate support
from database.models.base import Base
from database.models.document import Document, Chunk
from database.models.audit import AuditLog

config = context.config

# Load database URL from environment
config.set_main_option(
    "sqlalchemy.url",
    os.getenv("DATABASE_URL", "postgresql+asyncpg://raguser:ragpass@localhost:5432/ragpipeline")
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### 4.2 Migration Workflow Commands

```bash
# Create a new migration (auto-detect model changes)
alembic revision --autogenerate -m "add_user_roles_table"

# Create an empty migration (for custom SQL)
alembic revision -m "add_custom_index"

# Apply all pending migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade abc123

# Show current revision
alembic current

# Show migration history
alembic history --verbose

# Show pending migrations
alembic heads
```

### 4.3 Example Migration File

`services/shared/database/migrations/versions/001_initial_schema.py`:

```python
"""Initial schema with documents and chunks tables

Revision ID: 001_initial
Revises: 
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', sa.String(255), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500)),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('metadata', postgresql.JSONB, default={}),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('visibility', sa.String(20), default='private'),
        sa.Column('allowed_groups', postgresql.JSONB, default=[]),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )
    
    # Create chunks table
    op.create_table(
        'chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer, nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('token_count', sa.Integer),
        sa.Column('metadata', postgresql.JSONB, default={}),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )
    
    # Create indexes
    op.create_index('ix_documents_tenant_id', 'documents', ['tenant_id'])
    op.create_index('ix_documents_source_id', 'documents', ['source_id'])
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
    op.create_index('ix_documents_status', 'documents', ['status'])
    
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'])
    op.create_index('ix_chunks_tenant_id', 'chunks', ['tenant_id'])


def downgrade() -> None:
    op.drop_table('chunks')
    op.drop_table('documents')
```

### 4.4 CI/CD Migration Integration

Add to GitHub Actions workflow (`.github/workflows/deploy.yml`):

```yaml
jobs:
  migrate:
    name: Run Database Migrations
    runs-on: ubuntu-latest
    needs: [build]
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install alembic sqlalchemy[asyncio] asyncpg
      
      - name: Run migrations
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: |
          cd services/shared/database
          alembic upgrade head
      
      - name: Verify migration status
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: |
          cd services/shared/database
          alembic current

  deploy:
    name: Deploy Application
    needs: [migrate]
    # ... rest of deployment ...
```

### 4.5 Migration Best Practices

**DO:**
- Always test migrations on a staging database first
- Include both `upgrade()` and `downgrade()` functions
- Use transactions (default behavior)
- Add comments describing what the migration does
- Run `alembic check` in CI to catch unapplied migrations

**DON'T:**
- Never modify a migration that has been deployed
- Don't drop columns in production without a deprecation period
- Avoid long-running migrations during peak hours

**Data Migration Example:**

```python
def upgrade() -> None:
    # Schema change
    op.add_column('documents', sa.Column('owner_id', sa.String(255)))
    
    # Data migration
    op.execute("""
        UPDATE documents 
        SET owner_id = metadata->>'author' 
        WHERE metadata->>'author' IS NOT NULL
    """)

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
