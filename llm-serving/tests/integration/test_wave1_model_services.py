"""
Wave 1 Integration Tests - Model Services

Tests for verifying all three core services are operational:
- vLLM (US-5.1)
- Embedding Service (US-5.2)
- Reranker Service (US-5.3)

Run with: pytest tests/integration/test_wave1_model_services.py -v
Requires services to be running via docker-compose.
"""

import asyncio
import os
from typing import AsyncGenerator

import httpx
import numpy as np
import pytest

# Service URLs from environment or defaults
VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000")
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://localhost:8001")
RERANKER_URL = os.environ.get("RERANKER_URL", "http://localhost:8002")


@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async HTTP client."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


# =============================================================================
# vLLM Tests (US-5.1)
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_health(http_client: httpx.AsyncClient):
    """Test vLLM health endpoint."""
    response = await http_client.get(f"{VLLM_URL}/health")
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_list_models(http_client: httpx.AsyncClient):
    """Test vLLM models listing."""
    response = await http_client.get(f"{VLLM_URL}/v1/models")
    assert response.status_code == 200

    data = response.json()
    assert "data" in data
    assert len(data["data"]) > 0

    model = data["data"][0]
    assert "id" in model


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_chat_completion(http_client: httpx.AsyncClient):
    """Test vLLM chat completion."""
    # Get model name first
    models_response = await http_client.get(f"{VLLM_URL}/v1/models")
    model_name = models_response.json()["data"][0]["id"]

    response = await http_client.post(
        f"{VLLM_URL}/v1/chat/completions",
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": "What is 2+2? Answer with just the number."}],
            "max_tokens": 10,
            "temperature": 0.0,
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert "choices" in data
    assert len(data["choices"]) > 0
    assert "message" in data["choices"][0]
    assert data["choices"][0]["message"]["role"] == "assistant"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_chat_completion_streaming(http_client: httpx.AsyncClient):
    """Test vLLM streaming chat completion."""
    models_response = await http_client.get(f"{VLLM_URL}/v1/models")
    model_name = models_response.json()["data"][0]["id"]

    chunks = []
    async with http_client.stream(
        "POST",
        f"{VLLM_URL}/v1/chat/completions",
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": "Say hi"}],
            "max_tokens": 5,
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200

        async for line in response.aiter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunks.append(line)

    assert len(chunks) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_metrics(http_client: httpx.AsyncClient):
    """Test vLLM Prometheus metrics endpoint."""
    response = await http_client.get(f"{VLLM_URL}/metrics")
    assert response.status_code == 200
    assert "vllm" in response.text.lower() or "request" in response.text.lower()


# =============================================================================
# Embedding Service Tests (US-5.2)
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_health(http_client: httpx.AsyncClient):
    """Test embedding service health endpoint."""
    response = await http_client.get(f"{EMBEDDING_URL}/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["model_loaded"] is True
    assert data["embedding_dim"] == 1024


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_single_input(http_client: httpx.AsyncClient):
    """Test embedding with single string input."""
    response = await http_client.post(
        f"{EMBEDDING_URL}/v1/embeddings",
        json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": "Hello world",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["object"] == "list"
    assert len(data["data"]) == 1
    assert len(data["data"][0]["embedding"]) == 1024


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_batch_input(http_client: httpx.AsyncClient):
    """Test embedding with batch input."""
    texts = ["Hello", "World", "Test embedding"]

    response = await http_client.post(
        f"{EMBEDDING_URL}/v1/embeddings",
        json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": texts,
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert len(data["data"]) == 3
    for item in data["data"]:
        assert len(item["embedding"]) == 1024


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_normalized(http_client: httpx.AsyncClient):
    """Test embeddings are L2-normalized."""
    response = await http_client.post(
        f"{EMBEDDING_URL}/v1/embeddings",
        json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": "Test normalization",
        },
    )

    assert response.status_code == 200
    embedding = response.json()["data"][0]["embedding"]

    # Calculate L2 norm
    norm = np.linalg.norm(embedding)
    assert abs(norm - 1.0) < 0.001, f"Embedding norm {norm} should be ~1.0"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_query_prefix(http_client: httpx.AsyncClient):
    """Test query prefix for BGE models."""
    response = await http_client.post(
        f"{EMBEDDING_URL}/v1/embeddings",
        json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": "What is machine learning?",
            "input_type": "query",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["data"][0]["embedding"]) == 1024


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_metrics(http_client: httpx.AsyncClient):
    """Test embedding Prometheus metrics endpoint."""
    response = await http_client.get(f"{EMBEDDING_URL}/metrics")
    assert response.status_code == 200
    assert "embedding_requests_total" in response.text


# =============================================================================
# Reranker Service Tests (US-5.3)
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_health(http_client: httpx.AsyncClient):
    """Test reranker service health endpoint."""
    response = await http_client.get(f"{RERANKER_URL}/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["model_loaded"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_query_documents(http_client: httpx.AsyncClient):
    """Test reranking with query + documents."""
    response = await http_client.post(
        f"{RERANKER_URL}/rerank",
        json={
            "query": "What is machine learning?",
            "documents": [
                "Machine learning is a subset of AI.",
                "The weather is nice today.",
                "Deep learning uses neural networks.",
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert "results" in data
    assert len(data["results"]) == 3

    # Results should be sorted by score descending
    scores = [r["score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_pairs(http_client: httpx.AsyncClient):
    """Test reranking with pre-formed pairs."""
    response = await http_client.post(
        f"{RERANKER_URL}/rerank",
        json={
            "pairs": [
                {"query": "What is AI?", "document": "AI is artificial intelligence."},
                {"query": "What is ML?", "document": "ML is machine learning."},
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_top_k(http_client: httpx.AsyncClient):
    """Test top_k filtering."""
    response = await http_client.post(
        f"{RERANKER_URL}/rerank",
        json={
            "query": "test query",
            "documents": ["doc1", "doc2", "doc3", "doc4", "doc5"],
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_preserves_indices(http_client: httpx.AsyncClient):
    """Test that original indices are preserved."""
    response = await http_client.post(
        f"{RERANKER_URL}/rerank",
        json={
            "query": "test",
            "documents": ["doc0", "doc1", "doc2"],
        },
    )

    assert response.status_code == 200
    indices = {r["index"] for r in response.json()["results"]}
    assert indices == {0, 1, 2}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_relevance_ranking(http_client: httpx.AsyncClient):
    """Test that relevant documents rank higher."""
    response = await http_client.post(
        f"{RERANKER_URL}/rerank",
        json={
            "query": "How do neural networks work?",
            "documents": [
                "Neural networks are inspired by biological neurons.",
                "The stock market saw gains today.",
                "Deep learning models use multiple layers of neurons.",
            ],
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]

    # Stock market doc (index 1) should be ranked lowest
    stock_market_result = next(r for r in results if r["index"] == 1)
    assert stock_market_result == results[-1], "Irrelevant doc should be last"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_metrics(http_client: httpx.AsyncClient):
    """Test reranker Prometheus metrics endpoint."""
    response = await http_client.get(f"{RERANKER_URL}/metrics")
    assert response.status_code == 200
    assert "rerank_requests_total" in response.text


# =============================================================================
# Cross-Service Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_services_healthy(http_client: httpx.AsyncClient):
    """Verify all services are healthy."""
    services = [
        (VLLM_URL, "/health"),
        (EMBEDDING_URL, "/health"),
        (RERANKER_URL, "/health"),
    ]

    for base_url, health_path in services:
        response = await http_client.get(f"{base_url}{health_path}")
        assert response.status_code == 200, f"Service at {base_url} is not healthy"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_similarity(http_client: httpx.AsyncClient):
    """Test that similar texts have similar embeddings."""
    response = await http_client.post(
        f"{EMBEDDING_URL}/v1/embeddings",
        json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": [
                "The cat sat on the mat",
                "A cat was sitting on a mat",
                "The stock market crashed today",
            ],
        },
    )

    data = response.json()
    emb1 = np.array(data["data"][0]["embedding"])
    emb2 = np.array(data["data"][1]["embedding"])
    emb3 = np.array(data["data"][2]["embedding"])

    # Cosine similarity (embeddings are normalized)
    sim_12 = np.dot(emb1, emb2)
    sim_13 = np.dot(emb1, emb3)

    assert sim_12 > sim_13, "Similar sentences should have higher similarity"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_requests(http_client: httpx.AsyncClient):
    """Test handling concurrent requests across services."""

    async def make_embedding_request(i: int) -> int:
        response = await http_client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": f"Test text number {i}",
            },
        )
        return response.status_code

    async def make_rerank_request(i: int) -> int:
        response = await http_client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": f"Query {i}",
                "documents": [f"Document {j} for query {i}" for j in range(3)],
            },
        )
        return response.status_code

    # Run concurrent requests
    tasks = []
    for i in range(10):
        tasks.append(make_embedding_request(i))
        tasks.append(make_rerank_request(i))

    results = await asyncio.gather(*tasks)

    assert all(status == 200 for status in results), "All concurrent requests should succeed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
