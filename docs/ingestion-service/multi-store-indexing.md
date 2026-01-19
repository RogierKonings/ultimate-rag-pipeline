# Multi-Store Indexing & ACL Bulletproofing

> **Version:** 1.0
> **Status:** Production Ready
> **Last Updated:** January 2026

This document describes the multi-store indexing architecture that ensures document consistency across PostgreSQL (authoritative source), Qdrant (vector store), and OpenSearch (keyword store), along with comprehensive ACL enforcement.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Indexing State Machine](#indexing-state-machine)
- [Background Reconciliation](#background-reconciliation)
- [Soft-Delete Propagation](#soft-delete-propagation)
- [Early ACL Filtering](#early-acl-filtering)
- [Tenant-Scoped Index Configuration](#tenant-scoped-index-configuration)
- [API Reference](#api-reference)
- [Observability](#observability)
- [Operations Guide](#operations-guide)

---

## Overview

The RAG pipeline indexes documents to three stores for different purposes:

| Store | Purpose | Data |
|-------|---------|------|
| **PostgreSQL** | Authoritative source, metadata, ACLs | Document metadata, chunks, status |
| **Qdrant** | Semantic (vector) search | Embeddings, payload for filtering |
| **OpenSearch** | Keyword (BM25) search | Full text, metadata for filtering |

The multi-store indexing system provides:

- **Explicit status tracking** for each store per document
- **Automated reconciliation** to detect and repair inconsistencies
- **Immediate deletion propagation** when documents are soft-deleted
- **Defense-in-depth ACL filtering** at both query and post-processing levels
- **Optional per-tenant isolation** for large tenants requiring dedicated resources

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Multi-Store Indexing                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │  process_document │                                                       │
│  │      Task         │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                  │
│           ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Index Coordinator                                   │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │   Qdrant    │  │ OpenSearch  │  │ PostgreSQL  │                  │   │
│  │  │   Writer    │  │   Writer    │  │   Writer    │                  │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │   │
│  │         │                │                │                          │   │
│  │         ▼                ▼                ▼                          │   │
│  │    ┌─────────┐     ┌─────────┐     ┌─────────────────────┐         │   │
│  │    │ Vectors │     │  Docs   │     │  Status Tracking    │         │   │
│  │    │ Payload │     │  Text   │     │  - qdrant_status    │         │   │
│  │    └─────────┘     └─────────┘     │  - opensearch_status│         │   │
│  │                                     │  - last_indexed_at  │         │   │
│  │                                     │  - last_index_error │         │   │
│  │                                     └─────────────────────┘         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                 Background Reconciler (Celery Beat)                    │   │
│  │  - Detects missing chunks in Qdrant/OpenSearch                        │   │
│  │  - Removes orphaned entries after deletion                            │   │
│  │  - Updates status fields in PostgreSQL                                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Soft-Delete Propagation (Event-Driven)                    │   │
│  │  Document.status = 'deleted' → Tombstone Task → Delete from stores    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Indexing State Machine

### Status Enum

Each document tracks its indexing status per store:

```python
class IndexStatus(str, Enum):
    """Indexing status for external stores."""
    PENDING = "pending"    # Indexing not yet attempted or in progress
    OK = "ok"              # Successfully indexed
    ERROR = "error"        # Indexing failed (see last_index_error)
    STALE = "stale"        # Document updated, needs re-indexing
```

### Document Model Extensions

The `Document` model includes the following status tracking fields:

| Field | Type | Description |
|-------|------|-------------|
| `qdrant_status` | `IndexStatus` | Current indexing status in Qdrant |
| `opensearch_status` | `IndexStatus` | Current indexing status in OpenSearch |
| `last_indexed_at` | `datetime` | Timestamp of last successful indexing |
| `last_index_error` | `text` | Error message from last failed indexing |
| `index_attempts` | `integer` | Number of indexing attempts (for backoff) |

### State Transitions

```
                    ┌─────────┐
                    │ PENDING │ ◀────── New document
                    └────┬────┘
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
         ┌────────┐           ┌─────────┐
         │   OK   │           │  ERROR  │
         └────┬───┘           └────┬────┘
              │                    │
              │                    │ Retry
              ▼                    ▼
         ┌─────────┐         ┌─────────┐
         │  STALE  │◀────────│ PENDING │
         └─────────┘         └─────────┘
         (document updated)
```

### Database Schema

```sql
-- Enum type for indexing status
CREATE TYPE index_status AS ENUM ('pending', 'ok', 'error', 'stale');

-- Added columns to source_documents table
ALTER TABLE source_documents ADD COLUMN qdrant_status index_status NOT NULL DEFAULT 'pending';
ALTER TABLE source_documents ADD COLUMN opensearch_status index_status NOT NULL DEFAULT 'pending';
ALTER TABLE source_documents ADD COLUMN last_indexed_at TIMESTAMPTZ;
ALTER TABLE source_documents ADD COLUMN last_index_error TEXT;
ALTER TABLE source_documents ADD COLUMN index_attempts INTEGER NOT NULL DEFAULT 0;

-- Indexes for efficient status queries
CREATE INDEX ix_source_documents_qdrant_status ON source_documents(qdrant_status);
CREATE INDEX ix_source_documents_opensearch_status ON source_documents(opensearch_status);
CREATE INDEX ix_source_documents_sync_status ON source_documents(tenant_id, qdrant_status, opensearch_status)
    WHERE status = 'active';
```

### Ingestion Pipeline Integration

The `process_document` task updates status at each stage:

```python
async def _index_to_stores(document, chunks, embeddings, session):
    # Mark as pending before indexing
    document.qdrant_status = IndexStatus.PENDING
    document.opensearch_status = IndexStatus.PENDING
    document.index_attempts += 1
    await session.commit()

    errors = []

    # Index to Qdrant
    try:
        await qdrant_client.upsert_chunks(chunks, embeddings, document.id, document.tenant_id)
        document.qdrant_status = IndexStatus.OK
    except Exception as e:
        document.qdrant_status = IndexStatus.ERROR
        errors.append(f"Qdrant: {str(e)}")

    # Index to OpenSearch
    try:
        await opensearch_client.index_chunks(chunks, document.id, document.tenant_id)
        document.opensearch_status = IndexStatus.OK
    except Exception as e:
        document.opensearch_status = IndexStatus.ERROR
        errors.append(f"OpenSearch: {str(e)}")

    # Update final status
    if errors:
        document.last_index_error = "; ".join(errors)
    else:
        document.last_index_error = None
        document.last_indexed_at = datetime.utcnow()

    await session.commit()
```

---

## Background Reconciliation

### Overview

The background reconciler automatically detects and repairs inconsistencies between stores:

- **Missing chunks**: Chunks in PostgreSQL but not in Qdrant/OpenSearch
- **Orphaned entries**: Chunks in Qdrant/OpenSearch but not in PostgreSQL
- **Status mismatches**: Status fields not matching actual store state

### Celery Task

```python
@shared_task(queue="maintenance", bind=True, soft_time_limit=3600)
async def reconcile_index(
    self,
    tenant_id: str,
    document_id: str | None = None,
    dry_run: bool = False,
    batch_size: int = 100,
) -> dict:
    """
    Reconcile PostgreSQL authoritative state with Qdrant and OpenSearch.

    Args:
        tenant_id: Tenant to reconcile
        document_id: Optional specific document (None = all tenant documents)
        dry_run: If True, report issues without fixing
        batch_size: Number of documents to process per batch

    Returns:
        ReconciliationResult as dict
    """
```

### Reconciliation Phases

1. **Phase 1: Detect Missing Chunks**
   - Query active documents from PostgreSQL
   - Check if chunks exist in Qdrant and OpenSearch
   - Re-index any missing chunks

2. **Phase 2: Detect Orphaned Entries**
   - Get all chunk IDs from Qdrant/OpenSearch for tenant
   - Compare with active chunks in PostgreSQL
   - Delete orphaned entries

3. **Phase 3: Update Status Fields**
   - Verify status fields match actual state
   - Update any mismatches

### Scheduling

Default schedule: Nightly at 3 AM (configurable per tenant):

```python
# Celery Beat configuration
beat_schedule = {
    "nightly-reconciliation": {
        "task": "ingestion.tasks.reconcile.reconcile_all_tenants",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {"dry_run": False},
    },
}
```

### Reconciliation Result

```python
@dataclass
class ReconciliationResult:
    tenant_id: str
    document_id: str | None
    dry_run: bool
    started_at: datetime
    completed_at: datetime
    documents_scanned: int
    chunks_scanned: int
    issues_found: int
    issues_fixed: int
    issues_failed: int
    issues: list[ReconciliationIssue]
```

---

## Soft-Delete Propagation

### Overview

When a document is soft-deleted in PostgreSQL, the deletion must propagate immediately to Qdrant and OpenSearch to prevent deleted content from appearing in search results.

### Tombstone Task

```python
@shared_task(queue="ingestion", bind=True, max_retries=3, autoretry_for=(Exception,))
async def propagate_deletion(
    self,
    document_id: str,
    tenant_id: str,
) -> dict:
    """
    Propagate document deletion to all external stores.

    This task is idempotent - safe to retry on failure.
    """
    result = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "qdrant_deleted": 0,
        "opensearch_deleted": 0,
        "errors": [],
    }

    # Delete from Qdrant
    try:
        result["qdrant_deleted"] = await qdrant.delete_by_document_id(document_id, tenant_id)
    except Exception as e:
        result["errors"].append(f"Qdrant deletion failed: {e}")

    # Delete from OpenSearch
    try:
        result["opensearch_deleted"] = await opensearch.delete_by_document_id(document_id, tenant_id)
    except Exception as e:
        result["errors"].append(f"OpenSearch deletion failed: {e}")

    if result["errors"]:
        raise Exception("; ".join(result["errors"]))

    return result
```

### Automatic Triggering

Deletions are triggered via SQLAlchemy event listener:

```python
@event.listens_for(Document, "after_update")
def on_document_update(mapper, connection, target: Document):
    """Trigger deletion propagation when document is soft-deleted."""
    status_history = get_history(target, "status")
    if status_history.has_changes():
        old_status = status_history.deleted[0] if status_history.deleted else None
        new_status = status_history.added[0] if status_history.added else None

        if old_status != "deleted" and new_status == "deleted":
            # Enqueue tombstone task after commit
            propagate_deletion.delay(
                document_id=str(target.id),
                tenant_id=target.tenant_id,
            )
```

### Safety Net: Status Field in Stores

The `status` field is indexed to both Qdrant and OpenSearch payloads. All retrieval queries include `status='active'` filter as defense-in-depth:

```python
# Qdrant filter always includes:
FieldCondition(key="status", match=MatchValue(value="active"))

# OpenSearch filter always includes:
{"term": {"status": "active"}}
```

This ensures deleted documents are never returned even if the tombstone task fails or is delayed.

---

## Early ACL Filtering

### Overview

ACL filters are applied at the database query level (before fusion/reranking) to ensure unauthorized documents never reach the reranker. A safety net filter is retained post-rerank as defense-in-depth.

### Filter Application Points

```
Query
  │
  ├──▶ Semantic Search (Qdrant)
  │    └── ACL Filter applied in query_filter
  │
  ├──▶ Keyword Search (OpenSearch)
  │    └── ACL Filter applied in bool.filter
  │
  ├──▶ RRF Fusion
  │
  ├──▶ Reranking (all docs should be authorized)
  │
  └──▶ Safety Net Filter (should be no-op)
       └── Logs warning + increments metric if filters anything
```

### ACL Filter Components

The ACL filter enforces:

1. **Tenant isolation** (mandatory)
2. **Document status** (only active documents)
3. **Visibility rules** (public/private/group/tenant)
4. **User-specific access** (allowed_users, denied_users)

### Qdrant Filter Structure

```python
def build_qdrant_filter(user_context: UserContext) -> Filter:
    must_conditions = [
        # Tenant isolation - ALWAYS required
        FieldCondition(key="tenant_id", match=MatchValue(value=str(user_context.tenant_id))),
        # Only active documents - ALWAYS required
        FieldCondition(key="status", match=MatchValue(value="active")),
    ]

    # Visibility-based access (should = OR)
    visibility_conditions = [
        FieldCondition(key="visibility", match=MatchValue(value="public")),
        FieldCondition(key="visibility", match=MatchValue(value="tenant")),
    ]

    # Group-based access
    if user_context.groups:
        visibility_conditions.append(
            Filter(must=[
                FieldCondition(key="visibility", match=MatchValue(value="group")),
                FieldCondition(key="allowed_groups", match=MatchAny(any=user_context.groups)),
            ])
        )

    # Private documents owned by user
    if user_context.user_id:
        visibility_conditions.append(
            Filter(must=[
                FieldCondition(key="visibility", match=MatchValue(value="private")),
                FieldCondition(key="owner_id", match=MatchValue(value=str(user_context.user_id))),
            ])
        )

    return Filter(
        must=must_conditions,
        should=visibility_conditions,
        must_not=build_denied_conditions(user_context),
    )
```

### Safety Net Metric

The safety net filter should never filter anything if query-level ACL is working correctly. Any filtering indicates a bug:

```python
acl_safety_net_filtered = Counter(
    "acl_safety_net_filtered_total",
    "Documents filtered by safety net (should be zero)",
    ["tenant_id", "reason"],
)
```

Alert if this metric is non-zero.

---

## Tenant-Scoped Index Configuration

### Overview

Large tenants (>10M chunks, dedicated SLAs, regulatory requirements) can be configured to use dedicated Qdrant collections and OpenSearch indices instead of shared resources.

### Configuration Model

```python
class TenantIsolationMode(str, Enum):
    SHARED = "shared"      # Use shared collection/index (default)
    DEDICATED = "dedicated"  # Use tenant-specific collection/index

class TenantConfig(Base):
    tenant_id: str
    isolation_mode: TenantIsolationMode = TenantIsolationMode.SHARED
    qdrant_collection_name: str | None = None  # e.g., "documents_tenant123"
    qdrant_settings: dict | None = None        # Custom HNSW params
    opensearch_index_name: str | None = None   # e.g., "documents-tenant123"
    opensearch_settings: dict | None = None    # Custom index settings
```

### Collection/Index Naming

| Mode | Qdrant Collection | OpenSearch Index |
|------|-------------------|------------------|
| Shared | `documents` | `documents` |
| Dedicated | `documents_{tenant_id}` | `documents-{tenant_id}` |

### Routing Logic

The store clients automatically route to the correct collection/index:

```python
class TenantAwareQdrantClient:
    async def get_collection_for_tenant(self, tenant_id: str) -> str:
        config = await self.config_repo.get_by_tenant_id(tenant_id)
        if config and config.isolation_mode == TenantIsolationMode.DEDICATED:
            return config.qdrant_collection_name or f"documents_{tenant_id}"
        return "documents"  # Shared collection
```

### Migration to Dedicated

Zero-downtime migration process:

1. Create dedicated collection/index
2. Copy all tenant's vectors/documents (batched)
3. Update tenant config to use dedicated
4. (Optional) Clean up from shared collection

```python
result = await migrate_tenant_to_dedicated(
    tenant_id="large-tenant",
    dry_run=False,  # Set True for preview
)
# Returns: chunks migrated, duration, success status
```

---

## API Reference

### Sync Status Endpoint

```
GET /api/v1/documents/sync-status
```

Query document indexing sync status across all stores.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tenant_id` | string | Required. Tenant ID |
| `status_filter` | string | `all`, `ok`, `error`, `pending`, `any_error` |
| `since` | datetime | Filter by updated_at |
| `limit` | int | Results per page (default: 100) |
| `offset` | int | Pagination offset |

**Response:**

```json
{
  "summary": {
    "ok": 950,
    "error": 5,
    "pending": 2,
    "stale": 3
  },
  "documents": [
    {
      "document_id": "uuid",
      "source_id": "s3://bucket/doc.pdf",
      "qdrant_status": "ok",
      "opensearch_status": "error",
      "last_indexed_at": "2026-01-15T10:30:00Z",
      "last_index_error": "OpenSearch: Connection refused",
      "index_attempts": 3
    }
  ],
  "total": 960,
  "limit": 100,
  "offset": 0
}
```

### Reconciliation Endpoints

```
POST /api/v1/admin/reconcile
```

Trigger index reconciliation for a tenant.

**Request:**

```json
{
  "tenant_id": "uuid",
  "document_id": null,
  "dry_run": true
}
```

**Response:**

```json
{
  "job_id": "uuid",
  "status": "queued",
  "message": "Reconciliation dry-run queued for tenant uuid"
}
```

---

```
GET /api/v1/admin/reconcile/{job_id}
```

Get reconciliation job status.

**Response:**

```json
{
  "status": "completed",
  "job_id": "uuid",
  "result": {
    "tenant_id": "uuid",
    "documents_scanned": 1000,
    "chunks_scanned": 15000,
    "issues_found": 5,
    "issues_fixed": 5,
    "issues_failed": 0,
    "duration_seconds": 45.2
  }
}
```

### Tenant Isolation Endpoints

```
GET /api/v1/admin/tenants/{tenant_id}/isolation-status
```

Get tenant's current isolation configuration.

**Response:**

```json
{
  "tenant_id": "uuid",
  "isolation_mode": "shared",
  "qdrant_collection": "documents",
  "opensearch_index": "documents"
}
```

---

```
POST /api/v1/admin/tenants/{tenant_id}/migrate-to-dedicated
```

Migrate tenant to dedicated collection/index.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `dry_run` | bool | Preview without changes (default: true) |

**Response (dry_run=true):**

```json
{
  "tenant_id": "uuid",
  "source_collection": "documents",
  "target_collection": "documents_uuid",
  "chunks_to_migrate": 150000,
  "estimated_duration_minutes": 15
}
```

---

## Observability

### Prometheus Metrics

#### Index Status Metrics

```prometheus
# Gauge: Documents by indexing status
documents_by_index_status{store="qdrant", status="ok", tenant_id="t1"} 950
documents_by_index_status{store="qdrant", status="error", tenant_id="t1"} 5
documents_by_index_status{store="opensearch", status="ok", tenant_id="t1"} 955
```

#### Reconciliation Metrics

```prometheus
# Counter: Reconciliation runs
index_reconciliation_runs_total{tenant_id="t1", status="success"} 30
index_reconciliation_runs_total{tenant_id="t1", status="partial"} 2

# Histogram: Reconciliation duration
index_reconciliation_duration_seconds_bucket{tenant_id="t1", le="60"} 25
index_reconciliation_duration_seconds_bucket{tenant_id="t1", le="300"} 30

# Counter: Orphans cleaned
index_orphans_cleaned_total{store="qdrant"} 15
index_orphans_cleaned_total{store="opensearch"} 12

# Counter: Missing re-indexed
index_missing_reindexed_total{store="qdrant"} 8
index_missing_reindexed_total{store="opensearch"} 10
```

#### ACL Safety Net Metric

```prometheus
# Counter: Documents filtered by safety net (should be zero!)
acl_safety_net_filtered_total{tenant_id="t1", reason="unauthorized_access_attempt"} 0
```

### Alerting Rules

```yaml
groups:
  - name: multi-store-indexing
    rules:
      # Alert if documents stuck in ERROR state
      - alert: DocumentIndexingErrors
        expr: documents_by_index_status{status="error"} > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "{{ $value }} documents in ERROR state for {{ $labels.store }}"

      # Alert if reconciliation is failing
      - alert: ReconciliationFailures
        expr: increase(index_reconciliation_runs_total{status="failure"}[1h]) > 0
        labels:
          severity: warning
        annotations:
          summary: "Reconciliation failures detected for tenant {{ $labels.tenant_id }}"

      # Alert if safety net is filtering (indicates ACL bug)
      - alert: ACLSafetyNetTriggered
        expr: increase(acl_safety_net_filtered_total[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "ACL safety net filtering documents - possible ACL bug!"
```

### Structured Logging

All operations emit structured logs:

```json
{
  "timestamp": "2026-01-15T10:30:00Z",
  "level": "INFO",
  "event": "qdrant_indexing_success",
  "document_id": "uuid",
  "chunk_count": 15,
  "duration_ms": 45
}
```

```json
{
  "timestamp": "2026-01-15T10:30:05Z",
  "level": "WARNING",
  "event": "acl_safety_net_filtered",
  "document_id": "uuid",
  "chunk_id": "uuid",
  "tenant_id": "t1",
  "visibility": "private",
  "reason": "safety_net_catch"
}
```

---

## Operations Guide

### Monitoring Sync Status

1. **Dashboard**: Check the "Document Sync Status" panel in Grafana
2. **API**: Query `/api/v1/documents/sync-status?status_filter=any_error`
3. **Metrics**: Monitor `documents_by_index_status{status="error"}`

### Handling Indexing Errors

1. **Identify affected documents**: Use sync status API with `status_filter=error`
2. **Check error messages**: Review `last_index_error` field
3. **Fix underlying issue**: Network, capacity, schema mismatch
4. **Trigger re-indexing**: Either wait for reconciler or trigger manually

### Manual Reconciliation

```bash
# Dry run first
curl -X POST http://localhost:8001/api/v1/admin/reconcile \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"tenant_id": "uuid", "dry_run": true}'

# Execute reconciliation
curl -X POST http://localhost:8001/api/v1/admin/reconcile \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"tenant_id": "uuid", "dry_run": false}'

# Check progress
curl http://localhost:8001/api/v1/admin/reconcile/{job_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Migrating Tenant to Dedicated Collection

1. **Assess tenant size**: Check chunk count and growth rate
2. **Schedule migration**: Choose low-traffic window
3. **Run dry-run**: Preview migration without changes
4. **Execute migration**: Run with `dry_run=false`
5. **Verify**: Check tenant isolation status and test queries
6. **Rollback if needed**: Set isolation mode back to shared

```bash
# Dry run
curl -X POST "http://localhost:8001/api/v1/admin/tenants/{id}/migrate-to-dedicated?dry_run=true" \
  -H "Authorization: Bearer $TOKEN"

# Execute
curl -X POST "http://localhost:8001/api/v1/admin/tenants/{id}/migrate-to-dedicated?dry_run=false" \
  -H "Authorization: Bearer $TOKEN"
```

### Troubleshooting

#### Documents Not Appearing in Search

1. Check `qdrant_status` and `opensearch_status` in PostgreSQL
2. Verify `status` field is `active`
3. Check ACL filters match user context
4. Run reconciliation to detect/fix inconsistencies

#### Deleted Documents Still Appearing

1. Check tombstone task queue for backlog
2. Verify `status` field filter in search queries
3. Manually trigger reconciliation for orphan cleanup
4. Check Celery worker health for `ingestion` queue

#### High Reconciliation Duration

1. Consider increasing `batch_size`
2. Check store health (Qdrant, OpenSearch response times)
3. Schedule during lower-traffic periods
4. For large tenants, consider dedicated collection migration

---

## Related Documentation

- [Ingestion Service README](README.md)
- [Architecture Overview](../architecture.md)
- [Security & ACL](../security/README.md)
- [Observability](../observability/README.md)
