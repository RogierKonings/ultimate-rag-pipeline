# Database Security Enablement

> **Version:** 1.0
> **Status:** Production Implementation
> **Cross-Reference:** US-10.7.2 (Security Hardening)

## Overview

The RAG Pipeline implements comprehensive database security including SSL/TLS connections, proper authentication, and credential management for PostgreSQL, Redis, and OpenSearch in production environments.

## Security Measures

| Database | Transport Security | Authentication | Additional |
|----------|-------------------|----------------|------------|
| PostgreSQL | SSL/TLS with certificate verification | Username/password from Vault | Connection pooling secured |
| Redis | TLS connections | Strong password + ACL | Command restrictions |
| OpenSearch | HTTPS | Basic auth or certificates | RBAC, audit logging |

## PostgreSQL Security

### SSL Configuration

PostgreSQL connections support multiple SSL modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| `disable` | No SSL | Local development only |
| `require` | Encrypt, no verification | Basic encryption |
| `verify-ca` | Verify server certificate | Production (internal CA) |
| `verify-full` | Full verification + hostname | Production (recommended) |

### Configuration

```python
from shared.database.connection import create_engine_with_ssl

# Environment variables
# POSTGRES_SSL_MODE=verify-full
# POSTGRES_SSL_CA=/certs/ca.crt
# POSTGRES_HOST=postgres.rag-pipeline.svc
# POSTGRES_USER=raguser
# POSTGRES_PASSWORD=<from-secrets>

engine = create_engine_with_ssl()
```

### SSL Context Creation

```python
from shared.security.tls import create_ssl_context

def create_postgres_ssl_context():
    ssl_mode = os.getenv("POSTGRES_SSL_MODE", "prefer")

    if ssl_mode == "disable":
        return None

    ctx = ssl.create_default_context()

    if ssl_mode == "verify-ca":
        ca_cert = os.getenv("POSTGRES_SSL_CA")
        ctx.load_verify_locations(ca_cert)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED

    elif ssl_mode == "verify-full":
        ca_cert = os.getenv("POSTGRES_SSL_CA")
        ctx.load_verify_locations(ca_cert)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

    return ctx
```

### Connection String Security

**Never include passwords in connection strings** - they appear in logs. Instead:

```python
# Good: Password passed separately
database_url = f"postgresql+asyncpg://{user}@{host}:{port}/{database}"
connect_args = {"password": password, "ssl": ssl_context}

# Bad: Password in URL (appears in logs!)
# database_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
```

## Redis Security

### TLS Configuration

```python
from shared.cache.redis_client import create_redis_client

# Environment variables
# REDIS_TLS_ENABLED=true
# REDIS_TLS_CA=/certs/ca.crt
# REDIS_TLS_CERT=/certs/client.crt  (optional, for mTLS)
# REDIS_TLS_KEY=/certs/client.key   (optional, for mTLS)
# REDIS_PASSWORD=<from-secrets>

redis = create_redis_client()
```

### ACL Configuration

Redis ACLs restrict command access per user:

```redis
# Application user - limited commands
user rag_app on >{password} ~rag:* &* +@read +@write +@connection -@dangerous

# Cache user - only get/set operations
user rag_cache on >{password} ~cache:* &* +get +set +setex +del +exists +expire

# Celery user - task queue operations
user rag_celery on >{password} ~celery:* &* +@list +@string +@set +@connection

# Disable default user
user default off
```

### Dangerous Commands Disabled

The following commands are disabled for application users:
- `FLUSHALL`, `FLUSHDB`
- `CONFIG`, `DEBUG`
- `SHUTDOWN`, `SLAVEOF`
- `KEYS` (use `SCAN` instead)

## OpenSearch Security

### HTTPS Configuration

```python
from shared.search.opensearch_client import create_opensearch_client

# Environment variables
# OPENSEARCH_SSL_ENABLED=true
# OPENSEARCH_SSL_CA=/certs/ca.crt
# OPENSEARCH_USERNAME=rag_app
# OPENSEARCH_PASSWORD=<from-secrets>

client = create_opensearch_client()
```

### Role-Based Access Control

OpenSearch roles for different service accounts:

```yaml
# Read-only role for retrieval service
rag_retrieval_role:
  cluster_permissions:
    - cluster_composite_ops_ro
  index_permissions:
    - index_patterns:
        - "rag-*"
      allowed_actions:
        - read
        - search

# Write role for ingestion service
rag_ingestion_role:
  cluster_permissions:
    - cluster_composite_ops
  index_permissions:
    - index_patterns:
        - "rag-*"
      allowed_actions:
        - crud
        - create_index

# Admin role for management operations
rag_admin_role:
  cluster_permissions:
    - cluster_all
  index_permissions:
    - index_patterns:
        - "rag-*"
      allowed_actions:
        - all
```

## Credential Sanitization in Logs

All credentials are automatically sanitized from logs using the `SanitizingProcessor`:

```python
from shared.logging.sanitizer import SanitizingProcessor

# Patterns sanitized:
# - password=xxx -> password=***
# - ://user:pass@host -> ://***:***@host
# - Bearer eyJxxx -> Bearer ***
# - Basic xxx -> Basic ***
# - api_key=xxx -> api_key=***

# Example
logger.info("Connecting to database", url="postgresql://user:secret@host/db")
# Logged as: {"url": "postgresql://***:***@host/db"}
```

### Sensitive Key Detection

Dictionary keys containing these patterns have values masked:
- `password`, `secret`, `token`, `api_key`, `credential`, `auth`

```python
data = {"username": "admin", "password": "secret123"}
sanitized = sanitize_dict(data)
# Result: {"username": "admin", "password": "***"}
```

## Health Checks with SSL Verification

Health endpoints verify SSL is active:

```python
from shared.health.database_health import (
    check_postgres_health,
    check_redis_health,
    check_opensearch_health,
)

# PostgreSQL health with SSL check
pg_status = await check_postgres_health(engine)
# Returns: DatabaseHealthStatus(
#   name="postgresql", healthy=True, latency_ms=5.2, ssl_enabled=True
# )

# Redis health
redis_status = await check_redis_health(redis_client)
# Verifies TLS context is present

# OpenSearch health
os_status = await check_opensearch_health(client)
# Checks transport.use_ssl flag
```

## Kubernetes Configuration

### Certificate Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: database-tls-certs
  namespace: rag-pipeline
type: kubernetes.io/tls
data:
  ca.crt: <base64-ca-cert>
  tls.crt: <base64-client-cert>
  tls.key: <base64-client-key>
```

### Credential Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
  namespace: rag-pipeline
type: Opaque
stringData:
  POSTGRES_USER: raguser
  POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
  POSTGRES_SSL_MODE: verify-full
---
apiVersion: v1
kind: Secret
metadata:
  name: redis-credentials
  namespace: rag-pipeline
type: Opaque
stringData:
  REDIS_PASSWORD: "${REDIS_PASSWORD}"
  REDIS_TLS_ENABLED: "true"
---
apiVersion: v1
kind: Secret
metadata:
  name: opensearch-credentials
  namespace: rag-pipeline
type: Opaque
stringData:
  OPENSEARCH_USERNAME: rag_app
  OPENSEARCH_PASSWORD: "${OPENSEARCH_PASSWORD}"
  OPENSEARCH_SSL_ENABLED: "true"
```

### Mounting in Pods

```yaml
spec:
  containers:
    - name: retrieval
      volumeMounts:
        - name: db-certs
          mountPath: /certs
          readOnly: true
      envFrom:
        - secretRef:
            name: postgres-credentials
        - secretRef:
            name: redis-credentials
  volumes:
    - name: db-certs
      secret:
        secretName: database-tls-certs
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_SSL_MODE` | SSL mode | `prefer` |
| `POSTGRES_SSL_CA` | CA certificate path | - |
| `REDIS_TLS_ENABLED` | Enable Redis TLS | `false` |
| `REDIS_TLS_CA` | Redis CA certificate | - |
| `REDIS_TLS_CERT` | Redis client certificate | - |
| `REDIS_TLS_KEY` | Redis client key | - |
| `OPENSEARCH_SSL_ENABLED` | Enable HTTPS | `false` |
| `OPENSEARCH_SSL_CA` | OpenSearch CA certificate | - |
| `ENVIRONMENT` | Deployment environment | `development` |

## Testing

### Unit Tests

```bash
pytest services/shared/security/tls/tests/test_database_security.py -v
```

### Integration Tests

```python
@pytest.mark.integration
class TestPostgresSSLIntegration:
    async def test_connects_with_ssl(self, postgres_engine):
        """Should connect to PostgreSQL with SSL."""
        async with postgres_engine.connect() as conn:
            result = await conn.execute("SELECT ssl_is_used()")
            assert result.fetchone()[0] is True

    async def test_rejects_non_ssl(self, postgres_host):
        """Should reject connection without SSL in production."""
        with pytest.raises(ConnectionError):
            await asyncpg.connect(
                host=postgres_host,
                ssl=False,  # Explicitly disabled
            )
```

## Troubleshooting

### PostgreSQL SSL Issues

**"SSL connection required"**
- Set `POSTGRES_SSL_MODE=require` or higher
- Ensure CA certificate is mounted

**"Certificate verify failed"**
- Check CA certificate is correct for your PostgreSQL server
- Verify certificate hasn't expired

### Redis TLS Issues

**"SSL: CERTIFICATE_VERIFY_FAILED"**
- Verify `REDIS_TLS_CA` points to correct CA
- Check Redis server certificate is valid

**"AUTH required"**
- Ensure `REDIS_PASSWORD` is set
- Check ACL user has required permissions

### OpenSearch SSL Issues

**"ConnectionError: SSL handshake failed"**
- Verify `OPENSEARCH_SSL_ENABLED=true`
- Check CA certificate is mounted
- Confirm OpenSearch has security plugin enabled

## Related Documentation

- [Security Overview](./README.md)
- [Inter-Service Authentication](./inter-service-authentication.md)
- [Secrets Management](./README.md#secrets-management)
- [TLS Certificate Management](../infrastructure/tls-certificate-management.md)
