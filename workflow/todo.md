# Ingestion Service - Remaining Work Items

This document contains refined, actionable tasks to bring the ingestion service to 100% completion against all user stories (US-2.1 through US-2.12). Each task is detailed enough for an LLM agent to pick up and implement independently.

## Status Summary

| User Story | Current | Target | Gap |
|------------|---------|--------|-----|
| US-2.1 Source Connectors | 100% | 100% | - |
| US-2.2 Document Parsers | 85% | 100% | 3 tasks |
| US-2.3 Chunking Engine | 100% | 100% | - |
| US-2.4 Embedding Service | 100% | 100% | - |
| US-2.5 Index Writers | 100% | 100% | - |
| US-2.6 Metadata Enrichment | 100% | 100% | - |
| US-2.7 Async Processing | 100% | 100% | - |
| US-2.8 Ingestion API | 97% | 100% | 1 task |
| US-2.9 Embedding Migration | 95% | 100% | 2 tasks |
| US-2.10 Sync & Reembed APIs | 100% | 100% | - |
| US-2.11 Deduplication | 100% | 100% | - |
| US-2.12 Schema Alignment | 95% | 100% | 2 tasks |

---

## Task List

### TASK-001: Add YAML Frontmatter Extraction to Markdown Parser

**Priority:** Medium
**User Story:** US-2.2 Document Parsers
**Estimated Effort:** Small
**File:** `services/ingestion/processors/parsers/markdown.py`

#### Context
The Markdown parser currently extracts text, code blocks, and tables, but does not extract YAML frontmatter metadata commonly found in documentation files (title, author, date, tags, etc.).

#### Requirements
1. Detect YAML frontmatter between `---` delimiters at the start of the file
2. Parse YAML content and merge into `ParsedDocument.metadata`
3. Extract common fields: `title`, `author`, `date`, `tags`, `description`
4. Remove frontmatter from the `text` field (don't double-include)
5. Handle malformed YAML gracefully (log warning, continue parsing)

#### Implementation Details

```python
# Add to MarkdownParser class

def _extract_frontmatter(self, text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown.

    Args:
        text: Raw markdown text.

    Returns:
        Tuple of (frontmatter_dict, remaining_text)
    """
    import yaml

    if not text.startswith("---"):
        return {}, text

    # Find closing delimiter
    end_match = re.search(r"\n---\s*\n", text[3:])
    if not end_match:
        return {}, text

    yaml_content = text[3:end_match.start() + 3]
    remaining_text = text[end_match.end() + 3:]

    try:
        frontmatter = yaml.safe_load(yaml_content) or {}
        return frontmatter, remaining_text
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse frontmatter: {e}")
        return {}, text
```

Update `parse()` method to call `_extract_frontmatter()` before other processing.

#### Test Cases
Add to `services/ingestion/processors/parsers/tests/test_parsers.py`:

```python
@pytest.mark.asyncio
async def test_markdown_frontmatter_extraction():
    """Test YAML frontmatter is extracted from markdown."""
    content = b'''---
title: My Document
author: John Doe
date: 2024-01-15
tags:
  - python
  - docs
---

# Introduction

This is the content.
'''
    parser = MarkdownParser()
    result = await parser.parse(content)

    assert result.metadata.get("title") == "My Document"
    assert result.metadata.get("author") == "John Doe"
    assert result.metadata.get("tags") == ["python", "docs"]
    assert "---" not in result.text  # Frontmatter removed from text


@pytest.mark.asyncio
async def test_markdown_malformed_frontmatter():
    """Test malformed YAML frontmatter is handled gracefully."""
    content = b'''---
title: [invalid yaml
---

# Content
'''
    parser = MarkdownParser()
    result = await parser.parse(content)

    # Should parse successfully, just without frontmatter
    assert "Content" in result.text
```

#### Dependencies
- `pyyaml` (already in requirements.txt)

#### Acceptance Criteria
- [ ] YAML frontmatter is extracted and added to metadata
- [ ] Common fields (title, author, date, tags) are accessible
- [ ] Malformed YAML logs warning but doesn't fail parsing
- [ ] Frontmatter is not duplicated in text content
- [ ] Tests pass

---

### TASK-002: Implement OCR Support for Scanned PDFs

**Priority:** Medium
**User Story:** US-2.2 Document Parsers
**Estimated Effort:** Medium
**File:** `services/ingestion/processors/parsers/pdf.py`

#### Context
The PDF parser has OCR configuration (`ocr_enabled`, `ocr_language`) but the actual OCR implementation is missing. Scanned PDFs currently return empty or minimal text.

#### Requirements
1. Detect when a PDF page has no extractable text (scanned image)
2. Use Tesseract OCR via pytesseract to extract text from page images
3. Make OCR optional via `PDFParserConfig.ocr_enabled`
4. Support language configuration via `PDFParserConfig.ocr_language`
5. Handle OCR failures gracefully

#### Implementation Details

```python
# Add to PDFParser class

async def _ocr_page(self, page) -> str:
    """Extract text from page using OCR.

    Args:
        page: PyMuPDF page object.

    Returns:
        OCR-extracted text.
    """
    import pytesseract
    from PIL import Image

    # Render page to image
    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR
    pix = page.get_pixmap(matrix=mat)

    # Convert to PIL Image
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    # Run OCR
    try:
        text = pytesseract.image_to_string(
            img,
            lang=self.config.ocr_language
        )
        return text.strip()
    except Exception as e:
        logger.warning(f"OCR failed: {e}")
        return ""


async def _parse_with_pymupdf(self, content: bytes, metadata: dict) -> ParsedDocument:
    # ... existing code ...

    for page_num in range(pages_to_process):
        page = doc[page_num]
        text = page.get_text("text")

        # If no text and OCR enabled, try OCR
        if not text.strip() and self.config.ocr_enabled:
            logger.info(f"Page {page_num + 1} has no text, attempting OCR")
            text = await self._ocr_page(page)

        # ... rest of existing code ...
```

#### Test Cases

```python
@pytest.mark.asyncio
async def test_pdf_ocr_scanned_document(sample_scanned_pdf):
    """Test OCR extraction from scanned PDF."""
    parser = PDFParser(PDFParserConfig(ocr_enabled=True))
    result = await parser.parse(sample_scanned_pdf)

    # Should have extracted text via OCR
    assert len(result.text) > 100
    assert result.metadata.get("ocr_applied") == True


@pytest.mark.asyncio
async def test_pdf_ocr_disabled():
    """Test OCR is skipped when disabled."""
    parser = PDFParser(PDFParserConfig(ocr_enabled=False))
    result = await parser.parse(sample_scanned_pdf)

    # Should have minimal/no text
    assert len(result.text) < 50
```

#### Dependencies
- `pytesseract` - Add to requirements.txt
- `pillow` - Already in requirements.txt
- System: `tesseract-ocr` must be installed on the host

#### Docker Update
Add to `services/ingestion/Dockerfile`:
```dockerfile
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng
```

#### Acceptance Criteria
- [ ] Scanned PDFs return extracted text via OCR
- [ ] OCR is only applied to pages with no extractable text
- [ ] OCR can be disabled via configuration
- [ ] Language is configurable
- [ ] OCR failures are logged but don't fail parsing
- [ ] Dockerfile updated with tesseract dependency
- [ ] Tests pass

---

### TASK-003: Add JSON Parser for Structured Data

**Priority:** Low
**User Story:** US-2.2 Document Parsers
**Estimated Effort:** Small
**File:** `services/ingestion/processors/parsers/json_parser.py` (new file)

#### Context
The architecture mentions JSON as a potential source format, but no JSON parser exists. This is useful for ingesting structured data exports, API responses saved to files, etc.

#### Requirements
1. Parse JSON files and extract text content
2. Support configurable content field extraction
3. Handle nested structures by flattening to text
4. Extract metadata from designated fields

#### Implementation Details

```python
"""JSON document parser."""

import json
import logging
from typing import Optional

from .base import BaseParser, ContentBlock, ContentType, ParsedDocument

logger = logging.getLogger(__name__)


class JSONParser(BaseParser):
    """Parser for JSON documents."""

    def __init__(self, content_fields: list[str] = None, metadata_fields: list[str] = None):
        """Initialize JSON parser.

        Args:
            content_fields: Fields to extract as content (default: ["content", "text", "body"])
            metadata_fields: Fields to extract as metadata (default: ["title", "author", "date"])
        """
        self.content_fields = content_fields or ["content", "text", "body", "description"]
        self.metadata_fields = metadata_fields or ["title", "author", "date", "id", "url"]

    @property
    def supported_mime_types(self) -> list[str]:
        return ["application/json"]

    async def parse(self, content: bytes, metadata: Optional[dict] = None) -> ParsedDocument:
        metadata = metadata or {}

        try:
            data = json.loads(content.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        # Handle array of objects
        if isinstance(data, list):
            return self._parse_array(data, metadata)

        # Handle single object
        return self._parse_object(data, metadata)

    def _parse_object(self, data: dict, metadata: dict) -> ParsedDocument:
        texts = []
        extracted_metadata = {}

        # Extract content fields
        for field in self.content_fields:
            if field in data:
                value = data[field]
                if isinstance(value, str):
                    texts.append(value)
                elif isinstance(value, (list, dict)):
                    texts.append(json.dumps(value, indent=2))

        # Extract metadata fields
        for field in self.metadata_fields:
            if field in data:
                extracted_metadata[field] = data[field]

        # If no content fields found, flatten entire object
        if not texts:
            texts.append(self._flatten_to_text(data))

        return ParsedDocument(
            text="\n\n".join(texts),
            blocks=[ContentBlock(content_type=ContentType.TEXT, content=t, position=i)
                    for i, t in enumerate(texts)],
            title=extracted_metadata.get("title"),
            metadata={**metadata, **extracted_metadata}
        )

    def _flatten_to_text(self, data: dict, prefix: str = "") -> str:
        """Flatten nested dict to readable text."""
        lines = []
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                lines.append(self._flatten_to_text(value, full_key))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        lines.append(self._flatten_to_text(item, f"{full_key}[{i}]"))
                    else:
                        lines.append(f"{full_key}[{i}]: {item}")
            else:
                lines.append(f"{full_key}: {value}")
        return "\n".join(lines)
```

#### Registration
Update `services/ingestion/processors/parsers/registry.py`:
```python
from .json_parser import JSONParser

# In ParserRegistry.__init__
self.register(JSONParser())
```

#### Test Cases

```python
@pytest.mark.asyncio
async def test_json_parser_object():
    content = b'{"title": "Test", "content": "Hello world", "author": "Jane"}'
    parser = JSONParser()
    result = await parser.parse(content)

    assert "Hello world" in result.text
    assert result.title == "Test"
    assert result.metadata.get("author") == "Jane"


@pytest.mark.asyncio
async def test_json_parser_array():
    content = b'[{"text": "First"}, {"text": "Second"}]'
    parser = JSONParser()
    result = await parser.parse(content)

    assert "First" in result.text
    assert "Second" in result.text
```

#### Acceptance Criteria
- [ ] JSON files are parsed successfully
- [ ] Content is extracted from configurable fields
- [ ] Metadata is extracted from designated fields
- [ ] Nested structures are flattened to readable text
- [ ] Parser is registered in the registry
- [ ] Tests pass

---

### TASK-004: Add OpenAPI Schema Examples to Match Architecture

**Priority:** Low
**User Story:** US-2.8 Ingestion API
**Estimated Effort:** Small
**Files:** `services/ingestion/api/schemas/*.py`

#### Context
The OpenAPI documentation should include request/response examples that match the architecture.md specification exactly. This ensures API consumers have clear, accurate documentation.

#### Requirements
1. Add `json_schema_extra` with examples to all Pydantic schemas
2. Examples must match `docs/architecture.md` API section
3. Include both success and error response examples

#### Implementation Details

Update `services/ingestion/api/schemas/ingest.py`:

```python
class SyncRequest(BaseModel):
    """Request to start incremental sync."""
    source_type: SourceType
    source_config: dict
    options: Optional[IngestOptions] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_type": "filesystem",
                    "source_config": {
                        "path": "/data/documents",
                        "recursive": True,
                        "include_patterns": ["*.pdf", "*.docx"]
                    },
                    "options": {
                        "chunking_strategy": "recursive",
                        "target_tokens": 300
                    }
                }
            ]
        }
    )


class SyncResponse(BaseModel):
    """Response from sync request."""
    job_id: UUID
    status: str
    estimated_documents: Optional[int] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "status": "queued",
                    "estimated_documents": 150
                }
            ]
        }
    )
```

Update `services/ingestion/api/schemas/migrations.py`:

```python
class MigrationStartRequest(BaseModel):
    """Request to start embedding migration."""
    target_model: str
    scope: Optional[dict] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "target_model": "BAAI/bge-m3",
                    "scope": {
                        "tenant_id": "550e8400-e29b-41d4-a716-446655440000"
                    }
                }
            ]
        }
    )
```

#### Test Cases

```python
def test_openapi_schema_has_examples():
    """Test that OpenAPI schema includes examples."""
    from fastapi.testclient import TestClient
    from ingestion.run import app

    client = TestClient(app)
    response = client.get("/openapi.json")
    schema = response.json()

    # Check SyncRequest has examples
    sync_schema = schema["components"]["schemas"]["SyncRequest"]
    assert "examples" in sync_schema

    # Check example has required fields
    example = sync_schema["examples"][0]
    assert "source_type" in example
    assert "source_config" in example
```

#### Acceptance Criteria
- [ ] All request schemas have examples matching architecture.md
- [ ] All response schemas have examples
- [ ] OpenAPI JSON includes examples
- [ ] Swagger UI displays examples correctly
- [ ] Tests pass

---

### TASK-005: Add Automated Rollback Tests for Migration

**Priority:** Medium
**User Story:** US-2.9 Embedding Model Migration
**Estimated Effort:** Medium
**File:** `services/ingestion/migrations/tests/test_embedding_migrator.py`

#### Context
The embedding migrator has rollback capability (`rollback_migration()`), but needs comprehensive tests to ensure rollback works correctly in various failure scenarios.

#### Requirements
1. Test rollback after partial migration
2. Test rollback after validation failure
3. Test rollback preserves original data
4. Test concurrent access during rollback
5. Test alias switching during rollback

#### Implementation Details

```python
# Add to test_embedding_migrator.py

@pytest.mark.asyncio
async def test_rollback_after_partial_migration(migrator, mock_qdrant):
    """Test rollback correctly restores state after partial migration."""
    # Setup: Start migration, process 50%
    job_id = await migrator.start_migration(
        target_model="bge-m3",
        scope={"tenant_id": str(uuid4())}
    )

    # Simulate partial progress
    await mock_qdrant.simulate_partial_migration(job_id, progress=0.5)

    # Trigger rollback
    result = await migrator.rollback_migration(job_id)

    assert result["status"] == "rolled_back"
    assert result["documents_restored"] == 50

    # Verify original collection is active
    assert await mock_qdrant.get_active_collection() == "documents"

    # Verify new collection was deleted
    assert not await mock_qdrant.collection_exists(f"documents_migration_{job_id}")


@pytest.mark.asyncio
async def test_rollback_after_validation_failure(migrator, mock_qdrant):
    """Test rollback when validation detects quality regression."""
    job_id = await migrator.start_migration(
        target_model="bge-m3",
        scope={"tenant_id": str(uuid4())}
    )

    # Complete migration
    await mock_qdrant.complete_migration(job_id)

    # Mock validation failure
    with patch.object(migrator, 'validate_migration', return_value={
        "passed": False,
        "reason": "Quality regression detected",
        "metrics": {"recall_drop": 0.15}
    }):
        result = await migrator.rollback_migration(job_id)

    assert result["status"] == "rolled_back"
    assert result["reason"] == "validation_failure"


@pytest.mark.asyncio
async def test_rollback_preserves_original_embeddings(migrator, mock_qdrant, sample_documents):
    """Test that rollback preserves original embedding vectors."""
    # Store original embeddings
    original_embeddings = await mock_qdrant.get_all_embeddings("documents")

    # Start and partially complete migration
    job_id = await migrator.start_migration(target_model="bge-m3", scope={})
    await mock_qdrant.simulate_partial_migration(job_id, progress=0.7)

    # Rollback
    await migrator.rollback_migration(job_id)

    # Verify original embeddings unchanged
    current_embeddings = await mock_qdrant.get_all_embeddings("documents")
    assert original_embeddings == current_embeddings


@pytest.mark.asyncio
async def test_rollback_alias_switching(migrator, mock_qdrant):
    """Test that alias correctly switches back during rollback."""
    job_id = await migrator.start_migration(target_model="bge-m3", scope={})

    # Complete migration and switch alias
    await mock_qdrant.complete_migration(job_id)
    await migrator.switch_to_new_collection(job_id)

    # Verify alias points to new collection
    assert await mock_qdrant.get_alias_target("documents") == f"documents_v2"

    # Rollback
    await migrator.rollback_migration(job_id)

    # Verify alias points back to original
    assert await mock_qdrant.get_alias_target("documents") == "documents_v1"


@pytest.mark.asyncio
async def test_rollback_idempotent(migrator):
    """Test that calling rollback multiple times is safe."""
    job_id = await migrator.start_migration(target_model="bge-m3", scope={})

    # Rollback twice
    result1 = await migrator.rollback_migration(job_id)
    result2 = await migrator.rollback_migration(job_id)

    assert result1["status"] == "rolled_back"
    assert result2["status"] == "already_rolled_back"
```

#### Acceptance Criteria
- [ ] Partial migration rollback works correctly
- [ ] Validation failure triggers proper rollback
- [ ] Original embeddings are preserved
- [ ] Alias switching works both directions
- [ ] Rollback is idempotent
- [ ] Tests pass

---

### TASK-006: Add Migration Validation Sample Size Configuration

**Priority:** Low
**User Story:** US-2.9 Embedding Model Migration
**Estimated Effort:** Small
**File:** `services/ingestion/migrations/embedding_migrator.py`

#### Context
The migrator validates migration quality using sample queries, but the sample size and validation thresholds should be configurable.

#### Requirements
1. Add validation configuration to migration start request
2. Allow configuring: sample_size, recall_threshold, latency_threshold
3. Store validation config in job record
4. Use defaults from architecture spec if not provided

#### Implementation Details

```python
# Add to embedding_migrator.py

@dataclass
class ValidationConfig:
    """Configuration for migration validation."""
    sample_size: int = 100
    recall_threshold: float = 0.95  # Min acceptable recall@10
    latency_threshold_ms: int = 100  # Max acceptable p95 latency


class EmbeddingMigrator:
    async def start_migration(
        self,
        target_model: str,
        scope: dict,
        validation_config: Optional[ValidationConfig] = None
    ) -> UUID:
        """Start embedding migration with optional validation configuration."""
        config = validation_config or ValidationConfig()

        job = EmbeddingJob(
            target_model=target_model,
            scope=scope,
            validation_config=asdict(config),
            # ... rest of job creation
        )

        # ... existing code

    async def validate_migration(self, job_id: UUID) -> dict:
        """Validate migration using configured thresholds."""
        job = await self._get_job(job_id)
        config = ValidationConfig(**job.validation_config)

        # Get sample queries
        queries = await self._get_sample_queries(config.sample_size)

        # Run comparison
        results = {
            "passed": True,
            "sample_size": config.sample_size,
            "metrics": {}
        }

        recall_scores = []
        latencies = []

        for query in queries:
            # Search both collections
            old_results = await self._search_collection(
                self.old_collection, query, k=10
            )
            new_results = await self._search_collection(
                self.new_collection, query, k=10
            )

            # Calculate recall
            old_ids = set(r.id for r in old_results)
            new_ids = set(r.id for r in new_results)
            recall = len(old_ids & new_ids) / len(old_ids) if old_ids else 1.0
            recall_scores.append(recall)

            latencies.append(new_results.latency_ms)

        avg_recall = sum(recall_scores) / len(recall_scores)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        results["metrics"] = {
            "avg_recall": avg_recall,
            "p95_latency_ms": p95_latency,
            "recall_threshold": config.recall_threshold,
            "latency_threshold_ms": config.latency_threshold_ms
        }

        if avg_recall < config.recall_threshold:
            results["passed"] = False
            results["reason"] = f"Recall {avg_recall:.2f} below threshold {config.recall_threshold}"

        if p95_latency > config.latency_threshold_ms:
            results["passed"] = False
            results["reason"] = f"Latency {p95_latency}ms exceeds threshold {config.latency_threshold_ms}ms"

        return results
```

#### API Schema Update

```python
# Add to schemas/migrations.py

class ValidationConfigSchema(BaseModel):
    sample_size: int = Field(default=100, ge=10, le=1000)
    recall_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    latency_threshold_ms: int = Field(default=100, ge=10, le=10000)


class MigrationStartRequest(BaseModel):
    target_model: str
    scope: Optional[dict] = None
    validation_config: Optional[ValidationConfigSchema] = None
```

#### Acceptance Criteria
- [ ] Validation config is accepted in migration start request
- [ ] Default values match architecture specification
- [ ] Config is stored with job record
- [ ] Validation uses configured thresholds
- [ ] API schema documented
- [ ] Tests pass

---

### TASK-007: Add Schema Alignment Test

**Priority:** High
**User Story:** US-2.12 Schema Alignment & Logging
**Estimated Effort:** Medium
**File:** `services/ingestion/tests/test_schema_alignment.py` (new file)

#### Context
US-2.12 requires a test that validates ORM models match the architecture-defined schemas. This ensures schema drift is detected in CI.

#### Requirements
1. Validate `source_documents` table schema matches architecture.md
2. Validate `chunks` table schema matches architecture.md
3. Validate `embedding_jobs` table schema matches architecture.md
4. Check column types, constraints, and indexes
5. Fail CI if schemas don't match

#### Implementation Details

```python
"""Schema alignment tests (US-2.12).

Validates that ORM models match architecture-defined schemas from docs/architecture.md.
Run with: pytest tests/test_schema_alignment.py
"""

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from shared.database.models import SourceDocument, Chunk, EmbeddingJob
from shared.database.connection import get_engine


# Architecture-defined schema expectations
EXPECTED_SOURCE_DOCUMENTS_COLUMNS = {
    "id": {"type": "UUID", "nullable": False, "primary_key": True},
    "tenant_id": {"type": "UUID", "nullable": False},
    "source_type": {"type": "VARCHAR(50)", "nullable": False},
    "source_uri": {"type": "TEXT", "nullable": False},
    "external_id": {"type": "VARCHAR(255)", "nullable": True},
    "title": {"type": "TEXT", "nullable": True},
    "raw_location": {"type": "TEXT", "nullable": True},
    "content_hash": {"type": "VARCHAR(64)", "nullable": True},
    "ingested_at": {"type": "TIMESTAMP", "nullable": True},
    "updated_at": {"type": "TIMESTAMP", "nullable": True},
    "version": {"type": "INTEGER", "nullable": True, "default": 1},
    "schema_version": {"type": "VARCHAR(20)", "nullable": True},
    "visibility": {"type": "VARCHAR(50)", "nullable": True},
    "allowed_groups": {"type": "ARRAY", "nullable": True},
    "metadata": {"type": "JSONB", "nullable": True},
}

EXPECTED_CHUNKS_COLUMNS = {
    "id": {"type": "UUID", "nullable": False, "primary_key": True},
    "document_id": {"type": "UUID", "nullable": False, "foreign_key": "source_documents.id"},
    "chunk_index": {"type": "INTEGER", "nullable": False},
    "content": {"type": "TEXT", "nullable": False},
    "token_count": {"type": "INTEGER", "nullable": True},
    "embedding_model": {"type": "VARCHAR(100)", "nullable": True},
    "embedding_version": {"type": "VARCHAR(20)", "nullable": True},
    "created_at": {"type": "TIMESTAMP", "nullable": True},
    "metadata": {"type": "JSONB", "nullable": True},
}

EXPECTED_EMBEDDING_JOBS_COLUMNS = {
    "id": {"type": "UUID", "nullable": False, "primary_key": True},
    "status": {"type": "VARCHAR(20)", "nullable": True},
    "embedding_model": {"type": "VARCHAR(100)", "nullable": True},
    "target_scope": {"type": "JSONB", "nullable": True},
    "started_at": {"type": "TIMESTAMP", "nullable": True},
    "completed_at": {"type": "TIMESTAMP", "nullable": True},
    "error_message": {"type": "TEXT", "nullable": True},
    "stats": {"type": "JSONB", "nullable": True},
}

EXPECTED_INDEXES = {
    "source_documents": [
        "idx_docs_tenant",
        "idx_docs_source_type",
        "idx_docs_metadata"
    ],
    "chunks": [
        "idx_chunks_document"
    ],
}

EXPECTED_CONSTRAINTS = {
    "source_documents": [
        {"type": "unique", "columns": ["tenant_id", "source_uri", "content_hash"]}
    ],
    "chunks": [
        {"type": "unique", "columns": ["document_id", "chunk_index"]}
    ],
}


@pytest.fixture
def db_engine():
    """Get database engine for inspection."""
    return get_engine()


def test_source_documents_schema(db_engine):
    """Validate source_documents table matches architecture schema."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("source_documents")}

    for col_name, expected in EXPECTED_SOURCE_DOCUMENTS_COLUMNS.items():
        assert col_name in columns, f"Missing column: {col_name}"
        actual = columns[col_name]

        # Check nullable
        if "nullable" in expected:
            assert actual["nullable"] == expected["nullable"], \
                f"Column {col_name} nullable mismatch"


def test_chunks_schema(db_engine):
    """Validate chunks table matches architecture schema."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("chunks")}

    for col_name, expected in EXPECTED_CHUNKS_COLUMNS.items():
        assert col_name in columns, f"Missing column: {col_name}"


def test_embedding_jobs_schema(db_engine):
    """Validate embedding_jobs table matches architecture schema."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("embedding_jobs")}

    for col_name, expected in EXPECTED_EMBEDDING_JOBS_COLUMNS.items():
        assert col_name in columns, f"Missing column: {col_name}"


def test_required_indexes_exist(db_engine):
    """Validate required indexes exist per architecture spec."""
    inspector = inspect(db_engine)

    for table, expected_indexes in EXPECTED_INDEXES.items():
        actual_indexes = [idx["name"] for idx in inspector.get_indexes(table)]

        for idx in expected_indexes:
            assert idx in actual_indexes, \
                f"Missing index {idx} on table {table}"


def test_unique_constraints(db_engine):
    """Validate unique constraints per architecture spec."""
    inspector = inspect(db_engine)

    for table, constraints in EXPECTED_CONSTRAINTS.items():
        unique_constraints = inspector.get_unique_constraints(table)

        for expected in constraints:
            if expected["type"] == "unique":
                found = any(
                    set(uc["column_names"]) == set(expected["columns"])
                    for uc in unique_constraints
                )
                assert found, \
                    f"Missing unique constraint on {table}: {expected['columns']}"


def test_config_matches_architecture():
    """Validate config values match architecture specification."""
    from config import validate_architecture_config

    result = validate_architecture_config()

    assert result["embedding_dimensions"]["valid"]
    assert result["chunking_target_tokens"]["valid"]
    assert result["chunking_max_tokens"]["valid"]
    assert result["chunking_overlap_tokens"]["valid"]
```

#### Acceptance Criteria
- [ ] Test validates all three tables (source_documents, chunks, embedding_jobs)
- [ ] Column names and types are checked
- [ ] Required indexes are validated
- [ ] Unique constraints are validated
- [ ] Config validation is included
- [ ] Test runs in CI pipeline
- [ ] Tests pass

---

### TASK-008: Add Retrieval Logs Integration

**Priority:** Low
**User Story:** US-2.12 Schema Alignment & Logging
**Estimated Effort:** Small
**File:** `services/ingestion/services/documents.py`

#### Context
US-2.12 mentions persisting ingestion events to a retrieval_logs-compatible structure for downstream evaluation. Currently, ingestion events are only logged to stdout/OpenTelemetry but not persisted to PostgreSQL.

#### Requirements
1. Log significant ingestion events to a database table
2. Use structured format compatible with retrieval_logs
3. Include: tenant_id, document_id, job_id, event_type, timestamp, metadata
4. Enable async batch inserts to avoid blocking ingestion

#### Implementation Details

```python
# Add to services/ingestion/services/ingestion_logs.py (new file)

"""Ingestion event logging to PostgreSQL (US-2.12)."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from shared.database.connection import get_session


@dataclass
class IngestionLogEntry:
    """Ingestion log entry for persistence."""
    tenant_id: UUID
    event_type: str  # document_ingested, chunk_created, embedding_generated, etc.
    timestamp: datetime
    document_id: Optional[UUID] = None
    job_id: Optional[UUID] = None
    chunk_count: int = 0
    latency_ms: Optional[int] = None
    metadata: Optional[dict] = None


class IngestionLogWriter:
    """Async batch writer for ingestion logs."""

    def __init__(self, batch_size: int = 100, flush_interval: float = 5.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._buffer: list[IngestionLogEntry] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background flush task."""
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """Stop and flush remaining logs."""
        if self._flush_task:
            self._flush_task.cancel()
        await self._flush()

    async def log(self, entry: IngestionLogEntry):
        """Add log entry to buffer."""
        async with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.batch_size:
                await self._flush()

    async def _periodic_flush(self):
        """Periodically flush buffer."""
        while True:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def _flush(self):
        """Flush buffer to database."""
        async with self._lock:
            if not self._buffer:
                return

            entries = self._buffer
            self._buffer = []

        async with get_session() as session:
            # Bulk insert
            await session.execute(
                """
                INSERT INTO ingestion_logs
                (tenant_id, event_type, timestamp, document_id, job_id,
                 chunk_count, latency_ms, metadata)
                VALUES (:tenant_id, :event_type, :timestamp, :document_id,
                        :job_id, :chunk_count, :latency_ms, :metadata)
                """,
                [
                    {
                        "tenant_id": e.tenant_id,
                        "event_type": e.event_type,
                        "timestamp": e.timestamp,
                        "document_id": e.document_id,
                        "job_id": e.job_id,
                        "chunk_count": e.chunk_count,
                        "latency_ms": e.latency_ms,
                        "metadata": e.metadata,
                    }
                    for e in entries
                ]
            )
            await session.commit()


# Global instance
_log_writer: Optional[IngestionLogWriter] = None


async def get_log_writer() -> IngestionLogWriter:
    """Get or create log writer instance."""
    global _log_writer
    if _log_writer is None:
        _log_writer = IngestionLogWriter()
        await _log_writer.start()
    return _log_writer


async def log_ingestion_event(
    tenant_id: UUID,
    event_type: str,
    document_id: Optional[UUID] = None,
    job_id: Optional[UUID] = None,
    chunk_count: int = 0,
    latency_ms: Optional[int] = None,
    **metadata
):
    """Log an ingestion event to PostgreSQL."""
    writer = await get_log_writer()
    await writer.log(IngestionLogEntry(
        tenant_id=tenant_id,
        event_type=event_type,
        timestamp=datetime.utcnow(),
        document_id=document_id,
        job_id=job_id,
        chunk_count=chunk_count,
        latency_ms=latency_ms,
        metadata=metadata if metadata else None
    ))
```

#### Migration Required
Add migration for `ingestion_logs` table:

```python
# services/shared/database/migrations/versions/004_ingestion_logs.py

def upgrade():
    op.create_table(
        'ingestion_logs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('timestamp', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=True),
        sa.Column('job_id', sa.UUID(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), default=0),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
    )
    op.create_index('idx_ingestion_logs_tenant_time', 'ingestion_logs',
                    ['tenant_id', 'timestamp'])
```

#### Acceptance Criteria
- [ ] Ingestion events are persisted to PostgreSQL
- [ ] Async batch writing doesn't block ingestion
- [ ] Migration creates table with proper indexes
- [ ] Events include required fields (tenant_id, document_id, etc.)
- [ ] Tests pass

---

## Implementation Order

Recommended order based on dependencies and priority:

1. **TASK-007** - Schema alignment test (High priority, enables CI validation)
2. **TASK-001** - Markdown frontmatter (Medium priority, quick win)
3. **TASK-005** - Rollback tests (Medium priority, improves reliability)
4. **TASK-002** - OCR support (Medium priority, requires Docker changes)
5. **TASK-006** - Validation config (Low priority, enhancement)
6. **TASK-004** - OpenAPI examples (Low priority, documentation)
7. **TASK-003** - JSON parser (Low priority, nice to have)
8. **TASK-008** - Ingestion logs (Low priority, requires migration)

---

## Notes for LLM Agents

When implementing these tasks:

1. **Always read existing code first** - Use `mcp__serena__find_symbol` or read the file to understand current implementation
2. **Follow existing patterns** - Match code style, error handling, and logging patterns
3. **Add tests alongside code** - Every feature change needs corresponding tests
4. **Update requirements.txt** if adding dependencies
5. **Run tests locally** before marking complete: `pytest services/ingestion/`
6. **Reference architecture.md** for any API or schema decisions

Each task is self-contained and can be implemented independently.
