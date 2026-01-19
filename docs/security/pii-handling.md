# Enhanced PII Handling

> **Version:** 1.0
> **Status:** Production Implementation
> **Cross-Reference:** US-10.7.4 (Security Hardening)

## Overview

The RAG Pipeline implements comprehensive PII (Personally Identifiable Information) detection and redaction using Microsoft Presidio. PII is detected and handled at three stages: document ingestion, query processing, and LLM response filtering.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          PII Processing Pipeline                            │
└────────────────────────────────────────────────────────────────────────────┘

                ┌─────────────────┐
                │   PIIDetector   │ ◄── Microsoft Presidio + spaCy
                │   (Detection)   │
                └────────┬────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ PIIProcessor    │ │ QuerySanitizer  │ │ ResponseFilter  │
│ (Ingestion)     │ │ (Query Input)   │ │ (LLM Output)    │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │               │               │
         ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Redacted Docs   │ │ Sanitized Logs  │ │ Filtered Resp   │
│ → Vector Store  │ │ Safe Processing │ │ → User          │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Supported PII Types

| Entity Type | Description | Example |
|-------------|-------------|---------|
| `EMAIL_ADDRESS` | Email addresses | user@example.com |
| `PHONE_NUMBER` | Phone numbers | +1-555-123-4567 |
| `US_SSN` | Social Security Numbers | 123-45-6789 |
| `CREDIT_CARD` | Credit card numbers | 4111-1111-1111-1111 |
| `PERSON` | Person names | John Smith |
| `LOCATION` | Physical locations | 123 Main St, NYC |
| `DATE_TIME` | Dates and times | January 15, 1990 |
| `IP_ADDRESS` | IP addresses | 192.168.1.1 |
| `IBAN_CODE` | International bank numbers | GB82 WEST 1234 5698 7654 32 |
| `US_PASSPORT` | US passport numbers | 123456789 |
| `US_DRIVER_LICENSE` | Driver's license numbers | D123-4567-8901 |
| `MEDICAL_LICENSE` | Medical license numbers | MD12345 |
| `CUSTOM` | Tenant-specific patterns | EMP-123456 |

## Components

| Component | Location | Purpose |
|-----------|----------|---------|
| PIIDetector | [services/shared/security/pii/detector.py](../../services/shared/security/pii/detector.py) | Core detection engine |
| PIIConfig | [services/shared/security/pii/config.py](../../services/shared/security/pii/config.py) | Configuration settings |
| PIIResponseFilter | [services/shared/security/pii/response_filter.py](../../services/shared/security/pii/response_filter.py) | LLM output filtering |
| TenantPIIConfig | [services/shared/security/pii/tenant_config.py](../../services/shared/security/pii/tenant_config.py) | Per-tenant settings |

## Redaction Modes

| Mode | Description | Example |
|------|-------------|---------|
| `MASK` | Replace with type label | `<EMAIL_ADDRESS>` |
| `HASH` | Replace with hash | `a7f3b2c1` |
| `ENCRYPT` | Reversible encryption | `ENC:xxxxx` |
| `REMOVE` | Delete entirely | `` |
| `SYNTHETIC` | Fake replacement | `user@example.com` |

## Configuration

### Basic Configuration

```python
from shared.security.pii import PIIConfig, PIIDetector

config = PIIConfig(
    enabled=True,
    language="en",
    score_threshold=0.7,
    entities=[
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
        "CREDIT_CARD", "US_SSN", "IBAN_CODE"
    ],
)

detector = PIIDetector(config)
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PII_DETECTION_ENABLED` | Enable PII detection | `true` |
| `PII_THRESHOLD` | Confidence threshold (0-1) | `0.7` |
| `PII_REDACTION_MODE` | Default redaction mode | `MASK` |
| `PII_LOG_DETECTIONS` | Log PII detections | `true` |
| `PII_REJECT_ON_DETECTION` | Block content with PII | `false` |

## Usage

### PII Detection

```python
from shared.security.pii import PIIDetector

detector = PIIDetector(default_threshold=0.7)

# Detect PII in text
result = detector.detect("Contact John at john@example.com or 555-123-4567")

print(result.has_pii)  # True
print(result.entity_count)  # 3

for entity in result.entities:
    print(f"{entity.entity_type}: {entity.text} (score: {entity.score})")
    # PERSON: John (score: 0.85)
    # EMAIL_ADDRESS: john@example.com (score: 0.99)
    # PHONE_NUMBER: 555-123-4567 (score: 0.95)
```

### PII Redaction

```python
from shared.security.pii import PIIRedactor, RedactionMode

redactor = PIIRedactor()

# Mask PII
result = redactor.redact(
    text="Contact John at john@example.com",
    entities=detection.entities,
    mode=RedactionMode.MASK,
)
print(result.redacted_text)
# "Contact <PERSON> at <EMAIL_ADDRESS>"

# Hash PII
result = redactor.redact(
    text="SSN: 123-45-6789",
    entities=detection.entities,
    mode=RedactionMode.HASH,
)
print(result.redacted_text)
# "SSN: a7f3b2c1"
```

### Custom Patterns

Add tenant-specific PII patterns:

```python
detector.add_custom_pattern(
    tenant_id="acme-corp",
    name="employee_id",
    pattern=r"EMP-\d{6}",
    entity_type="EMPLOYEE_ID",
    score=0.95,
)

# Detect with tenant patterns
result = detector.detect(
    "Employee EMP-123456 reported the issue",
    tenant_id="acme-corp",
)
```

## Pipeline Integration

### Ingestion Pipeline

```python
from shared.security.pii import PIIProcessor, PIIProcessingConfig

config = PIIProcessingConfig(
    enabled=True,
    detection_threshold=0.5,
    redaction_mode=RedactionMode.MASK,
    reject_on_pii=False,  # Set True to reject documents
    store_pii_mapping=False,  # Set True to store for authorized access
)

processor = PIIProcessor(detector, redactor, config)

# Process document during ingestion
content, metadata = await processor.process_document(
    content=document_text,
    document_id="doc-123",
    tenant_id="tenant-1",
)

# Content is now redacted
# Metadata includes: pii_found, pii_count, pii_types
```

### Query Sanitization

```python
from shared.security.pii import QuerySanitizer, QuerySanitizationConfig

config = QuerySanitizationConfig(
    enabled=True,
    detection_threshold=0.6,
    reject_queries_with_pii=False,
    redact_pii_in_logs=True,
    alert_on_pii_queries=True,
)

sanitizer = QuerySanitizer(detector, redactor, config)

# Sanitize user query
query_for_processing, query_for_logging, has_pii = await sanitizer.sanitize_query(
    query="What did john.doe@example.com say about the project?",
    tenant_id="tenant-1",
    user_id="user-123",
)

# query_for_processing: original query (for search)
# query_for_logging: "What did <EMAIL_ADDRESS> say about the project?"
# has_pii: True
```

### Response Filtering

```python
from shared.security.pii import ResponseFilter, ResponseFilterConfig

config = ResponseFilterConfig(
    enabled=True,
    detection_threshold=0.7,
    redact_pii=True,
    fail_on_pii=False,  # Set True to block responses
)

filter = ResponseFilter(detector, redactor, config)

# Filter LLM response before returning to user
filtered_response, metadata = await filter.filter_response(
    response="Based on the document, John Smith (SSN: 123-45-6789) submitted...",
    tenant_id="tenant-1",
    request_id="req-123",
)

# filtered_response: "Based on the document, <PERSON> (SSN: <US_SSN>) submitted..."
# metadata: {pii_filtered: True, pii_found: True, pii_count: 2}
```

## Tenant Configuration

### Per-Tenant Settings

```python
from shared.security.pii import TenantPIIConfig, load_tenant_pii_config

# Load from database
config = await load_tenant_pii_config("tenant-123", db_session)

# Or create programmatically
config = TenantPIIConfig(
    tenant_id="tenant-123",

    # Detection settings
    detection_enabled=True,
    detection_threshold=0.5,
    custom_patterns=[
        {"name": "project_id", "pattern": r"PROJ-\d{4}", "score": 0.9}
    ],

    # Ingestion settings
    ingestion_redaction_mode=RedactionMode.MASK,
    ingestion_reject_on_pii=False,
    ingestion_allowed_pii_types=["DATE_TIME"],  # Allow dates through

    # Query settings
    query_redact_in_logs=True,
    query_reject_with_pii=False,

    # Response settings
    response_redact_pii=True,
    response_fail_on_pii=False,

    # Compliance
    data_retention_days=90,
    pii_access_audit=True,
)
```

### Configuration API

```http
# Get tenant PII config
GET /api/v1/tenants/{tenant_id}/pii-config

# Update tenant PII config
PUT /api/v1/tenants/{tenant_id}/pii-config
Content-Type: application/json
{
    "detection_threshold": 0.6,
    "ingestion_redaction_mode": "hash",
    "custom_patterns": [
        {"name": "internal_id", "pattern": "INT-\\d{8}", "score": 0.95}
    ]
}
```

## Audit Logging

All PII detection events are logged:

```python
logger.info(
    "pii_detected",
    document_id=document_id,
    tenant_id=tenant_id,
    pii_count=len(entities),
    pii_types=[e.entity_type for e in entities],
)

logger.warning(
    "pii_in_query",
    tenant_id=tenant_id,
    user_id=user_id,
    pii_types=[e.entity_type for e in entities],
)
```

## Performance Considerations

### Caching

- spaCy model loaded once at startup
- Custom recognizers cached per tenant
- Detection results not cached (security)

### Async Processing

All PII operations support async for non-blocking I/O:

```python
# Async detection
result = await detector.detect_async(text)

# Async filtering
filtered = await filter.filter_response_async(response)
```

### Batch Processing

For bulk ingestion:

```python
# Process multiple documents
async def process_batch(documents: list[str]) -> list[tuple[str, dict]]:
    tasks = [
        processor.process_document(doc, f"doc-{i}", tenant_id)
        for i, doc in enumerate(documents)
    ]
    return await asyncio.gather(*tasks)
```

## Testing

### Unit Tests

```bash
pytest services/shared/security/pii/tests/ -v
```

### Test Examples

```python
def test_detects_email(detector):
    result = detector.detect("Contact us at john@example.com")
    assert result.has_pii
    assert any(e.entity_type == PIIType.EMAIL for e in result.entities)

def test_respects_threshold(detector):
    # Low confidence entities filtered out
    high_threshold_detector = PIIDetector(default_threshold=0.95)
    result = high_threshold_detector.detect("Maybe John mentioned...")
    # Person name with low confidence may be filtered

def test_custom_patterns(detector):
    detector.add_custom_pattern(
        tenant_id="test",
        name="emp_id",
        pattern=r"EMP-\d{6}",
    )
    result = detector.detect("Employee EMP-123456", tenant_id="test")
    assert result.has_pii
```

## Compliance

### GDPR Article 5

- Data minimization through automatic redaction
- Purpose limitation via tenant-specific rules
- Audit trail for all PII access

### HIPAA

- PHI detection (medical license, patient IDs)
- Access controls for PII mapping
- Audit logging requirements

### CCPA

- Consumer data identification
- Right to deletion support
- Data portability compliance

## Troubleshooting

### False Positives

Increase threshold or add to allow list:

```python
config = PIIConfig(
    score_threshold=0.8,  # Higher threshold
    entities=["EMAIL_ADDRESS", "CREDIT_CARD"],  # Only specific types
)
```

### Missing Detections

Lower threshold or add custom patterns:

```python
config = PIIConfig(
    score_threshold=0.5,  # Lower threshold
)

detector.add_custom_pattern(
    tenant_id="tenant-1",
    name="custom_id",
    pattern=r"ID-\d{10}",
    score=0.95,
)
```

### Performance Issues

- Ensure spaCy model `en_core_web_lg` is installed
- Use batch processing for bulk operations
- Consider sampling for high-volume streams

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| presidio-analyzer | 2.2+ | PII detection |
| presidio-anonymizer | 2.2+ | PII redaction |
| spacy | 3.5+ | NLP engine |
| en_core_web_lg | 3.5+ | English language model |

Install requirements:

```bash
pip install presidio-analyzer presidio-anonymizer
python -m spacy download en_core_web_lg
```

## Related Documentation

- [Security Overview](./README.md)
- [Audit Logging](../audit-logging.md)
- [Data Protection](./README.md#encryption)
- [Compliance](./README.md#compliance)
