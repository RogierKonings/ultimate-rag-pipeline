# Epic 5: LLM Serving Layer - Implementation Plan

> **Epic:** LLM Serving Layer
> **Total Estimated Effort:** 2 weeks
> **Dependencies:** Epic 1 (Infrastructure - GPU nodes)

## Executive Summary

This implementation plan details the deployment of a production-grade LLM Serving Layer comprising vLLM for chat completions, BGE embedding service, BGE reranker service, and a unified OpenAI-compatible gateway. The plan is structured in 4 waves with clear checkpoints and integration tests.

---

## Implementation Waves

### Wave 1: Core Model Services (Parallel)

**Duration:** 3-4 days
**User Stories:** US-5.1, US-5.2, US-5.3 (can be implemented in parallel)

#### Agent 1: vLLM Deployment (US-5.1)

**Goal:** Deploy vLLM serving Llama-3.1-8B-Instruct with OpenAI-compatible API

**Tasks:**
1. Create namespace and RBAC
   - Create `llm-serving` namespace
   - Create ServiceAccount `vllm-sa`
   - Set up RBAC for HuggingFace model downloads

2. Build vLLM container
   - Write Dockerfile based on `nvidia/cuda:12.1.1-runtime-ubuntu22.04`
   - Install vLLM >= 0.4.0, ray, transformers
   - Add healthcheck script
   - Build and push to registry

3. Create Kubernetes manifests
   - ConfigMap with model settings (max_model_len=8192, gpu_memory_utilization=0.90)
   - Secret for HuggingFace token
   - PersistentVolumeClaim for model cache (50Gi)
   - Deployment with init container for model download
   - Service (ClusterIP)
   - GPU tolerations and node selectors

4. Write utility scripts
   - `healthcheck.py` - Kubernetes probe script
   - `warmup.py` - KV cache warmup
   - `benchmark.py` - Performance testing

5. Deploy and validate
   - Apply manifests
   - Verify model loads successfully
   - Test `/v1/chat/completions` endpoint
   - Test `/v1/completions` endpoint
   - Test streaming responses
   - Verify Prometheus metrics at `/metrics`

**Exit Criteria:**
- [ ] vLLM pod running with model loaded
- [ ] `/v1/chat/completions` returns valid responses
- [ ] Streaming works correctly
- [ ] `/health` returns 200
- [ ] `/metrics` exposes Prometheus metrics
- [ ] GPU memory utilization at ~90%

---

#### Agent 2: Embedding Service (US-5.2)

**Goal:** Deploy embedding service with BGE-large-en-v1.5 (1024 dimensions)

**Tasks:**
1. Create project structure
   ```
   embedding-service/
   ├── api/
   │   ├── main.py
   │   ├── routes.py
   │   └── models.py
   ├── core/
   │   ├── embedder.py
   │   └── batching.py
   ├── config.py
   ├── requirements.txt
   └── Dockerfile
   ```

2. Implement core embedding service
   - `EmbeddingService` class with sentence-transformers
   - GPU acceleration with FP16
   - Normalization to unit vectors
   - BGE query/passage prefix support ("query: ", "passage: ")

3. Implement dynamic batching
   - `DynamicBatcher` class
   - Max batch size: 32
   - Batch timeout: 50ms
   - Request queue with max size 1000

4. Create FastAPI application
   - `/v1/embeddings` - OpenAI-compatible endpoint
   - `/embed` - Direct batch endpoint
   - `/health` - Health check
   - `/metrics` - Prometheus metrics
   - Lifespan handler for model loading

5. Build container and deploy
   - Dockerfile with cuda base image
   - Kubernetes Deployment (4Gi RAM, 1 GPU)
   - Service on port 8001
   - HPA based on queue size

**Exit Criteria:**
- [ ] BGE-large model loaded
- [ ] `/v1/embeddings` returns 1024-dim vectors
- [ ] Embeddings are L2-normalized (norm ≈ 1.0)
- [ ] Single embedding < 50ms
- [ ] Batch of 32 < 200ms
- [ ] Query/passage prefixes working

---

#### Agent 3: Reranker Service (US-5.3)

**Goal:** Deploy reranker service with BGE-reranker-v2-m3

**Tasks:**
1. Create project structure
   ```
   reranker-service/
   ├── api/
   │   ├── main.py
   │   ├── routes.py
   │   └── models.py
   ├── core/
   │   ├── reranker.py
   │   └── batching.py
   ├── config.py
   ├── requirements.txt
   └── Dockerfile
   ```

2. Implement core reranker service
   - `RerankerService` class with AutoModelForSequenceClassification
   - Cross-encoder pairwise scoring
   - GPU acceleration with FP16
   - Batch inference support

3. Implement request handling
   - Support query + documents format
   - Support pre-formed pairs format
   - top_k filtering
   - min_score threshold
   - Result sorting by score descending
   - Preserve original indices

4. Create FastAPI application
   - `/rerank` - Main reranking endpoint
   - `/v1/rerank` - Versioned alias
   - `/health` - Health check
   - `/metrics` - Prometheus metrics

5. Build container and deploy
   - Dockerfile with cuda base image
   - Kubernetes Deployment (4Gi RAM, 1 GPU)
   - Service on port 8002
   - HPA based on queue size

**Exit Criteria:**
- [ ] BGE-reranker-v2-m3 model loaded
- [ ] `/rerank` with query + documents works
- [ ] `/rerank` with pairs works
- [ ] Results sorted by score descending
- [ ] Original indices preserved
- [ ] Latency < 100ms for 20 pairs

---

### Wave 1 Checkpoint

**Integration Test:** `tests/integration/test_wave1_model_services.py`

```python
# Verify all three services are operational
# Test vLLM chat completion
# Test embedding generation
# Test document reranking
# Verify Prometheus metrics from all services
```

---

### Wave 2: Configuration & Resource Management

**Duration:** 2-3 days
**User Stories:** US-5.4, US-5.5 (can be done in parallel)
**Dependencies:** Wave 1 completed

#### Agent 4: Model Configuration (US-5.4)

**Goal:** Implement centralized configuration management with A/B testing support

**Tasks:**
1. Create configuration module
   ```
   config/
   ├── manager.py        # ConfigurationManager
   ├── models.py         # Data models
   ├── router.py         # A/B routing
   ├── watcher.py        # ConfigMap watcher
   └── api/
       └── routes.py     # Configuration API
   ```

2. Implement configuration manager
   - Load from YAML files
   - Version tracking with rollback
   - Change notification callbacks
   - ConfigMap file watcher

3. Implement data models
   - `LLMGenerationConfig` (temperature, top_p, max_tokens, penalties)
   - `EmbeddingConfig` (normalize, batch_size, prefixes)
   - `RerankerConfig` (max_pairs, normalize_scores)
   - `ModelEndpoint` (model_id, endpoint_url, configs)
   - `ABTestConfig` (model_a, model_b, traffic_split, strategy)

4. Implement A/B router
   - `SINGLE` - Always use primary
   - `RANDOM` - Random selection with weights
   - `ROUND_ROBIN` - Alternate between models
   - `HEADER_BASED` - Based on request header
   - `USER_BASED` - Consistent hash by user ID

5. Create configuration API
   - `GET /config` - Current state
   - `PATCH /config/endpoints/{name}` - Update endpoint
   - `PATCH /config/endpoints/{name}/generation` - Update LLM params
   - `POST /config/ab-tests` - Create A/B test
   - `POST /config/rollback` - Rollback to version
   - `GET /config/export` - Export as YAML

6. Create default configuration files
   - `defaults/llm.yaml`
   - `defaults/embedding.yaml`
   - `defaults/reranker.yaml`

**Exit Criteria:**
- [ ] YAML configuration loading works
- [ ] Dynamic parameter updates via API
- [ ] A/B test creation and management
- [ ] Multiple routing strategies functional
- [ ] Version tracking with rollback
- [ ] ConfigMap auto-reload working

---

#### Agent 5: Resource Management (US-5.5)

**Goal:** Implement GPU monitoring, batch optimization, cost tracking, and auto-scaling

**Tasks:**
1. Create resource management module
   ```
   resource-management/
   ├── gpu_monitor.py        # nvidia-smi integration
   ├── batch_optimizer.py    # Batch tuning
   ├── cost_tracker.py       # Cost allocation
   └── k8s/
       ├── hpa-vllm.yaml
       ├── hpa-embedding.yaml
       ├── hpa-reranker.yaml
       ├── resource-quotas.yaml
       └── priority-classes.yaml
   ```

2. Implement GPU monitor
   - Parse nvidia-smi XML output
   - Track memory usage, utilization, temperature, power
   - Async polling with configurable interval
   - Callback registration for metrics updates

3. Implement batch optimizer
   - Record batch statistics (size, processing time, wait time)
   - Calculate efficiency score
   - Recommend optimal batch size and timeout
   - Auto-apply recommendations (optional)

4. Implement cost tracker
   - Per-GPU cost rates (A100, A10, T4)
   - Per-model cost allocation
   - Cost per request/token calculation
   - Monthly cost estimation
   - Hourly aggregation

5. Create Kubernetes resources
   - HPA for vLLM (GPU utilization, queue depth)
   - HPA for embedding service (queue size)
   - HPA for reranker service (queue size)
   - ResourceQuota for namespace
   - LimitRange for containers
   - PriorityClasses (critical, standard, batch)

**Exit Criteria:**
- [ ] GPU metrics collected via nvidia-smi
- [ ] Batch optimization recommendations generated
- [ ] Cost tracking per model operational
- [ ] HPA configured for all services
- [ ] Resource quotas enforced
- [ ] Priority classes defined

---

### Wave 2 Checkpoint

**Integration Test:** `tests/integration/test_wave2_config_resources.py`

```python
# Verify configuration API
# Test A/B routing with different strategies
# Test configuration rollback
# Verify HPA triggers on load
# Test cost tracking accumulation
```

---

### Wave 3: Health & Monitoring

**Duration:** 2-3 days
**User Stories:** US-5.6
**Dependencies:** Wave 1 & 2 completed

#### Agent 6: Model Health & Monitoring (US-5.6)

**Goal:** Implement comprehensive health checks, metrics, alerting, and anomaly detection

**Tasks:**
1. Create monitoring module
   ```
   monitoring/
   ├── health.py             # Health checkers
   ├── metrics.py            # Prometheus metrics
   ├── collectors.py         # Custom collectors
   ├── anomaly.py            # Anomaly detection
   ├── prometheus/
   │   ├── rules.yaml        # Alert rules
   │   └── servicemonitor.yaml
   └── grafana/
       └── dashboards/
           ├── llm-overview.json
           ├── embedding-metrics.json
           └── gpu-utilization.json
   ```

2. Implement health checkers
   - Base `HealthChecker` class
   - `VLLMHealthChecker` - Check `/v1/models`, model loaded state
   - `EmbeddingHealthChecker` - Test embedding request
   - `RerankerHealthChecker` - Test rerank request
   - Liveness and readiness endpoints

3. Implement Prometheus metrics
   - `llm_requests_total` (service, endpoint, status)
   - `llm_request_latency_seconds` (service, endpoint) with percentile buckets
   - `llm_tokens_processed_total` (service, type)
   - `llm_queue_size` (service)
   - `llm_gpu_memory_used_bytes` (gpu_id)
   - `llm_gpu_utilization_percent` (gpu_id)
   - `llm_errors_total` (service, error_type)

4. Implement anomaly detection
   - Z-score based detection with sliding window
   - `LatencyAnomalyDetector` - Latency spikes
   - `ThroughputAnomalyDetector` - Throughput drops
   - Configurable thresholds

5. Create alerting rules
   - `LLMHighErrorRate` - >5% error rate for 5m
   - `LLMHighLatency` - p95 > 5s for 5m
   - `LLMVeryHighLatency` - p99 > 10s for 2m
   - `LLMHighQueueDepth` - Queue > 100 for 5m
   - `LLMGPUMemoryHigh` - GPU memory > 95% for 5m
   - `LLMServiceDown` - Service unavailable for 1m

6. Create Grafana dashboards
   - LLM Overview (request rate, latency, errors)
   - Embedding Metrics (throughput, batch sizes)
   - GPU Utilization (memory, compute, temperature)

**Exit Criteria:**
- [ ] `/health/live` and `/health/ready` endpoints working
- [ ] Prometheus metrics exposed at `/metrics`
- [ ] Latency percentiles tracked (p50, p95, p99)
- [ ] GPU metrics collected
- [ ] Alert rules deployed to Prometheus
- [ ] Grafana dashboards created
- [ ] Anomaly detection flagging outliers

---

### Wave 3 Checkpoint

**Integration Test:** `tests/integration/test_wave3_monitoring.py`

```python
# Verify health endpoints
# Test Prometheus metrics scraping
# Verify alert rules syntax
# Test anomaly detection with synthetic spikes
# Validate Grafana dashboard JSON
```

---

### Wave 4: Gateway & Security

**Duration:** 3-4 days
**User Stories:** US-5.7, US-5.8
**Dependencies:** Wave 1, 2, 3 completed

#### Agent 7: Unified OpenAI Gateway (US-5.7)

**Goal:** Create a single gateway exposing OpenAI-compatible endpoints for chat, embeddings, and rerank

**Tasks:**
1. Create gateway service
   ```
   gateway/
   ├── api/
   │   ├── main.py
   │   ├── routes/
   │   │   ├── completions.py
   │   │   ├── embeddings.py
   │   │   └── rerank.py
   │   └── models.py
   ├── clients/
   │   ├── vllm_client.py
   │   ├── embedding_client.py
   │   └── reranker_client.py
   ├── config.py
   └── k8s/
       ├── deployment.yaml
       └── service.yaml
   ```

2. Implement backend clients
   - `VLLMClient` - Proxy to vLLM service
   - `EmbeddingClient` - Proxy to embedding service
   - `RerankerClient` - Proxy to reranker service
   - Connection pooling with httpx
   - Retry logic with exponential backoff

3. Implement gateway routes
   - `POST /v1/chat/completions` - Proxy to vLLM with streaming support
   - `POST /v1/embeddings` - Proxy to embedding service
   - `POST /v1/rerank` - Proxy to reranker service
   - `GET /v1/models` - Aggregated model list

4. Implement OpenAI compatibility
   - Request/response schema matching
   - Model name mapping
   - Usage token counting
   - Error response formatting

5. Add gateway features
   - Request/response logging
   - Correlation ID tracking
   - OpenAPI documentation
   - Health aggregation from backends

6. Deploy gateway
   - Kubernetes Deployment (no GPU required)
   - Service on port 8004
   - Ingress/LoadBalancer for external access

**Exit Criteria:**
- [ ] `/v1/chat/completions` works with OpenAI SDK
- [ ] `/v1/embeddings` works with OpenAI SDK
- [ ] `/v1/rerank` documented and working
- [ ] Streaming responses functional
- [ ] Model list aggregated from backends
- [ ] Gateway health reflects backend status

---

#### Agent 8: Auth & Rate Limiting (US-5.8)

**Goal:** Implement JWT authentication and rate limiting for the gateway

**Tasks:**
1. Create auth module
   ```
   gateway/
   └── auth/
       ├── jwt.py           # JWT validation
       ├── rate_limiter.py  # Rate limiting
       └── middleware.py    # FastAPI middleware
   ```

2. Implement JWT validation
   - RS256 signature verification
   - Issuer/audience validation
   - Token expiration check
   - Extract tenant_id, user_id, roles
   - JWKS endpoint caching

3. Implement rate limiting
   - Token bucket algorithm
   - Per-tenant limits
   - Per-user limits
   - Configurable via environment
   - Redis backend for distributed limiting

4. Implement middleware
   - Auth middleware - 401/403 responses
   - Rate limit middleware - 429 with Retry-After header
   - Context propagation (X-Tenant-Id, X-User-Id headers to backends)

5. Create error responses
   - 401 Unauthorized (missing/invalid token)
   - 403 Forbidden (insufficient permissions)
   - 429 Too Many Requests (rate limit exceeded)
   - Structured error payloads matching OpenAI format

6. Add configuration
   - Environment variables for rate limits
   - ConfigMap for tenant-specific limits
   - Secret for JWT public keys

**Exit Criteria:**
- [ ] Requests without JWT rejected with 401
- [ ] Invalid JWT rejected with 401
- [ ] Valid JWT passes through
- [ ] Tenant/user context logged
- [ ] Rate limits enforced per tenant
- [ ] 429 response includes Retry-After header
- [ ] Context headers propagated to backends

---

### Wave 4 Checkpoint

**Integration Test:** `tests/integration/test_wave4_gateway.py`

```python
# Test gateway with OpenAI SDK
# Test streaming through gateway
# Test JWT validation
# Test rate limiting triggers 429
# Test context propagation to backends
```

---

## Final Integration & Validation

### End-to-End Test Suite

**File:** `tests/e2e/test_llm_serving_layer.py`

```python
# Full E2E test covering:
# 1. Gateway authentication
# 2. Chat completion via gateway
# 3. Embedding generation via gateway
# 4. Document reranking via gateway
# 5. Rate limiting behavior
# 6. Health endpoint aggregation
# 7. Prometheus metrics collection
# 8. Configuration updates
# 9. A/B routing
# 10. Cost tracking
```

### Performance Validation

| Metric | Target | Test Method |
|--------|--------|-------------|
| LLM Throughput | >100 tokens/sec | `scripts/benchmark_vllm.py` |
| LLM TTFT | <500ms | Measure time to first chunk |
| Embedding Latency (single) | <50ms | Single request timing |
| Embedding Batch (32) | <200ms | Batch request timing |
| Reranker (20 pairs) | <100ms | Rerank timing |
| GPU Utilization | >70% | Monitor during load test |

### Load Testing

```bash
# Run load test against gateway
locust -f tests/load/locustfile.py --host http://gateway:8004

# Target: 100 concurrent users
# Duration: 10 minutes
# Success criteria: <1% error rate, p95 < 2s
```

---

## Deployment Checklist

### Pre-deployment

- [ ] GPU nodes available in cluster
- [ ] NVIDIA device plugin installed
- [ ] HuggingFace token configured (if needed)
- [ ] Container registry access configured
- [ ] Prometheus/Grafana stack deployed
- [ ] Redis available (for rate limiting)

### Wave 1 Deployment

- [ ] `kubectl apply -f llm-serving/vllm/k8s/`
- [ ] `kubectl apply -f llm-serving/embedding-service/k8s/`
- [ ] `kubectl apply -f llm-serving/reranker-service/k8s/`
- [ ] Verify all pods running
- [ ] Run Wave 1 integration tests

### Wave 2 Deployment

- [ ] `kubectl apply -f llm-serving/config/k8s/`
- [ ] `kubectl apply -f llm-serving/resource-management/k8s/`
- [ ] Verify HPA policies active
- [ ] Run Wave 2 integration tests

### Wave 3 Deployment

- [ ] `kubectl apply -f llm-serving/monitoring/prometheus/`
- [ ] Import Grafana dashboards
- [ ] Verify ServiceMonitor active
- [ ] Run Wave 3 integration tests

### Wave 4 Deployment

- [ ] `kubectl apply -f llm-serving/gateway/k8s/`
- [ ] Configure Ingress/LoadBalancer
- [ ] Verify external access
- [ ] Run Wave 4 integration tests

### Post-deployment

- [ ] Run full E2E test suite
- [ ] Run performance benchmarks
- [ ] Verify all alerts not firing
- [ ] Document any deviations

---

## Rollback Plan

### Per-Service Rollback

```bash
# Rollback individual service
kubectl rollout undo deployment/vllm-llama -n llm-serving
kubectl rollout undo deployment/embedding-service -n llm-serving
kubectl rollout undo deployment/reranker-service -n llm-serving
kubectl rollout undo deployment/llm-gateway -n llm-serving
```

### Configuration Rollback

```bash
# Via Configuration API
curl -X POST http://gateway:8004/config/rollback?version=N
```

### Full Epic Rollback

```bash
# Delete entire namespace (caution: destroys all data)
kubectl delete namespace llm-serving

# Re-apply from previous known-good state
kubectl apply -k k8s/overlays/prod-previous/
```

---

## Definition of Done (Epic Level)

- [ ] vLLM deployed and serving Llama-3.1-8B-Instruct
- [ ] OpenAI-compatible API working for chat completions
- [ ] Embedding service generating 1024-dim vectors
- [ ] Reranker service scoring document pairs
- [ ] Unified OpenAI-compatible gateway operational
- [ ] Gateway enforces JWT auth and rate limiting
- [ ] All services have health check endpoints
- [ ] Prometheus metrics exposed and scraped
- [ ] Grafana dashboards created
- [ ] HPA configured for auto-scaling
- [ ] GPU utilization monitored
- [ ] Latency within SLA targets
- [ ] Documentation complete
- [ ] Load testing performed
- [ ] Failover and recovery tested

---

## Appendix: Service Ports

| Service | Internal Port | External Port | Protocol |
|---------|--------------|---------------|----------|
| vLLM | 8000 | - | HTTP |
| Embedding Service | 8001 | - | HTTP |
| Reranker Service | 8002 | - | HTTP |
| Gateway | 8004 | 443 | HTTPS |

## Appendix: Environment Variables

### vLLM
- `MODEL_NAME` - HuggingFace model ID
- `GPU_MEMORY_UTILIZATION` - 0.0-1.0
- `MAX_MODEL_LEN` - Max context length
- `TENSOR_PARALLEL_SIZE` - Number of GPUs

### Embedding Service
- `MODEL_NAME` - Sentence-transformer model
- `MAX_BATCH_SIZE` - Max batch size
- `USE_FP16` - Enable half precision

### Reranker Service
- `MODEL_NAME` - Cross-encoder model
- `MAX_BATCH_SIZE` - Max pairs per batch
- `MAX_SEQUENCE_LENGTH` - Max input length

### Gateway
- `VLLM_URL` - vLLM service URL
- `EMBEDDING_URL` - Embedding service URL
- `RERANKER_URL` - Reranker service URL
- `JWT_ISSUER` - Expected JWT issuer
- `JWT_AUDIENCE` - Expected JWT audience
- `RATE_LIMIT_RPS` - Default rate limit
