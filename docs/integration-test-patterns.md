# Integration Test Patterns

> **Applies to:** All Services  
> **Priority:** Standard  
> **Cross-Reference:** All refined user stories

## Overview

This document defines integration testing patterns for the Ultimate RAG Pipeline. Integration tests verify that components work correctly together across service boundaries.

## Test Categories

### 1. API Integration Tests

Test complete API workflows including authentication, request handling, and response validation.

```python
# tests/integration/test_ingestion_api.py
import pytest
from httpx import AsyncClient
from uuid import uuid4

@pytest.fixture
async def authenticated_client(test_app, test_user_token):
    """Create authenticated test client."""
    async with AsyncClient(
        app=test_app,
        base_url="http://test",
        headers={"Authorization": f"Bearer {test_user_token}"}
    ) as client:
        yield client

@pytest.fixture
def sample_document():
    """Create sample document for testing."""
    return {
        "source_type": "filesystem",
        "source_config": {
            "path": "/test/data/sample.pdf",
            "storage_type": "local"
        },
        "acl": {
            "tenant_id": str(uuid4()),
            "visibility": "private"
        }
    }

class TestIngestionWorkflow:
    """Integration tests for complete ingestion workflow."""
    
    @pytest.mark.integration
    async def test_ingest_document_e2e(
        self,
        authenticated_client: AsyncClient,
        sample_document: dict,
        wait_for_job
    ):
        """Test complete document ingestion flow."""
        # Step 1: Start ingestion
        response = await authenticated_client.post(
            "/api/v1/ingest",
            json=sample_document
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        
        # Step 2: Wait for job completion
        status = await wait_for_job(authenticated_client, job_id, timeout=60)
        assert status["status"] == "completed"
        assert status["documents_processed"] == 1
        
        # Step 3: Verify document in database
        doc_id = status["documents"][0]["id"]
        doc_response = await authenticated_client.get(f"/api/v1/documents/{doc_id}")
        assert doc_response.status_code == 200
        assert doc_response.json()["status"] == "active"
        
        # Step 4: Verify chunks exist
        chunks_response = await authenticated_client.get(
            f"/api/v1/documents/{doc_id}/chunks"
        )
        assert chunks_response.status_code == 200
        assert len(chunks_response.json()["chunks"]) > 0
    
    @pytest.mark.integration
    async def test_ingest_then_retrieve(
        self,
        authenticated_client: AsyncClient,
        sample_document: dict,
        wait_for_job
    ):
        """Test ingestion followed by retrieval."""
        # Ingest document
        response = await authenticated_client.post(
            "/api/v1/ingest",
            json=sample_document
        )
        job_id = response.json()["job_id"]
        await wait_for_job(authenticated_client, job_id)
        
        # Query the document
        retrieve_response = await authenticated_client.post(
            "/api/v1/retrieve",
            json={
                "query": "sample content from document",
                "top_k": 5
            }
        )
        
        assert retrieve_response.status_code == 200
        results = retrieve_response.json()["results"]
        assert len(results) > 0
```

### 2. Service-to-Service Integration Tests

Test communication between microservices.

```python
# tests/integration/test_service_integration.py
import pytest
from unittest.mock import patch

class TestRetrievalToOrchestrator:
    """Test integration between Retrieval and Orchestrator services."""
    
    @pytest.mark.integration
    async def test_orchestrator_calls_retrieval(
        self,
        orchestrator_client: AsyncClient,
        retrieval_service_mock
    ):
        """Test that orchestrator correctly calls retrieval service."""
        # Configure mock
        retrieval_service_mock.search.return_value = [
            {"chunk_id": "123", "content": "Test content", "score": 0.95}
        ]
        
        # Make query through orchestrator
        response = await orchestrator_client.post(
            "/api/v1/query",
            json={"query": "test question"}
        )
        
        assert response.status_code == 200
        
        # Verify retrieval was called
        retrieval_service_mock.search.assert_called_once()
        call_args = retrieval_service_mock.search.call_args
        assert "test question" in str(call_args)


class TestIngestionToVectorStore:
    """Test integration between Ingestion and Vector Store."""
    
    @pytest.mark.integration
    async def test_chunks_indexed_in_qdrant(
        self,
        ingestion_service,
        qdrant_client,
        sample_document
    ):
        """Test that ingested chunks appear in Qdrant."""
        # Ingest document
        doc_id = await ingestion_service.ingest(sample_document)
        
        # Query Qdrant directly
        results = await qdrant_client.scroll(
            collection_name="rag_chunks",
            scroll_filter={
                "must": [
                    {"key": "document_id", "match": {"value": str(doc_id)}}
                ]
            }
        )
        
        assert len(results[0]) > 0  # Chunks exist
        
        # Verify embedding dimensions
        for point in results[0]:
            assert len(point.vector) == 1024  # BGE dimension
```

### 3. Database Integration Tests

Test database operations with real PostgreSQL.

```python
# tests/integration/test_database.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

@pytest.fixture
async def db_session(test_db_engine):
    """Create test database session."""
    async with AsyncSession(test_db_engine) as session:
        yield session
        await session.rollback()

class TestDocumentRepository:
    """Database integration tests for document repository."""
    
    @pytest.mark.integration
    async def test_create_and_retrieve_document(
        self,
        db_session: AsyncSession,
        document_repository
    ):
        """Test document CRUD operations."""
        # Create document
        doc = await document_repository.create(
            session=db_session,
            source_id="test-source",
            source_type="file",
            title="Test Document",
            tenant_id=uuid4()
        )
        
        # Retrieve document
        retrieved = await document_repository.get_by_id(
            db_session,
            doc.id
        )
        
        assert retrieved is not None
        assert retrieved.title == "Test Document"
        assert retrieved.source_type == "file"
    
    @pytest.mark.integration
    async def test_cascade_delete(
        self,
        db_session: AsyncSession,
        document_repository,
        chunk_repository
    ):
        """Test that deleting document cascades to chunks."""
        # Create document with chunks
        doc = await document_repository.create(
            session=db_session,
            source_id="cascade-test",
            source_type="file",
            title="Cascade Test",
            tenant_id=uuid4()
        )
        
        # Add chunks
        for i in range(5):
            await chunk_repository.create(
                session=db_session,
                document_id=doc.id,
                chunk_index=i,
                content=f"Chunk {i} content"
            )
        
        # Verify chunks exist
        chunks = await chunk_repository.get_by_document(db_session, doc.id)
        assert len(chunks) == 5
        
        # Delete document
        await document_repository.delete(db_session, doc.id)
        
        # Verify chunks deleted
        chunks = await chunk_repository.get_by_document(db_session, doc.id)
        assert len(chunks) == 0
```

### 4. Message Queue Integration Tests

Test Celery task execution.

```python
# tests/integration/test_celery.py
import pytest
from celery.result import AsyncResult

class TestCeleryTasks:
    """Integration tests for Celery task execution."""
    
    @pytest.mark.integration
    async def test_ingestion_task_executes(
        self,
        celery_app,
        celery_worker,
        sample_document
    ):
        """Test that ingestion task runs successfully."""
        from tasks.ingest import process_document
        
        # Queue task
        result = process_document.delay(sample_document)
        
        # Wait for completion (with timeout)
        task_result = result.get(timeout=60)
        
        assert task_result["status"] == "success"
        assert "document_id" in task_result
    
    @pytest.mark.integration
    async def test_embedding_batch_task(
        self,
        celery_app,
        celery_worker
    ):
        """Test batch embedding task."""
        from tasks.embed import embed_batch
        
        texts = ["Text one", "Text two", "Text three"]
        
        result = embed_batch.delay(texts)
        embeddings = result.get(timeout=30)
        
        assert len(embeddings) == 3
        assert all(len(e) == 1024 for e in embeddings)
```

## Test Fixtures

### Shared Fixtures

```python
# tests/conftest.py
import pytest
import asyncio
from httpx import AsyncClient
import docker

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def docker_services():
    """Start Docker services for integration tests."""
    client = docker.from_env()
    
    # Start services
    containers = []
    for service in ["postgres", "qdrant", "redis", "opensearch"]:
        container = client.containers.run(
            f"rag-pipeline-{service}",
            detach=True,
            remove=True
        )
        containers.append(container)
    
    # Wait for services to be ready
    import time
    time.sleep(10)
    
    yield containers
    
    # Cleanup
    for container in containers:
        container.stop()

@pytest.fixture
async def wait_for_job():
    """Factory fixture to wait for job completion."""
    async def _wait(client: AsyncClient, job_id: str, timeout: int = 30):
        import asyncio
        start = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start) < timeout:
            response = await client.get(f"/api/v1/ingest/{job_id}")
            status = response.json()
            
            if status["status"] in ["completed", "failed"]:
                return status
            
            await asyncio.sleep(1)
        
        raise TimeoutError(f"Job {job_id} did not complete in {timeout}s")
    
    return _wait

@pytest.fixture
def test_user_token():
    """Generate test JWT token."""
    import jwt
    from datetime import datetime, timedelta
    
    payload = {
        "sub": "test-user-id",
        "tenant_id": "test-tenant-id",
        "roles": ["user"],
        "groups": ["engineering"],
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    
    return jwt.encode(payload, "test-secret", algorithm="HS256")
```

## Running Integration Tests

```bash
# Run all integration tests
pytest tests/integration/ -v -m integration

# Run with Docker services (using docker-compose)
docker-compose -f docker-compose.test.yml up -d
pytest tests/integration/ -v -m integration
docker-compose -f docker-compose.test.yml down

# Run specific test category
pytest tests/integration/test_ingestion_api.py -v

# Run with coverage
pytest tests/integration/ -v --cov=services --cov-report=html

# Run in CI with retries for flaky tests
pytest tests/integration/ -v --reruns 2 --reruns-delay 5
```

## CI/CD Integration

```yaml
# .github/workflows/integration-tests.yml
name: Integration Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_rag
        ports:
          - 5432:5432
      
      qdrant:
        image: qdrant/qdrant:latest
        ports:
          - 6333:6333
      
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      
      - name: Run integration tests
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_rag
          QDRANT_URL: http://localhost:6333
          REDIS_URL: redis://localhost:6379
        run: |
          pytest tests/integration/ -v -m integration --junitxml=integration-results.xml
      
      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: integration-test-results
          path: integration-results.xml
```

## Best Practices

1. **Isolation**: Each test should clean up after itself
2. **Idempotency**: Tests should be runnable in any order
3. **Timeouts**: Always use timeouts for async operations
4. **Mocking External Services**: Mock third-party APIs but use real infrastructure
5. **Test Data**: Use factory fixtures for consistent test data
6. **Parallelization**: Design tests to run in parallel where possible
