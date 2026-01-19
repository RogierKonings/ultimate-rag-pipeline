# Audit Logging

> **Applies to:** All Services
> **Priority:** Critical for Compliance
> **Cross-Reference:** US-10.7.5 (Security Hardening)

## Overview

The audit logging system provides comprehensive tracking of security-relevant events across all services in the Ultimate RAG Pipeline. It captures authentication, authorization, data access, and administrative actions with tamper-evident hash chaining.

## Features

- **Structured Logging**: JSON-formatted log entries for log aggregation systems
- **Hash Chaining**: SHA-256 hash chain for tamper evidence
- **Multi-Backend Storage**: PostgreSQL for persistence, OpenSearch for analytics
- **Automatic Request Logging**: FastAPI middleware captures all API requests
- **Query & Export**: REST API for searching, filtering, and exporting audit logs

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Ingestion API  │     │  Retrieval API  │     │ Orchestrator API│
│                 │     │                 │     │                 │
│ AuditMiddleware │     │ AuditMiddleware │     │ AuditMiddleware │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                          ┌──────▼──────┐
                          │ AuditLogger │
                          └──────┬──────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
             ┌──────▼──────┐ ┌───▼───┐ ┌──────▼──────┐
             │ PostgreSQL  │ │ JSON  │ │ OpenSearch  │
             │ (Permanent) │ │ Logs  │ │ (Analytics) │
             └─────────────┘ └───────┘ └─────────────┘
```

## Audit Actions

All audit events use the `AuditAction` enum:

| Action | Description |
|--------|-------------|
| `AUTH_LOGIN` | User login attempt |
| `AUTH_LOGOUT` | User logout |
| `AUTH_TOKEN_REFRESH` | Token refresh |
| `AUTH_PASSWORD_CHANGE` | Password change |
| `AUTH_MFA_SETUP` | MFA configuration |
| `AUTHZ_PERMISSION_CHECK` | Permission verification |
| `AUTHZ_ROLE_ASSIGNED` | Role assignment |
| `AUTHZ_ROLE_REVOKED` | Role revocation |
| `DOCUMENT_CREATE` | Document ingestion |
| `DOCUMENT_READ` | Document access |
| `DOCUMENT_UPDATE` | Document modification |
| `DOCUMENT_DELETE` | Document deletion |
| `QUERY_SEARCH` | Search query execution |
| `QUERY_CHAT` | Chat/RAG query |
| `ADMIN_CONFIG_CHANGE` | Configuration modification |
| `ADMIN_USER_CREATE` | User account creation |
| `ADMIN_USER_DELETE` | User account deletion |
| `DATA_EXPORT` | Data export operation |
| `DATA_IMPORT` | Data import operation |
| `SYSTEM_ERROR` | System error event |

## Usage

### Basic Logging

```python
from services.shared.security.audit import (
    AuditLogger,
    AuditAction,
    AuditOutcome,
    get_audit_logger,
)

# Get the global logger
logger = get_audit_logger("my-service")

# Log an event
await logger.log(
    action=AuditAction.DOCUMENT_READ,
    outcome=AuditOutcome.SUCCESS,
    user_id=user_id,
    tenant_id=tenant_id,
    resource_type="document",
    resource_id=str(doc_id),
    client_ip=request.client.host,
    details={"chunk_ids": chunk_ids},
)
```

### Convenience Methods

```python
# Login event
await logger.log_login(
    user_id=user_id,
    username="john@example.com",
    success=True,
    client_ip="192.168.1.1",
)

# Document access
await logger.log_document_access(
    user_id=user_id,
    document_id=str(doc_id),
    action=AuditAction.DOCUMENT_READ,
    tenant_id=tenant_id,
)

# Query execution
await logger.log_query(
    user_id=user_id,
    query_text="search query",
    results_count=10,
    duration_ms=150.5,
    tenant_id=tenant_id,
)

# Access denied
await logger.log_access_denied(
    user_id=user_id,
    resource_type="document",
    resource_id=str(doc_id),
    action=AuditAction.DOCUMENT_READ,
    reason="Insufficient permissions",
)

# System error
await logger.log_error(
    action=AuditAction.SYSTEM_ERROR,
    error_message="Database connection failed",
    trace_id=trace_id,
)
```

### Middleware Integration

The `AuditMiddleware` automatically logs all HTTP requests:

```python
from fastapi import FastAPI
from services.shared.security.audit import AuditMiddleware

app = FastAPI()

app.add_middleware(
    AuditMiddleware,
    service_name="ingestion-service",
    exclude_paths=["/health", "/healthz", "/ready", "/metrics"],
)
```

Middleware captures:
- Request method, path, and query parameters
- User ID (from JWT claims)
- Tenant ID (from request headers or JWT)
- Client IP (respects X-Forwarded-For)
- Request duration
- Response status code
- Correlation ID for distributed tracing

## Audit API

The orchestrator service exposes REST endpoints for querying audit logs:

### Query Logs

```http
GET /api/v1/audit/logs?tenant_id={uuid}&user_id={uuid}&action=AUTH_LOGIN&start_time=2024-01-01T00:00:00Z&end_time=2024-01-31T23:59:59Z&limit=100&offset=0
```

Query parameters:
- `tenant_id` (required): Filter by tenant
- `user_id`: Filter by specific user
- `action`: Filter by audit action
- `outcome`: Filter by outcome (SUCCESS, FAILURE, DENIED, ERROR)
- `resource_type`: Filter by resource type
- `resource_id`: Filter by resource ID
- `start_time`: Start of time range
- `end_time`: End of time range
- `limit`: Maximum results (default: 100)
- `offset`: Pagination offset

### Get Statistics

```http
GET /api/v1/audit/stats?tenant_id={uuid}&start_time=2024-01-01T00:00:00Z&end_time=2024-01-31T23:59:59Z
```

Returns aggregated statistics:
- Total entries by action
- Success/failure counts
- Unique user count
- Activity timeline

### Export Logs

```http
GET /api/v1/audit/export?tenant_id={uuid}&start_time=2024-01-01T00:00:00Z&end_time=2024-01-31T23:59:59Z&format=json
```

Supported formats:
- `json`: JSON array of entries
- `csv`: CSV format with headers

**Constraint:** Export limited to 90 days maximum to prevent excessive data transfer.

### Validate Hash Chain

```http
GET /api/v1/audit/validate-chain?tenant_id={uuid}&start_time=2024-01-01T00:00:00Z&end_time=2024-01-31T23:59:59Z
```

Verifies hash chain integrity. Returns:
- `valid`: True if chain is intact
- `first_broken_entry_id`: ID of first tampered entry (if any)
- `message`: Description of validation result

## OpenSearch Backend

The OpenSearch backend provides fast querying and analytics for audit logs:

### Index Pattern

Indices are created daily: `audit-logs-YYYY.MM.DD`

### Configuration

```python
from services.shared.security.audit import OpenSearchAuditBackend

backend = OpenSearchAuditBackend(
    hosts=["https://opensearch:9200"],
    http_auth=("admin", "password"),
    index_prefix="audit-logs",
    use_ssl=True,
    verify_certs=True,
)

# Write entry
await backend.write(entry)

# Query entries
entries = await backend.query(
    tenant_id=tenant_id,
    start_time=start,
    end_time=end,
    actions=[AuditAction.AUTH_LOGIN],
    limit=100,
)

# Get statistics
stats = await backend.get_stats(
    tenant_id=tenant_id,
    start_time=start,
    end_time=end,
)
```

## Hash Chain Integrity

Each audit log entry includes a SHA-256 hash computed from:
- Entry ID
- Timestamp
- User ID
- Tenant ID
- Action
- Outcome
- Resource type and ID
- Previous entry hash

This creates a tamper-evident chain where modifying any entry breaks the chain.

### Verification

```python
from services.shared.security.audit import AuditRepository

repo = AuditRepository(session)

valid, broken_id = await repo.validate_hash_chain(
    tenant_id=tenant_id,
    start_time=start,
    end_time=end,
)

if not valid:
    print(f"Chain broken at entry: {broken_id}")
```

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `AUDIT_LOG_LEVEL` | Log level for audit events | `INFO` |
| `AUDIT_OPENSEARCH_HOSTS` | OpenSearch hosts (comma-separated) | - |
| `AUDIT_OPENSEARCH_USER` | OpenSearch username | - |
| `AUDIT_OPENSEARCH_PASSWORD` | OpenSearch password | - |
| `AUDIT_INDEX_PREFIX` | Index name prefix | `audit-logs` |
| `AUDIT_RETENTION_DAYS` | Days to retain audit logs | `365` |

## Best Practices

1. **Always include tenant_id**: Multi-tenant isolation is critical for compliance
2. **Use correlation IDs**: Link related events across services
3. **Avoid logging sensitive data**: Never log passwords, tokens, or PII in details
4. **Set appropriate retention**: Balance compliance requirements with storage costs
5. **Monitor chain integrity**: Regularly validate hash chains in production
6. **Index management**: Set up index lifecycle management for OpenSearch

## Troubleshooting

### Missing Audit Entries

Check that:
1. Middleware is registered after authentication middleware
2. Service name is correctly configured
3. Paths aren't excluded unintentionally

### Hash Chain Validation Failures

If chain validation fails:
1. Check for database corruption
2. Look for out-of-order entries (clock skew)
3. Verify no manual database modifications occurred

### OpenSearch Connectivity

If OpenSearch backend fails:
1. Verify network connectivity
2. Check authentication credentials
3. Ensure SSL/TLS certificates are valid
4. Confirm index prefix permissions
