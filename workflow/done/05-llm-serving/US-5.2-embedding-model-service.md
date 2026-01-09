# US-5.2: Embedding Model Service

> **Story ID:** US-5.2  
> **Epic:** LLM Serving Layer  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** Epic 1 (Infrastructure - GPU nodes)

## User Story

**As a** developer  
**I want** embedding model served efficiently  
**So that** ingestion and retrieval have fast embeddings

## Context

The Embedding Model Service provides high-throughput vector embedding generation for document ingestion and query processing. It serves the BAAI/bge-large-en-v1.5 model (1024 dimensions) via a REST API with support for batch inference, request queuing, and GPU acceleration.

Key features:
- High-throughput batch inference
- OpenAI-compatible `/v1/embeddings` endpoint
- GPU acceleration with automatic batching
- Request queuing for optimal GPU utilization
- Support for query/passage prefixes (BGE-style)
- Prometheus metrics for monitoring

## Technical Requirements

### Directory Structure

```
llm-serving/
└── embedding-service/
    ├── Dockerfile
    ├── api/
    │   ├── __init__.py
    │   ├── main.py              # FastAPI application
    │   ├── routes.py            # API routes
    │   ├── models.py            # Pydantic models
    │   └── dependencies.py      # Dependency injection
    ├── core/
    │   ├── __init__.py
    │   ├── embedder.py          # Embedding generation
    │   ├── batching.py          # Dynamic batching
    │   └── model_loader.py      # Model loading utilities
    ├── k8s/
    │   ├── configmap.yaml
    │   ├── deployment.yaml
    │   ├── service.yaml
    │   └── hpa.yaml
    ├── config.py                # Configuration
    └── requirements.txt
```

### Data Models

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Union
from enum import Enum
from uuid import UUID, uuid4

class EmbeddingModel(str, Enum):
    BGE_LARGE = "BAAI/bge-large-en-v1.5"
    BGE_BASE = "BAAI/bge-base-en-v1.5"
    BGE_SMALL = "BAAI/bge-small-en-v1.5"

class EmbeddingServiceConfig(BaseModel):
    """Configuration for the embedding service."""
    
    # Model settings
    model_name: str = "BAAI/bge-large-en-v1.5"
    model_revision: Optional[str] = None
    embedding_dim: int = 1024
    max_sequence_length: int = 512
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8001
    
    # Batching settings
    max_batch_size: int = 32
    max_batch_tokens: int = 8192
    batch_timeout_ms: float = 50.0  # Max wait for batch to fill
    
    # GPU settings
    device: str = "cuda"  # cuda or cpu
    use_fp16: bool = True
    normalize_embeddings: bool = True
    
    # Queue settings
    max_queue_size: int = 1000
    worker_count: int = 1  # GPU workers
    
    # Caching
    enable_request_cache: bool = False
    cache_ttl_seconds: int = 3600

class EmbeddingRequest(BaseModel):
    """
    OpenAI-compatible embedding request.
    
    Supports both single string and list of strings as input.
    """
    model: str = "BAAI/bge-large-en-v1.5"
    input: Union[str, list[str]]
    encoding_format: Literal["float", "base64"] = "float"
    
    # Extension: prefix for BGE models
    input_type: Optional[Literal["query", "passage"]] = None
    
    # Request metadata
    user: Optional[str] = None
    request_id: UUID = Field(default_factory=uuid4)
    
    @field_validator("input")
    @classmethod
    def validate_input(cls, v):
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("Input cannot be empty")
        elif isinstance(v, list):
            if len(v) == 0:
                raise ValueError("Input list cannot be empty")
            if any(not s.strip() for s in v):
                raise ValueError("Input list cannot contain empty strings")
        return v

class EmbeddingData(BaseModel):
    """Single embedding in the response."""
    object: str = "embedding"
    index: int
    embedding: list[float]

class EmbeddingUsage(BaseModel):
    """Token usage for embedding request."""
    prompt_tokens: int
    total_tokens: int

class EmbeddingResponse(BaseModel):
    """OpenAI-compatible embedding response."""
    object: str = "list"
    model: str
    data: list[EmbeddingData]
    usage: EmbeddingUsage

class BatchEmbeddingRequest(BaseModel):
    """Batch embedding request for internal use."""
    texts: list[str]
    input_type: Optional[Literal["query", "passage"]] = None
    request_ids: list[UUID] = Field(default_factory=list)

class BatchEmbeddingResult(BaseModel):
    """Batch embedding result."""
    embeddings: list[list[float]]
    dimensions: int
    total_tokens: int
    processing_time_ms: float

class HealthResponse(BaseModel):
    """Health check response."""
    status: Literal["healthy", "unhealthy", "degraded"]
    model_loaded: bool
    model_name: str
    embedding_dim: int
    device: str
    gpu_available: bool
    gpu_memory_used_mb: Optional[float] = None
    queue_size: int
    uptime_seconds: float
```

### Embedding Service Core

```python
import torch
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import Optional
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    Core embedding generation service.
    
    Loads a sentence-transformers model and provides
    efficient batch embedding generation with GPU acceleration.
    """
    
    def __init__(self, config: EmbeddingServiceConfig):
        self.config = config
        self._model: Optional[SentenceTransformer] = None
        self._device: Optional[str] = None
        self._executor = ThreadPoolExecutor(max_workers=config.worker_count)
        self._lock = asyncio.Lock()
        self._startup_time = time.time()
    
    async def load_model(self):
        """Load the embedding model."""
        logger.info(f"Loading model: {self.config.model_name}")
        
        def _load():
            model = SentenceTransformer(
                self.config.model_name,
                revision=self.config.model_revision,
                device=self.config.device
            )
            
            # Set max sequence length
            model.max_seq_length = self.config.max_sequence_length
            
            # Enable FP16 if configured
            if self.config.use_fp16 and self.config.device == "cuda":
                model.half()
            
            return model
        
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(self._executor, _load)
        self._device = self.config.device
        
        logger.info(f"Model loaded on {self._device}")
        logger.info(f"Embedding dimension: {self.config.embedding_dim}")
    
    async def embed(
        self,
        texts: list[str],
        input_type: Optional[str] = None
    ) -> BatchEmbeddingResult:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of texts to embed
            input_type: "query" or "passage" for BGE prefix
        
        Returns:
            BatchEmbeddingResult with embeddings and metadata
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        start_time = time.time()
        
        # Add BGE prefix if specified
        if input_type == "query":
            texts = [f"query: {t}" for t in texts]
        elif input_type == "passage":
            texts = [f"passage: {t}" for t in texts]
        
        # Run embedding in thread pool to avoid blocking
        def _embed():
            with torch.no_grad():
                embeddings = self._model.encode(
                    texts,
                    batch_size=self.config.max_batch_size,
                    normalize_embeddings=self.config.normalize_embeddings,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
                return embeddings
        
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(self._executor, _embed)
        
        # Calculate approximate token count
        total_tokens = sum(len(t.split()) for t in texts)
        
        processing_time = (time.time() - start_time) * 1000
        
        return BatchEmbeddingResult(
            embeddings=embeddings.tolist(),
            dimensions=embeddings.shape[1],
            total_tokens=total_tokens,
            processing_time_ms=processing_time
        )
    
    async def embed_single(
        self,
        text: str,
        input_type: Optional[str] = None
    ) -> list[float]:
        """Embed a single text."""
        result = await self.embed([text], input_type)
        return result.embeddings[0]
    
    def get_health(self) -> HealthResponse:
        """Get service health status."""
        gpu_available = torch.cuda.is_available()
        gpu_memory = None
        
        if gpu_available and self._device == "cuda":
            gpu_memory = torch.cuda.memory_allocated() / 1024 / 1024
        
        return HealthResponse(
            status="healthy" if self._model is not None else "unhealthy",
            model_loaded=self._model is not None,
            model_name=self.config.model_name,
            embedding_dim=self.config.embedding_dim,
            device=self._device or "unknown",
            gpu_available=gpu_available,
            gpu_memory_used_mb=gpu_memory,
            queue_size=0,  # Will be updated by batching layer
            uptime_seconds=time.time() - self._startup_time
        )
    
    async def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=True)
        if self._model is not None:
            del self._model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
```

### Dynamic Batching

```python
import asyncio
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from uuid import UUID, uuid4
import time
import logging

logger = logging.getLogger(__name__)

@dataclass
class PendingRequest:
    """A pending embedding request in the queue."""
    request_id: UUID
    texts: list[str]
    input_type: Optional[str]
    future: asyncio.Future
    timestamp: float

class DynamicBatcher:
    """
    Dynamic batching layer for embedding requests.
    
    Collects incoming requests and batches them together
    for efficient GPU utilization. Batches are processed
    when either max_batch_size is reached or timeout expires.
    """
    
    def __init__(
        self,
        embed_fn: Callable[[list[str], Optional[str]], Awaitable[BatchEmbeddingResult]],
        max_batch_size: int = 32,
        max_batch_tokens: int = 8192,
        batch_timeout_ms: float = 50.0,
        max_queue_size: int = 1000
    ):
        self.embed_fn = embed_fn
        self.max_batch_size = max_batch_size
        self.max_batch_tokens = max_batch_tokens
        self.batch_timeout = batch_timeout_ms / 1000.0
        self.max_queue_size = max_queue_size
        
        self._queue: asyncio.Queue[PendingRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Metrics
        self._requests_processed = 0
        self._batches_processed = 0
        self._total_wait_time_ms = 0.0
    
    async def start(self):
        """Start the batching processor."""
        self._running = True
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info("Dynamic batcher started")
    
    async def stop(self):
        """Stop the batching processor."""
        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        logger.info("Dynamic batcher stopped")
    
    async def submit(
        self,
        texts: list[str],
        input_type: Optional[str] = None
    ) -> list[list[float]]:
        """
        Submit texts for embedding.
        
        Args:
            texts: List of texts to embed
            input_type: "query" or "passage" prefix
        
        Returns:
            List of embeddings
        """
        future = asyncio.get_event_loop().create_future()
        
        request = PendingRequest(
            request_id=uuid4(),
            texts=texts,
            input_type=input_type,
            future=future,
            timestamp=time.time()
        )
        
        await self._queue.put(request)
        
        return await future
    
    async def _process_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                batch = await self._collect_batch()
                
                if batch:
                    await self._process_batch(batch)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
    
    async def _collect_batch(self) -> list[PendingRequest]:
        """Collect requests into a batch."""
        batch: list[PendingRequest] = []
        total_texts = 0
        total_tokens = 0
        batch_input_type = None
        
        deadline = time.time() + self.batch_timeout
        
        while True:
            try:
                timeout = max(0, deadline - time.time())
                request = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=timeout if batch else None  # Wait indefinitely for first request
                )
                
                # Estimate tokens
                request_tokens = sum(len(t.split()) for t in request.texts)
                
                # Check if adding this request would exceed limits
                if batch and (
                    total_texts + len(request.texts) > self.max_batch_size or
                    total_tokens + request_tokens > self.max_batch_tokens or
                    (batch_input_type is not None and request.input_type != batch_input_type)
                ):
                    # Put request back and process current batch
                    await self._queue.put(request)
                    break
                
                batch.append(request)
                total_texts += len(request.texts)
                total_tokens += request_tokens
                batch_input_type = request.input_type
                
                # Check if batch is full
                if total_texts >= self.max_batch_size:
                    break
                    
            except asyncio.TimeoutError:
                # Timeout expired, process what we have
                break
        
        return batch
    
    async def _process_batch(self, batch: list[PendingRequest]):
        """Process a collected batch."""
        if not batch:
            return
        
        # Combine all texts
        all_texts = []
        text_counts = []
        input_type = batch[0].input_type
        
        for request in batch:
            all_texts.extend(request.texts)
            text_counts.append(len(request.texts))
        
        try:
            # Generate embeddings
            result = await self.embed_fn(all_texts, input_type)
            
            # Distribute results back to requests
            offset = 0
            for request, count in zip(batch, text_counts):
                request_embeddings = result.embeddings[offset:offset + count]
                request.future.set_result(request_embeddings)
                offset += count
                
                # Update metrics
                wait_time = (time.time() - request.timestamp) * 1000
                self._total_wait_time_ms += wait_time
                self._requests_processed += 1
            
            self._batches_processed += 1
            
        except Exception as e:
            # Propagate error to all requests
            for request in batch:
                if not request.future.done():
                    request.future.set_exception(e)
    
    def get_metrics(self) -> dict:
        """Get batcher metrics."""
        return {
            "queue_size": self._queue.qsize(),
            "requests_processed": self._requests_processed,
            "batches_processed": self._batches_processed,
            "avg_wait_time_ms": (
                self._total_wait_time_ms / self._requests_processed
                if self._requests_processed > 0 else 0
            )
        }
```

### FastAPI Application

```python
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response
import time
import logging

logger = logging.getLogger(__name__)

# Prometheus metrics
REQUESTS_TOTAL = Counter(
    "embedding_requests_total",
    "Total embedding requests",
    ["status", "model"]
)
REQUEST_LATENCY = Histogram(
    "embedding_request_latency_seconds",
    "Embedding request latency",
    ["model"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
BATCH_SIZE = Histogram(
    "embedding_batch_size",
    "Embedding batch sizes",
    buckets=[1, 2, 4, 8, 16, 32, 64, 128]
)
QUEUE_SIZE = Gauge(
    "embedding_queue_size",
    "Current queue size"
)
GPU_MEMORY = Gauge(
    "embedding_gpu_memory_mb",
    "GPU memory usage in MB"
)

# Global service instances
embedding_service: Optional[EmbeddingService] = None
batcher: Optional[DynamicBatcher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global embedding_service, batcher
    
    # Load configuration
    config = EmbeddingServiceConfig()
    
    # Initialize embedding service
    embedding_service = EmbeddingService(config)
    await embedding_service.load_model()
    
    # Initialize dynamic batcher
    batcher = DynamicBatcher(
        embed_fn=embedding_service.embed,
        max_batch_size=config.max_batch_size,
        max_batch_tokens=config.max_batch_tokens,
        batch_timeout_ms=config.batch_timeout_ms,
        max_queue_size=config.max_queue_size
    )
    await batcher.start()
    
    logger.info("Embedding service ready")
    
    yield
    
    # Cleanup
    await batcher.stop()
    await embedding_service.close()
    logger.info("Embedding service shutdown complete")

app = FastAPI(
    title="Embedding Service",
    description="High-throughput embedding generation with BGE models",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    """Add request timing header."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Request-Time"] = f"{duration:.4f}"
    return response

@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(request: EmbeddingRequest):
    """
    Create embeddings for the input text(s).
    
    OpenAI-compatible endpoint for embedding generation.
    Supports both single string and list of strings as input.
    """
    start_time = time.time()
    
    try:
        # Normalize input to list
        texts = [request.input] if isinstance(request.input, str) else request.input
        
        # Record batch size
        BATCH_SIZE.observe(len(texts))
        
        # Submit to batcher
        embeddings = await batcher.submit(texts, request.input_type)
        
        # Build response
        data = [
            EmbeddingData(index=i, embedding=emb)
            for i, emb in enumerate(embeddings)
        ]
        
        total_tokens = sum(len(t.split()) for t in texts)
        
        response = EmbeddingResponse(
            model=request.model,
            data=data,
            usage=EmbeddingUsage(
                prompt_tokens=total_tokens,
                total_tokens=total_tokens
            )
        )
        
        # Record metrics
        latency = time.time() - start_time
        REQUEST_LATENCY.labels(model=request.model).observe(latency)
        REQUESTS_TOTAL.labels(status="success", model=request.model).inc()
        
        return response
        
    except Exception as e:
        REQUESTS_TOTAL.labels(status="error", model=request.model).inc()
        logger.error(f"Embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed", response_model=BatchEmbeddingResult)
async def embed_batch(request: BatchEmbeddingRequest):
    """
    Batch embedding endpoint (non-OpenAI format).
    
    More efficient for internal use with direct list input.
    """
    try:
        embeddings = await batcher.submit(request.texts, request.input_type)
        
        return BatchEmbeddingResult(
            embeddings=embeddings,
            dimensions=len(embeddings[0]) if embeddings else 0,
            total_tokens=sum(len(t.split()) for t in request.texts),
            processing_time_ms=0  # Filled by batcher
        )
        
    except Exception as e:
        logger.error(f"Batch embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    health = embedding_service.get_health()
    
    # Update queue size from batcher
    if batcher:
        metrics = batcher.get_metrics()
        health.queue_size = metrics["queue_size"]
        QUEUE_SIZE.set(metrics["queue_size"])
    
    # Update GPU metrics
    if health.gpu_memory_used_mb:
        GPU_MEMORY.set(health.gpu_memory_used_mb)
    
    if health.status == "unhealthy":
        raise HTTPException(status_code=503, detail="Service unhealthy")
    
    return health

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )

@app.get("/v1/models")
async def list_models():
    """List available embedding models."""
    return {
        "object": "list",
        "data": [
            {
                "id": embedding_service.config.model_name,
                "object": "model",
                "owned_by": "bge",
                "permission": []
            }
        ]
    }
```

### Dockerfile

```dockerfile
# Embedding Service Dockerfile
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create non-root user
RUN useradd -m -u 1000 embedding
USER embedding
WORKDIR /app

# Copy application
COPY --chown=embedding:embedding . /app/

# Download model at build time (optional)
ARG PRELOAD_MODEL=false
RUN if [ "$PRELOAD_MODEL" = "true" ]; then \
    python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-large-en-v1.5')"; \
    fi

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

EXPOSE 8001

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

### Kubernetes Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: embedding-service
  namespace: llm-serving
  labels:
    app: embedding-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: embedding-service
  template:
    metadata:
      labels:
        app: embedding-service
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8001"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: embedding
          image: llm-serving/embedding-service:latest
          ports:
            - containerPort: 8001
          
          env:
            - name: MODEL_NAME
              value: "BAAI/bge-large-en-v1.5"
            - name: MAX_BATCH_SIZE
              value: "32"
            - name: MAX_BATCH_TOKENS
              value: "8192"
            - name: BATCH_TIMEOUT_MS
              value: "50"
            - name: USE_FP16
              value: "true"
          
          resources:
            requests:
              memory: "4Gi"
              cpu: "2"
              nvidia.com/gpu: "1"
            limits:
              memory: "8Gi"
              cpu: "4"
              nvidia.com/gpu: "1"
          
          livenessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 60
            periodSeconds: 30
          
          readinessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 30
            periodSeconds: 10
      
      nodeSelector:
        nvidia.com/gpu: "true"
      
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"
---
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: embedding-service
  namespace: llm-serving
spec:
  selector:
    app: embedding-service
  ports:
    - port: 8001
      targetPort: 8001
  type: ClusterIP
---
# k8s/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: embedding-service-hpa
  namespace: llm-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: embedding-service
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Pods
      pods:
        metric:
          name: embedding_queue_size
        target:
          type: AverageValue
          averageValue: "100"
```

## Acceptance Criteria

- [ ] BGE-large-en-v1.5 model deployed and loaded
- [ ] `/v1/embeddings` OpenAI-compatible endpoint working
- [ ] `/embed` batch endpoint working
- [ ] Embeddings are 1024-dimensional
- [ ] Batch inference support (max 32 per batch)
- [ ] Dynamic batching with configurable timeout
- [ ] GPU acceleration enabled
- [ ] FP16 inference working
- [ ] Request queuing for throughput
- [ ] Query/passage prefix support
- [ ] Normalization produces unit vectors
- [ ] Health check endpoint at `/health`
- [ ] Prometheus metrics at `/metrics`
- [ ] Latency < 50ms for single embedding
- [ ] Latency < 200ms for batch of 32

## Testing Requirements

```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
import numpy as np

EMBEDDING_URL = "http://localhost:8001"

@pytest.fixture
def mock_embedder():
    """Mock embedding service."""
    embedder = AsyncMock()
    embedder.embed.return_value = BatchEmbeddingResult(
        embeddings=[[0.1] * 1024],
        dimensions=1024,
        total_tokens=10,
        processing_time_ms=5.0
    )
    return embedder

@pytest.mark.asyncio
async def test_openai_compatible_single_input():
    """Test single string input."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": "Hello world"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert len(data["data"][0]["embedding"]) == 1024

@pytest.mark.asyncio
async def test_openai_compatible_batch_input():
    """Test list of strings input."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": ["Hello", "World", "Test"]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3
        for item in data["data"]:
            assert len(item["embedding"]) == 1024

@pytest.mark.asyncio
async def test_query_prefix():
    """Test query prefix is applied."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": "What is machine learning?",
                "input_type": "query"
            }
        )
        
        assert response.status_code == 200

@pytest.mark.asyncio
async def test_passage_prefix():
    """Test passage prefix is applied."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": "Machine learning is a subset of AI.",
                "input_type": "passage"
            }
        )
        
        assert response.status_code == 200

@pytest.mark.asyncio
async def test_embeddings_normalized():
    """Test embeddings are unit normalized."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": "Test normalization"
            }
        )
        
        data = response.json()
        embedding = data["data"][0]["embedding"]
        
        # Calculate L2 norm
        norm = np.linalg.norm(embedding)
        assert abs(norm - 1.0) < 0.001

@pytest.mark.asyncio
async def test_health_endpoint():
    """Test health check."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{EMBEDDING_URL}/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["model_loaded"] == True
        assert data["embedding_dim"] == 1024

@pytest.mark.asyncio
async def test_metrics_endpoint():
    """Test Prometheus metrics."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{EMBEDDING_URL}/metrics")
        
        assert response.status_code == 200
        assert "embedding_requests_total" in response.text
        assert "embedding_request_latency_seconds" in response.text

@pytest.mark.asyncio
async def test_empty_input_rejected():
    """Test empty input validation."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": ""
            }
        )
        
        assert response.status_code == 422

@pytest.mark.asyncio
async def test_empty_list_rejected():
    """Test empty list validation."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/v1/embeddings",
            json={
                "model": "BAAI/bge-large-en-v1.5",
                "input": []
            }
        )
        
        assert response.status_code == 422

@pytest.mark.asyncio
async def test_batch_endpoint():
    """Test direct batch endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EMBEDDING_URL}/embed",
            json={
                "texts": ["Hello", "World"],
                "input_type": "passage"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["embeddings"]) == 2
        assert data["dimensions"] == 1024

def test_dynamic_batcher_batching():
    """Test dynamic batcher collects requests."""
    import asyncio
    
    async def mock_embed(texts, input_type):
        return BatchEmbeddingResult(
            embeddings=[[0.1] * 1024] * len(texts),
            dimensions=1024,
            total_tokens=len(texts) * 5,
            processing_time_ms=10.0
        )
    
    async def run_test():
        batcher = DynamicBatcher(
            embed_fn=mock_embed,
            max_batch_size=4,
            batch_timeout_ms=100
        )
        await batcher.start()
        
        # Submit multiple requests concurrently
        results = await asyncio.gather(
            batcher.submit(["text1"]),
            batcher.submit(["text2"]),
            batcher.submit(["text3"])
        )
        
        assert len(results) == 3
        
        await batcher.stop()
    
    asyncio.run(run_test())

def test_embedding_service_config_defaults():
    """Test configuration defaults."""
    config = EmbeddingServiceConfig()
    
    assert config.model_name == "BAAI/bge-large-en-v1.5"
    assert config.embedding_dim == 1024
    assert config.max_batch_size == 32
    assert config.normalize_embeddings == True
```

## Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_service_end_to_end():
    """End-to-end test with real service."""
    async with httpx.AsyncClient(base_url=EMBEDDING_URL) as client:
        # Health check
        health = await client.get("/health")
        assert health.status_code == 200
        
        # Single embedding
        single = await client.post("/v1/embeddings", json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": "What is artificial intelligence?"
        })
        assert single.status_code == 200
        assert len(single.json()["data"][0]["embedding"]) == 1024
        
        # Batch embedding
        batch = await client.post("/v1/embeddings", json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": [
                "Machine learning overview",
                "Deep learning fundamentals",
                "Neural network architecture"
            ]
        })
        assert batch.status_code == 200
        assert len(batch.json()["data"]) == 3

@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_similarity():
    """Test that similar texts have similar embeddings."""
    async with httpx.AsyncClient(base_url=EMBEDDING_URL) as client:
        # Get embeddings for similar texts
        response = await client.post("/v1/embeddings", json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": [
                "The cat sat on the mat",
                "A cat was sitting on a mat",
                "The stock market crashed today"
            ]
        })
        
        data = response.json()
        emb1 = np.array(data["data"][0]["embedding"])
        emb2 = np.array(data["data"][1]["embedding"])
        emb3 = np.array(data["data"][2]["embedding"])
        
        # Similar sentences should have higher similarity
        sim_12 = np.dot(emb1, emb2)
        sim_13 = np.dot(emb1, emb3)
        
        assert sim_12 > sim_13  # Cat sentences more similar than cat vs market

@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_requests():
    """Test handling of concurrent requests."""
    import asyncio
    
    async def make_request(client, i):
        response = await client.post("/v1/embeddings", json={
            "model": "BAAI/bge-large-en-v1.5",
            "input": f"Test text number {i}"
        })
        return response.status_code
    
    async with httpx.AsyncClient(base_url=EMBEDDING_URL, timeout=30.0) as client:
        tasks = [make_request(client, i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        
        assert all(status == 200 for status in results)
```

## Dependencies

```txt
# requirements.txt
fastapi>=0.104.0
uvicorn>=0.24.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
sentence-transformers>=2.3.0
torch>=2.1.0
transformers>=4.37.0
numpy>=1.24.0
httpx>=0.25.0
prometheus-client>=0.19.0
```

## Performance Targets

| Metric | Target |
|--------|--------|
| Single embedding latency | <50ms |
| Batch (32) latency | <200ms |
| Throughput | >500 embeddings/sec |
| Queue wait time (p95) | <100ms |
| GPU memory | <4GB |

## Definition of Done

- [ ] Embedding service deployed on GPU node
- [ ] BGE-large-en-v1.5 model loaded
- [ ] `/v1/embeddings` OpenAI-compatible endpoint working
- [ ] `/embed` batch endpoint working
- [ ] Embeddings are 1024-dimensional
- [ ] Dynamic batching operational
- [ ] GPU acceleration working
- [ ] FP16 inference enabled
- [ ] Embeddings properly normalized
- [ ] Query/passage prefixes working
- [ ] Health check endpoint functional
- [ ] Prometheus metrics exposed
- [ ] Latency within targets
- [ ] HPA configured for scaling
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
