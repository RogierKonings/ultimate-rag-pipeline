# US-5.3: Reranker Model Service

> **Story ID:** US-5.3  
> **Epic:** LLM Serving Layer  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** Epic 1 (Infrastructure - GPU nodes)

## User Story

**As a** developer  
**I want** reranker model served  
**So that** retrieval results can be reranked for improved relevance

## Context

The Reranker Model Service provides cross-encoder based relevance scoring for query-document pairs. It serves the BAAI/bge-reranker-v2-m3 model, which performs pairwise scoring to rerank initial retrieval results. Unlike embedding models that encode independently, cross-encoders process query and document together for more accurate relevance assessment.

Key features:
- Cross-encoder pairwise scoring
- Batch inference for multiple document pairs
- GPU acceleration for low latency
- Top-K selection with score thresholds
- Prometheus metrics for monitoring

## Technical Requirements

### Directory Structure

```
llm-serving/
└── reranker-service/
    ├── Dockerfile
    ├── api/
    │   ├── __init__.py
    │   ├── main.py              # FastAPI application
    │   ├── routes.py            # API routes
    │   ├── models.py            # Pydantic models
    │   └── dependencies.py      # Dependency injection
    ├── core/
    │   ├── __init__.py
    │   ├── reranker.py          # Reranking logic
    │   ├── batching.py          # Batch processing
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
from typing import Optional, Literal
from enum import Enum
from uuid import UUID, uuid4

class RerankerModel(str, Enum):
    BGE_RERANKER_V2_M3 = "BAAI/bge-reranker-v2-m3"
    BGE_RERANKER_LARGE = "BAAI/bge-reranker-large"
    BGE_RERANKER_BASE = "BAAI/bge-reranker-base"

class RerankerServiceConfig(BaseModel):
    """Configuration for the reranker service."""
    
    # Model settings
    model_name: str = "BAAI/bge-reranker-v2-m3"
    model_revision: Optional[str] = None
    max_sequence_length: int = 512
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8002
    
    # Batching settings
    max_batch_size: int = 32
    batch_timeout_ms: float = 50.0
    
    # GPU settings
    device: str = "cuda"
    use_fp16: bool = True
    
    # Scoring settings
    normalize_scores: bool = False  # Return raw logits or sigmoid
    
    # Queue settings
    max_queue_size: int = 1000
    worker_count: int = 1

class DocumentPair(BaseModel):
    """A query-document pair for reranking."""
    query: str
    document: str
    doc_id: Optional[str] = None
    metadata: Optional[dict] = None

class RerankRequest(BaseModel):
    """
    Request to rerank documents for a query.
    
    Supports either:
    - Single query with list of documents
    - List of pre-formed query-document pairs
    """
    model: str = "BAAI/bge-reranker-v2-m3"
    
    # Option 1: Query + documents
    query: Optional[str] = None
    documents: Optional[list[str]] = None
    
    # Option 2: Pre-formed pairs
    pairs: Optional[list[DocumentPair]] = None
    
    # Reranking options
    top_k: Optional[int] = None  # Return only top K results
    min_score: Optional[float] = None  # Minimum score threshold
    return_documents: bool = True  # Include documents in response
    
    # Request metadata
    request_id: UUID = Field(default_factory=uuid4)
    
    @field_validator("documents", "pairs")
    @classmethod
    def validate_input(cls, v, info):
        # Ensure at least one input method is provided
        return v

class ScoredDocument(BaseModel):
    """A document with its relevance score."""
    index: int
    score: float
    document: Optional[str] = None
    doc_id: Optional[str] = None
    metadata: Optional[dict] = None

class RerankResponse(BaseModel):
    """Response from reranking request."""
    model: str
    results: list[ScoredDocument]
    usage: dict  # Token counts
    processing_time_ms: float

class BatchRerankRequest(BaseModel):
    """Batch reranking for internal use."""
    queries: list[str]
    documents: list[str]
    doc_ids: Optional[list[str]] = None

class BatchRerankResult(BaseModel):
    """Batch reranking result."""
    scores: list[float]
    processing_time_ms: float

class HealthResponse(BaseModel):
    """Health check response."""
    status: Literal["healthy", "unhealthy", "degraded"]
    model_loaded: bool
    model_name: str
    device: str
    gpu_available: bool
    gpu_memory_used_mb: Optional[float] = None
    queue_size: int
    uptime_seconds: float
```

### Reranker Service Core

```python
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from typing import Optional
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
import logging
import numpy as np

logger = logging.getLogger(__name__)

class RerankerService:
    """
    Core reranking service using cross-encoder models.
    
    Cross-encoders process query and document together through
    a transformer, producing a relevance score. More accurate
    than bi-encoder (embedding) similarity but slower.
    """
    
    def __init__(self, config: RerankerServiceConfig):
        self.config = config
        self._model = None
        self._tokenizer = None
        self._device = None
        self._executor = ThreadPoolExecutor(max_workers=config.worker_count)
        self._startup_time = time.time()
    
    async def load_model(self):
        """Load the reranker model and tokenizer."""
        logger.info(f"Loading reranker model: {self.config.model_name}")
        
        def _load():
            tokenizer = AutoTokenizer.from_pretrained(
                self.config.model_name,
                revision=self.config.model_revision
            )
            
            model = AutoModelForSequenceClassification.from_pretrained(
                self.config.model_name,
                revision=self.config.model_revision
            )
            
            # Move to device
            device = torch.device(self.config.device if torch.cuda.is_available() else "cpu")
            model = model.to(device)
            model.eval()
            
            # Enable FP16 if configured
            if self.config.use_fp16 and device.type == "cuda":
                model = model.half()
            
            return tokenizer, model, device
        
        loop = asyncio.get_event_loop()
        self._tokenizer, self._model, self._device = await loop.run_in_executor(
            self._executor, _load
        )
        
        logger.info(f"Reranker model loaded on {self._device}")
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        doc_ids: Optional[list[str]] = None,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        return_documents: bool = True
    ) -> RerankResponse:
        """
        Rerank documents for a query.
        
        Args:
            query: The search query
            documents: List of documents to rerank
            doc_ids: Optional document IDs
            top_k: Return only top K results
            min_score: Minimum score threshold
            return_documents: Include document text in response
        
        Returns:
            RerankResponse with scored and sorted documents
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        start_time = time.time()
        
        # Score all pairs
        scores = await self._score_pairs(query, documents)
        
        # Build results with indices
        results = []
        for i, (score, doc) in enumerate(zip(scores, documents)):
            doc_id = doc_ids[i] if doc_ids else None
            
            results.append(ScoredDocument(
                index=i,
                score=float(score),
                document=doc if return_documents else None,
                doc_id=doc_id
            ))
        
        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        
        # Apply min_score filter
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]
        
        # Apply top_k limit
        if top_k is not None:
            results = results[:top_k]
        
        processing_time = (time.time() - start_time) * 1000
        
        # Estimate token usage
        total_tokens = sum(len(query.split()) + len(d.split()) for d in documents)
        
        return RerankResponse(
            model=self.config.model_name,
            results=results,
            usage={
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens
            },
            processing_time_ms=processing_time
        )
    
    async def rerank_pairs(
        self,
        pairs: list[DocumentPair],
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        return_documents: bool = True
    ) -> RerankResponse:
        """
        Rerank pre-formed query-document pairs.
        
        Useful when each document has a different query
        or for multi-query scenarios.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        start_time = time.time()
        
        # Extract queries and documents
        queries = [p.query for p in pairs]
        documents = [p.document for p in pairs]
        
        # Score all pairs
        scores = await self._score_pairs_batch(queries, documents)
        
        # Build results
        results = []
        for i, (pair, score) in enumerate(zip(pairs, scores)):
            results.append(ScoredDocument(
                index=i,
                score=float(score),
                document=pair.document if return_documents else None,
                doc_id=pair.doc_id,
                metadata=pair.metadata
            ))
        
        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        
        # Apply filters
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]
        
        if top_k is not None:
            results = results[:top_k]
        
        processing_time = (time.time() - start_time) * 1000
        
        return RerankResponse(
            model=self.config.model_name,
            results=results,
            usage={
                "prompt_tokens": sum(len(q.split()) + len(d.split()) for q, d in zip(queries, documents)),
                "total_tokens": sum(len(q.split()) + len(d.split()) for q, d in zip(queries, documents))
            },
            processing_time_ms=processing_time
        )
    
    async def _score_pairs(
        self,
        query: str,
        documents: list[str]
    ) -> list[float]:
        """Score a single query against multiple documents."""
        queries = [query] * len(documents)
        return await self._score_pairs_batch(queries, documents)
    
    async def _score_pairs_batch(
        self,
        queries: list[str],
        documents: list[str]
    ) -> list[float]:
        """Score multiple query-document pairs."""
        
        def _score():
            # Tokenize pairs
            inputs = self._tokenizer(
                queries,
                documents,
                padding=True,
                truncation=True,
                max_length=self.config.max_sequence_length,
                return_tensors="pt"
            )
            
            # Move to device
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            
            # Run inference
            with torch.no_grad():
                outputs = self._model(**inputs)
                
                # Get logits (relevance scores)
                logits = outputs.logits
                
                if self.config.normalize_scores:
                    # Apply sigmoid to normalize to [0, 1]
                    scores = torch.sigmoid(logits).squeeze(-1)
                else:
                    # Return raw logits
                    scores = logits.squeeze(-1)
                
                return scores.cpu().numpy().tolist()
        
        loop = asyncio.get_event_loop()
        
        # Process in batches if needed
        all_scores = []
        batch_size = self.config.max_batch_size
        
        for i in range(0, len(queries), batch_size):
            batch_queries = queries[i:i + batch_size]
            batch_docs = documents[i:i + batch_size]
            
            # Temporarily override for this batch
            temp_queries, temp_docs = queries, documents
            queries, documents = batch_queries, batch_docs
            
            scores = await loop.run_in_executor(self._executor, _score)
            all_scores.extend(scores if isinstance(scores, list) else [scores])
            
            queries, documents = temp_queries, temp_docs
        
        return all_scores
    
    def get_health(self) -> HealthResponse:
        """Get service health status."""
        gpu_available = torch.cuda.is_available()
        gpu_memory = None
        
        if gpu_available and self._device and self._device.type == "cuda":
            gpu_memory = torch.cuda.memory_allocated() / 1024 / 1024
        
        return HealthResponse(
            status="healthy" if self._model is not None else "unhealthy",
            model_loaded=self._model is not None,
            model_name=self.config.model_name,
            device=str(self._device) if self._device else "unknown",
            gpu_available=gpu_available,
            gpu_memory_used_mb=gpu_memory,
            queue_size=0,
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
class PendingRerankRequest:
    """A pending rerank request in the queue."""
    request_id: UUID
    queries: list[str]
    documents: list[str]
    future: asyncio.Future
    timestamp: float

class RerankBatcher:
    """
    Dynamic batching for reranking requests.
    
    Collects incoming pairs and batches them for
    efficient GPU utilization.
    """
    
    def __init__(
        self,
        score_fn: Callable[[list[str], list[str]], Awaitable[list[float]]],
        max_batch_size: int = 32,
        batch_timeout_ms: float = 50.0,
        max_queue_size: int = 1000
    ):
        self.score_fn = score_fn
        self.max_batch_size = max_batch_size
        self.batch_timeout = batch_timeout_ms / 1000.0
        self.max_queue_size = max_queue_size
        
        self._queue: asyncio.Queue[PendingRerankRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Metrics
        self._requests_processed = 0
        self._batches_processed = 0
        self._total_pairs_processed = 0
    
    async def start(self):
        """Start the batching processor."""
        self._running = True
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info("Rerank batcher started")
    
    async def stop(self):
        """Stop the batching processor."""
        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
    
    async def submit(
        self,
        queries: list[str],
        documents: list[str]
    ) -> list[float]:
        """
        Submit pairs for scoring.
        
        Args:
            queries: List of queries
            documents: List of documents (same length as queries)
        
        Returns:
            List of scores
        """
        future = asyncio.get_event_loop().create_future()
        
        request = PendingRerankRequest(
            request_id=uuid4(),
            queries=queries,
            documents=documents,
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
                logger.error(f"Error in rerank processing loop: {e}")
    
    async def _collect_batch(self) -> list[PendingRerankRequest]:
        """Collect requests into a batch."""
        batch: list[PendingRerankRequest] = []
        total_pairs = 0
        
        deadline = time.time() + self.batch_timeout
        
        while True:
            try:
                timeout = max(0, deadline - time.time())
                request = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=timeout if batch else None
                )
                
                request_pairs = len(request.queries)
                
                # Check batch size limit
                if batch and total_pairs + request_pairs > self.max_batch_size:
                    await self._queue.put(request)
                    break
                
                batch.append(request)
                total_pairs += request_pairs
                
                if total_pairs >= self.max_batch_size:
                    break
                    
            except asyncio.TimeoutError:
                break
        
        return batch
    
    async def _process_batch(self, batch: list[PendingRerankRequest]):
        """Process a collected batch."""
        if not batch:
            return
        
        # Combine all pairs
        all_queries = []
        all_documents = []
        pair_counts = []
        
        for request in batch:
            all_queries.extend(request.queries)
            all_documents.extend(request.documents)
            pair_counts.append(len(request.queries))
        
        try:
            # Score all pairs
            scores = await self.score_fn(all_queries, all_documents)
            
            # Distribute results
            offset = 0
            for request, count in zip(batch, pair_counts):
                request_scores = scores[offset:offset + count]
                request.future.set_result(request_scores)
                offset += count
                
                self._requests_processed += 1
            
            self._batches_processed += 1
            self._total_pairs_processed += len(scores)
            
        except Exception as e:
            for request in batch:
                if not request.future.done():
                    request.future.set_exception(e)
    
    def get_metrics(self) -> dict:
        """Get batcher metrics."""
        return {
            "queue_size": self._queue.qsize(),
            "requests_processed": self._requests_processed,
            "batches_processed": self._batches_processed,
            "total_pairs_processed": self._total_pairs_processed
        }
```

### FastAPI Application

```python
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response
import time
import logging

logger = logging.getLogger(__name__)

# Prometheus metrics
REQUESTS_TOTAL = Counter(
    "rerank_requests_total",
    "Total rerank requests",
    ["status", "model"]
)
REQUEST_LATENCY = Histogram(
    "rerank_request_latency_seconds",
    "Rerank request latency",
    ["model"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)
PAIRS_PER_REQUEST = Histogram(
    "rerank_pairs_per_request",
    "Number of pairs per rerank request",
    buckets=[1, 5, 10, 20, 50, 100]
)
QUEUE_SIZE = Gauge(
    "rerank_queue_size",
    "Current queue size"
)

# Global instances
reranker_service: Optional[RerankerService] = None
batcher: Optional[RerankBatcher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global reranker_service, batcher
    
    config = RerankerServiceConfig()
    
    reranker_service = RerankerService(config)
    await reranker_service.load_model()
    
    batcher = RerankBatcher(
        score_fn=reranker_service._score_pairs_batch,
        max_batch_size=config.max_batch_size,
        batch_timeout_ms=config.batch_timeout_ms,
        max_queue_size=config.max_queue_size
    )
    await batcher.start()
    
    logger.info("Reranker service ready")
    
    yield
    
    await batcher.stop()
    await reranker_service.close()
    logger.info("Reranker service shutdown complete")

app = FastAPI(
    title="Reranker Service",
    description="Cross-encoder based document reranking",
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

@app.post("/rerank", response_model=RerankResponse)
async def rerank_documents(request: RerankRequest):
    """
    Rerank documents for a query.
    
    Accepts either:
    - query + documents: Scores query against each document
    - pairs: Scores each query-document pair
    """
    start_time = time.time()
    
    try:
        if request.pairs:
            # Use pre-formed pairs
            PAIRS_PER_REQUEST.observe(len(request.pairs))
            
            response = await reranker_service.rerank_pairs(
                pairs=request.pairs,
                top_k=request.top_k,
                min_score=request.min_score,
                return_documents=request.return_documents
            )
        elif request.query and request.documents:
            # Use query + documents
            PAIRS_PER_REQUEST.observe(len(request.documents))
            
            response = await reranker_service.rerank(
                query=request.query,
                documents=request.documents,
                top_k=request.top_k,
                min_score=request.min_score,
                return_documents=request.return_documents
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either (query + documents) or pairs"
            )
        
        latency = time.time() - start_time
        REQUEST_LATENCY.labels(model=request.model).observe(latency)
        REQUESTS_TOTAL.labels(status="success", model=request.model).inc()
        
        return response
        
    except Exception as e:
        REQUESTS_TOTAL.labels(status="error", model=request.model).inc()
        logger.error(f"Rerank error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/rerank", response_model=RerankResponse)
async def rerank_v1(request: RerankRequest):
    """Versioned rerank endpoint (alias)."""
    return await rerank_documents(request)

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    health = reranker_service.get_health()
    
    if batcher:
        metrics = batcher.get_metrics()
        health.queue_size = metrics["queue_size"]
        QUEUE_SIZE.set(metrics["queue_size"])
    
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
    """List available reranker models."""
    return {
        "object": "list",
        "data": [
            {
                "id": reranker_service.config.model_name,
                "object": "model",
                "owned_by": "bge",
                "type": "reranker"
            }
        ]
    }
```

### Dockerfile

```dockerfile
# Reranker Service Dockerfile
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN useradd -m -u 1000 reranker
USER reranker
WORKDIR /app

COPY --chown=reranker:reranker . /app/

# Optional: preload model
ARG PRELOAD_MODEL=false
RUN if [ "$PRELOAD_MODEL" = "true" ]; then \
    python3 -c "from transformers import AutoModelForSequenceClassification, AutoTokenizer; \
    AutoTokenizer.from_pretrained('BAAI/bge-reranker-v2-m3'); \
    AutoModelForSequenceClassification.from_pretrained('BAAI/bge-reranker-v2-m3')"; \
    fi

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

EXPOSE 8002

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8002"]
```

### Kubernetes Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reranker-service
  namespace: llm-serving
  labels:
    app: reranker-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: reranker-service
  template:
    metadata:
      labels:
        app: reranker-service
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8002"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: reranker
          image: llm-serving/reranker-service:latest
          ports:
            - containerPort: 8002
          
          env:
            - name: MODEL_NAME
              value: "BAAI/bge-reranker-v2-m3"
            - name: MAX_BATCH_SIZE
              value: "32"
            - name: BATCH_TIMEOUT_MS
              value: "50"
            - name: USE_FP16
              value: "true"
            - name: MAX_SEQUENCE_LENGTH
              value: "512"
          
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
              port: 8002
            initialDelaySeconds: 60
            periodSeconds: 30
          
          readinessProbe:
            httpGet:
              path: /health
              port: 8002
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
  name: reranker-service
  namespace: llm-serving
spec:
  selector:
    app: reranker-service
  ports:
    - port: 8002
      targetPort: 8002
  type: ClusterIP
---
# k8s/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: reranker-service-hpa
  namespace: llm-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: reranker-service
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Pods
      pods:
        metric:
          name: rerank_queue_size
        target:
          type: AverageValue
          averageValue: "50"
```

## Acceptance Criteria

- [ ] BGE-reranker-v2-m3 model deployed and loaded
- [ ] `/rerank` endpoint working with query + documents
- [ ] `/rerank` endpoint working with pairs
- [ ] Batch scoring support (up to 32 pairs)
- [ ] Results sorted by score descending
- [ ] top_k filtering works correctly
- [ ] min_score threshold filtering works
- [ ] Cross-encoder inference optimized (FP16)
- [ ] Latency < 100ms for 20 pairs
- [ ] GPU acceleration working
- [ ] Health check endpoint functional
- [ ] Prometheus metrics exposed
- [ ] Return original document indices

## Testing Requirements

```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np

RERANKER_URL = "http://localhost:8002"

@pytest.fixture
def mock_reranker():
    """Mock reranker service."""
    reranker = AsyncMock()
    reranker.rerank.return_value = RerankResponse(
        model="BAAI/bge-reranker-v2-m3",
        results=[
            ScoredDocument(index=0, score=0.9, document="doc1"),
            ScoredDocument(index=1, score=0.7, document="doc2")
        ],
        usage={"prompt_tokens": 100, "total_tokens": 100},
        processing_time_ms=50.0
    )
    return reranker

@pytest.mark.asyncio
async def test_rerank_query_documents():
    """Test reranking with query + documents."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": "What is machine learning?",
                "documents": [
                    "Machine learning is a subset of AI.",
                    "The weather is nice today.",
                    "Deep learning uses neural networks."
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 3
        
        # Results should be sorted by score
        scores = [r["score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)

@pytest.mark.asyncio
async def test_rerank_pairs():
    """Test reranking with pre-formed pairs."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "pairs": [
                    {"query": "What is AI?", "document": "AI is artificial intelligence."},
                    {"query": "What is ML?", "document": "ML is machine learning."}
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2

@pytest.mark.asyncio
async def test_top_k_filter():
    """Test top_k filtering."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": "test query",
                "documents": ["doc1", "doc2", "doc3", "doc4", "doc5"],
                "top_k": 3
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 3

@pytest.mark.asyncio
async def test_min_score_filter():
    """Test min_score filtering."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": "What is programming?",
                "documents": [
                    "Programming is writing code.",
                    "Cats are cute animals."
                ],
                "min_score": 0.5
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        # All returned results should have score >= 0.5
        for result in data["results"]:
            assert result["score"] >= 0.5

@pytest.mark.asyncio
async def test_return_documents_false():
    """Test omitting documents from response."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": "test",
                "documents": ["doc1", "doc2"],
                "return_documents": False
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result.get("document") is None

@pytest.mark.asyncio
async def test_preserves_original_index():
    """Test that original indices are preserved."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": "test",
                "documents": ["doc0", "doc1", "doc2"]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check indices are from 0, 1, 2 (original positions)
        indices = {r["index"] for r in data["results"]}
        assert indices == {0, 1, 2}

@pytest.mark.asyncio
async def test_health_endpoint():
    """Test health check."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{RERANKER_URL}/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["model_loaded"] == True

@pytest.mark.asyncio
async def test_metrics_endpoint():
    """Test Prometheus metrics."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{RERANKER_URL}/metrics")
        
        assert response.status_code == 200
        assert "rerank_requests_total" in response.text

@pytest.mark.asyncio
async def test_missing_input_error():
    """Test error when neither query+docs nor pairs provided."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={"model": "BAAI/bge-reranker-v2-m3"}
        )
        
        assert response.status_code == 400

@pytest.mark.asyncio
async def test_empty_documents_error():
    """Test error with empty documents list."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": "test",
                "documents": []
            }
        )
        
        # Should handle gracefully
        assert response.status_code in [200, 400]

def test_reranker_config_defaults():
    """Test configuration defaults."""
    config = RerankerServiceConfig()
    
    assert config.model_name == "BAAI/bge-reranker-v2-m3"
    assert config.max_batch_size == 32
    assert config.max_sequence_length == 512

def test_scored_document_model():
    """Test ScoredDocument model."""
    doc = ScoredDocument(
        index=0,
        score=0.95,
        document="Test document",
        doc_id="doc-123"
    )
    
    assert doc.index == 0
    assert doc.score == 0.95
    assert doc.document == "Test document"
    assert doc.doc_id == "doc-123"
```

## Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_end_to_end():
    """End-to-end test with real service."""
    async with httpx.AsyncClient(base_url=RERANKER_URL) as client:
        # Health check
        health = await client.get("/health")
        assert health.status_code == 200
        
        # Rerank documents
        response = await client.post("/rerank", json={
            "query": "How do neural networks work?",
            "documents": [
                "Neural networks are inspired by biological neurons.",
                "The stock market saw gains today.",
                "Deep learning models use multiple layers of neurons."
            ]
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Neural network docs should rank higher than stock market
        results = data["results"]
        stock_market_idx = next(
            r["index"] for r in results 
            if "stock" in results[results.index(r)].get("document", "").lower()
        )
        
        # Stock market doc should be last (lowest score)
        assert results[-1]["index"] == 1  # Index of stock market doc

@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_latency():
    """Test that reranking meets latency requirements."""
    import time
    
    async with httpx.AsyncClient(base_url=RERANKER_URL) as client:
        documents = [f"Document number {i} with some content" for i in range(20)]
        
        start = time.time()
        response = await client.post("/rerank", json={
            "query": "Find relevant documents",
            "documents": documents
        })
        latency_ms = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert latency_ms < 100  # Should be under 100ms for 20 docs

@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_relevance():
    """Test that reranker produces meaningful rankings."""
    async with httpx.AsyncClient(base_url=RERANKER_URL) as client:
        response = await client.post("/rerank", json={
            "query": "Python programming language",
            "documents": [
                "Python is a high-level programming language known for its simplicity.",
                "Java is a popular programming language used in enterprise applications.",
                "The python snake is found in tropical regions of Asia and Africa."
            ]
        })
        
        data = response.json()
        
        # Python programming doc should be ranked first
        assert data["results"][0]["index"] == 0
        
        # Python snake doc should likely be last (different context)
        assert data["results"][-1]["index"] == 2

@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_rerank_requests():
    """Test handling concurrent requests."""
    import asyncio
    
    async def make_request(client, i):
        response = await client.post("/rerank", json={
            "query": f"Query number {i}",
            "documents": [f"Document {j} for query {i}" for j in range(5)]
        })
        return response.status_code
    
    async with httpx.AsyncClient(base_url=RERANKER_URL, timeout=30.0) as client:
        tasks = [make_request(client, i) for i in range(10)]
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
torch>=2.1.0
transformers>=4.37.0
numpy>=1.24.0
httpx>=0.25.0
prometheus-client>=0.19.0
```

## Performance Targets

| Metric | Target |
|--------|--------|
| Latency (1 pair) | <20ms |
| Latency (20 pairs) | <100ms |
| Latency (32 pairs) | <150ms |
| Throughput | >300 pairs/sec |
| GPU memory | <4GB |

## Definition of Done

- [ ] Reranker service deployed on GPU node
- [ ] BGE-reranker-v2-m3 model loaded
- [ ] `/rerank` endpoint working (query + documents)
- [ ] `/rerank` endpoint working (pairs)
- [ ] Cross-encoder scoring functional
- [ ] Results sorted by score descending
- [ ] Original indices preserved
- [ ] top_k filtering working
- [ ] min_score threshold working
- [ ] FP16 inference enabled
- [ ] Latency < 100ms for 20 pairs
- [ ] Health check endpoint functional
- [ ] Prometheus metrics exposed
- [ ] Dynamic batching operational
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
