# Tenant PII Configuration Design

> **User Story:** US-10.7.4 - Enhanced PII Handling
> **Date:** 2026-01-19
> **Status:** Approved

## Overview

Implement per-tenant PII configuration to allow tenants to customize PII detection, handling modes, and custom patterns. This builds on the existing PII detection infrastructure in `services/shared/security/pii/`.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage location | `Tenant.settings["pii"]` JSONB | No migration needed, follows existing pattern |
| Configuration structure | Unified with sections | Single `pii` key with `ingestion`, `query`, `response` sections |
| API location | New dedicated router | `pii_admin.py` for cleaner separation |

## Data Model

Stored in `Tenant.settings["pii"]`:

```json
{
    "enabled": true,
    "default_handling_mode": "redact",
    "confidence_threshold": 0.7,

    "ingestion": {
        "enabled": true,
        "handling_mode": "redact",
        "reject_on_high_sensitivity": false,
        "store_pii_metadata": true
    },
    "query": {
        "enabled": true,
        "handling_mode": "redact",
        "redact_in_logs": true,
        "reject_queries_with_pii": false
    },
    "response": {
        "enabled": true,
        "handling_mode": "redact",
        "block_on_high_sensitivity": false
    },

    "entity_configs": {
        "US_SSN": {"enabled": true, "handling_mode": "reject", "min_score": 0.9},
        "EMAIL_ADDRESS": {"enabled": true, "handling_mode": "mask"}
    },

    "custom_patterns": [
        {"name": "employee_id", "pattern": "EMP-\\d{6}", "entity_type": "EMPLOYEE_ID", "score": 0.85}
    ]
}
```

## Service Layer

### TenantPIIConfigService

Location: `services/shared/security/pii/tenant_config.py`

```python
class TenantPIIConfigService:
    """Service for loading tenant-specific PII configuration."""

    def __init__(self, cache_ttl_seconds: int = 300):
        self._cache: dict[UUID, PIISettings] = {}
        self._cache_ttl = cache_ttl_seconds
        self._cache_timestamps: dict[UUID, float] = {}
        self._lock = asyncio.Lock()

    async def get_pii_settings(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIISettings:
        """Get merged PII settings for tenant (cached)."""

    async def get_detector(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIIDetector:
        """Get configured PIIDetector for tenant."""

    async def get_response_filter(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIIResponseFilter:
        """Get configured response filter for tenant."""

    async def get_query_filter(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIIQueryFilter:
        """Get configured query filter for tenant."""

    def invalidate_cache(self, tenant_id: UUID) -> None:
        """Invalidate cache when settings change."""

    def clear_cache(self) -> None:
        """Clear entire cache."""
```

## API Endpoints

Location: `services/ingestion/api/routes/pii_admin.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/tenants/{tenant_id}/pii-settings` | Get current PII configuration |
| PUT | `/admin/tenants/{tenant_id}/pii-settings` | Replace full configuration |
| PATCH | `/admin/tenants/{tenant_id}/pii-settings` | Partial update (merge) |
| POST | `/admin/tenants/{tenant_id}/pii-settings/custom-patterns` | Add custom pattern |
| DELETE | `/admin/tenants/{tenant_id}/pii-settings/custom-patterns/{name}` | Remove custom pattern |
| POST | `/admin/tenants/{tenant_id}/pii-settings/test` | Test detection on sample text |

All endpoints require admin privileges.

## Request/Response Schemas

Location: `services/ingestion/api/schemas/pii.py`

```python
class IngestionPIIConfig(BaseModel):
    enabled: bool = True
    handling_mode: str | None = None  # Override default
    reject_on_high_sensitivity: bool = False
    store_pii_metadata: bool = True

class QueryPIIConfig(BaseModel):
    enabled: bool = True
    handling_mode: str | None = None
    redact_in_logs: bool = True
    reject_queries_with_pii: bool = False

class ResponsePIIConfig(BaseModel):
    enabled: bool = True
    handling_mode: str | None = None
    block_on_high_sensitivity: bool = False

class PIIEntityConfigSchema(BaseModel):
    enabled: bool = True
    handling_mode: str | None = None
    min_score: float | None = None

class CustomPatternSchema(BaseModel):
    name: str
    pattern: str  # Regex pattern
    entity_type: str
    score: float = 0.85

class TenantPIISettingsResponse(BaseModel):
    tenant_id: str
    enabled: bool
    default_handling_mode: str
    confidence_threshold: float
    ingestion: IngestionPIIConfig
    query: QueryPIIConfig
    response: ResponsePIIConfig
    entity_configs: dict[str, PIIEntityConfigSchema]
    custom_patterns: list[CustomPatternSchema]

class TenantPIISettingsUpdate(BaseModel):
    enabled: bool | None = None
    default_handling_mode: str | None = None
    confidence_threshold: float | None = None
    ingestion: IngestionPIIConfig | None = None
    query: QueryPIIConfig | None = None
    response: ResponsePIIConfig | None = None
    entity_configs: dict[str, PIIEntityConfigSchema] | None = None

class PIITestRequest(BaseModel):
    text: str
    handling_mode: str | None = None

class PIITestResponse(BaseModel):
    has_pii: bool
    entity_counts: dict[str, int]
    entities: list[dict]  # Type, start, end, score (text redacted)
    redacted_text: str
    processing_time_ms: float
```

## Integration Points

### 1. Ingestion Pipeline

File: `services/ingestion/processors/enrichment/enrichment.py`

- Inject `TenantPIIConfigService`
- Load tenant settings in `enrich()` method
- Apply tenant's ingestion configuration

### 2. Orchestrator (Future)

Files in `services/orchestrator/`

- Query preprocessing: Apply `PIIQueryFilter` with tenant settings
- Response filtering: Apply `PIIResponseFilter` with tenant settings

## Files to Create

| File | Purpose |
|------|---------|
| `services/shared/security/pii/tenant_config.py` | TenantPIIConfigService |
| `services/ingestion/api/routes/pii_admin.py` | Admin API endpoints |
| `services/ingestion/api/schemas/pii.py` | Request/response schemas |
| `tests/security/test_tenant_pii_config.py` | Service tests |
| `services/ingestion/api/tests/test_pii_admin.py` | API tests |

## Files to Modify

| File | Changes |
|------|---------|
| `services/ingestion/api/main.py` | Register `pii_admin` router |
| `services/ingestion/api/routes/__init__.py` | Export new router |
| `services/shared/security/pii/__init__.py` | Export TenantPIIConfigService |
| `services/ingestion/processors/enrichment/enrichment.py` | Use tenant settings |

## Implementation Order

1. Create Pydantic schemas (`pii.py`)
2. Create TenantPIIConfigService (`tenant_config.py`)
3. Create API endpoints (`pii_admin.py`)
4. Register router in `main.py`
5. Write tests
6. Update enrichment pipeline integration

## Test Scenarios

### Unit Tests (TenantPIIConfigService)

- Load settings for tenant with no PII config (uses defaults)
- Load settings for tenant with partial config (merges with defaults)
- Load settings for tenant with full config
- Cache hit returns cached settings
- Cache invalidation clears tenant entry
- Custom patterns are loaded into detector

### API Tests

- GET returns default settings for tenant without config
- PUT replaces entire configuration
- PATCH merges with existing configuration
- POST custom pattern adds to list
- DELETE custom pattern removes from list
- Test endpoint returns detection results
- All endpoints require admin auth
- Invalid tenant ID returns 404

### Integration Tests

- Ingestion uses tenant-specific handling mode
- Custom patterns detect tenant-specific PII
- Cache invalidation propagates to active detectors
