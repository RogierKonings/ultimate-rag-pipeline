# Epic 6: Observability Stack - Implementation Plan

> **Epic:** Observability Stack
> **Total Estimated Effort:** 2-3 weeks
> **Dependencies:** Epic 1 (Infrastructure), Epic 3 (Retrieval), Epic 5 (LLM Serving)

## Executive Summary

This implementation plan details the deployment of a comprehensive Observability Stack for the RAG pipeline, comprising OpenTelemetry distributed tracing, Prometheus metrics, structured JSON logging, Grafana dashboards, alerting, and RAG-specific evaluation capabilities (Ragas, Phoenix). The plan is structured in 4 waves with clear checkpoints and integration tests.

---

## Implementation Waves

### Wave 1: Tracing & Metrics Foundation (Parallel)

**Duration:** 4-5 days
**User Stories:** US-6.1, US-6.2, US-6.3 (can be implemented in parallel)

#### Agent 1: OpenTelemetry Integration (US-6.1)

**Goal:** Deploy OpenTelemetry SDK across all services with distributed tracing

**Tasks:**
1. Create observability module structure
   ```
   observability/
   ├── otel/
   │   ├── __init__.py
   │   ├── tracer.py          # OTELConfig, OTELProvider
   │   ├── context.py         # TraceContextPropagator
   │   ├── spans.py           # @traced decorator, rag_span()
   │   ├── attributes.py      # RAGOperation enum, RAGAttributes
   │   └── middleware/
   │       ├── fastapi.py     # OTELMiddleware
   │       └── celery.py      # Celery instrumentation
   ```

2. Implement OTELConfig and OTELProvider (`tracer.py`)
   - Environment-based configuration (OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT)
   - TracerProvider with BatchSpanProcessor
   - OTLP exporter to collector
   - Sampling configuration (10% prod, 100% dev)
   - `setup_tracing()` function for service initialization

3. Define RAG-specific semantic attributes (`attributes.py`)
   - `RAGOperation` enum (QUERY, EMBEDDING, VECTOR_SEARCH, KEYWORD_SEARCH, RERANK, LLM_INFERENCE, etc.)
   - `RAGAttributes` class with standard attribute names
   - Helper functions: `set_rag_attributes()`, `set_retrieval_results()`, `set_llm_usage()`

4. Implement span decorators and helpers (`spans.py`)
   - `@traced` decorator for sync/async functions
   - `rag_span()` context manager
   - `get_current_span()`, `add_span_event()`, `set_span_error()` helpers

5. Implement context propagation (`context.py`)
   - `TraceContextPropagator` class
   - HTTP header injection/extraction (W3C Trace Context)
   - Kafka header support for async messaging
   - FastAPI dependency for extracting trace context

6. Create FastAPI middleware (`middleware/fastapi.py`)
   - Custom `OTELMiddleware` with RAG attributes
   - Tenant/user ID extraction from headers
   - Excluded paths configuration (/health, /metrics)
   - Automatic span creation for all requests

7. Deploy OTEL Collector
   - Create `k8s/otel-collector-config.yaml` with:
     - OTLP receivers (gRPC 4317, HTTP 4318)
     - Tail-based sampling (errors, slow traces, LLM calls)
     - Exporters to Jaeger/Tempo, Prometheus, Loki
   - Deploy Collector Deployment and Service

8. Deploy Jaeger (development) / Tempo (production)
   - All-in-one Jaeger for development
   - Tempo StatefulSet for production
   - UI accessible on port 16686

**Exit Criteria:**
- [ ] OTELConfig loads from environment
- [ ] Tracer creates spans with correct attributes
- [ ] Context propagates across HTTP calls
- [ ] FastAPI middleware adds trace context
- [ ] OTEL Collector deployed and healthy
- [ ] Jaeger/Tempo shows traces from services
- [ ] `pytest tests/observability/test_otel.py` passes

---

#### Agent 2: Prometheus Metrics (US-6.2)

**Goal:** Implement Prometheus metrics collection across all services

**Tasks:**
1. Create metrics module structure
   ```
   observability/
   ├── metrics/
   │   ├── __init__.py
   │   ├── registry.py        # RAGMetrics class
   │   ├── collectors.py      # VectorDB, PostgreSQL collectors
   │   ├── middleware.py      # PrometheusMiddleware
   │   └── exporters.py       # /metrics endpoint
   ```

2. Implement RAGMetrics class (`registry.py`)
   - Query metrics: `rag_query_total`, `rag_query_duration_seconds`, `rag_query_active`
   - Retrieval metrics: `rag_retrieval_duration_seconds`, `rag_retrieval_result_count`
   - Embedding metrics: `rag_embedding_duration_seconds`, `rag_embedding_tokens_total`
   - LLM metrics: `rag_llm_duration_seconds`, `rag_llm_ttft`, `rag_llm_tokens_total`
   - Ingestion metrics: `rag_documents_ingested_total`, `rag_chunks_created_total`
   - Cache metrics: `rag_cache_hits_total`, `rag_cache_misses_total`

3. Implement PrometheusMiddleware (`middleware.py`)
   - Request counting and duration tracking
   - Endpoint labeling (use route patterns, not raw paths)
   - Active query gauge tracking
   - Status code and error tracking

4. Add /metrics endpoint (`exporters.py`)
   - FastAPI route returning Prometheus format
   - Multiprocess mode support for gunicorn
   - `setup_metrics()` function for service initialization

5. Implement custom collectors (`collectors.py`)
   - `VectorDatabaseCollector` for Qdrant stats (points, collections)
   - `PostgreSQLCollector` for connection pool stats (active, idle)
   - Async metric collection

6. Deploy Prometheus
   - `k8s/prometheus.yaml` with service discovery
   - ServiceMonitor CRDs for RAG services
   - Recording rules for common aggregations
   - Retention configuration (15 days)

**Exit Criteria:**
- [ ] All metric types implemented (Counter, Histogram, Gauge, Summary)
- [ ] `/metrics` endpoint returns valid Prometheus format
- [ ] PrometheusMiddleware tracks requests with correct labels
- [ ] Custom collectors gather vector DB and PostgreSQL stats
- [ ] Prometheus scrapes all service targets
- [ ] Recording rules generate aggregations
- [ ] `pytest tests/observability/test_metrics.py` passes

---

#### Agent 3: Key Metrics Definition (US-6.3)

**Goal:** Define canonical metrics with semantic meaning for dashboards and alerts

**Tasks:**
1. Create metrics definitions module
   ```
   observability/
   ├── metrics/
   │   └── definitions/
   │       ├── __init__.py
   │       ├── query_metrics.py
   │       ├── retrieval_metrics.py
   │       ├── llm_metrics.py
   │       ├── ingestion_metrics.py
   │       ├── cache_metrics.py
   │       └── system_metrics.py
   ```

2. Implement MetricDefinition dataclass
   - Name, type (counter/gauge/histogram/summary), unit
   - Labels with descriptions
   - Use cases and example PromQL queries
   - Histogram buckets where applicable
   - SLO relevance flag

3. Create METRIC_CATALOG registry
   - All canonical metrics with full documentation
   - `get_slo_relevant_metrics()` function
   - `generate_metrics_documentation()` function
   - Naming convention validation

4. Define SLI/SLO classes (`sli.py`, `slo.py`)
   - `SLI` dataclass with query templates
   - `SLO` dataclass with targets, windows, burn rates
   - Key SLOs:
     - Query Latency: 99% < 2s (30d window)
     - Availability: 99.9% (30d window)
     - LLM TTFT: 95% < 1s (7d window)
     - Retrieval Latency: 99% < 500ms (30d window)

5. Generate SLO recording rules
   - `generate_slo_recording_rules()` for Prometheus
   - `generate_slo_burn_rate_alerts()` for alerting
   - Multi-window burn rate calculations

6. Generate metrics catalog documentation
   - `docs/metrics-catalog.md` with all metrics
   - Label cardinality guidelines
   - Example queries for each metric

**Exit Criteria:**
- [ ] All metrics follow `rag_<subsystem>_<metric>_<unit>` convention
- [ ] MetricDefinition includes labels, descriptions, example queries
- [ ] SLI/SLO definitions complete with error budget calculations
- [ ] Recording rules generated and deployable
- [ ] Burn rate alert templates created
- [ ] Metrics catalog markdown documentation generated
- [ ] `pytest tests/observability/test_metric_definitions.py` passes

---

### Wave 1 Checkpoint

**Integration Test:** `tests/integration/test_wave1_observability_foundation.py`

```python
# Verify OTEL tracing works end-to-end
# Test trace context propagation across services
# Verify Prometheus scrapes all targets
# Test metric increment and histogram observations
# Verify SLO recording rules calculate correctly
```

---

### Wave 2: Logging & Visualization

**Duration:** 4-5 days
**User Stories:** US-6.5, US-6.4, US-6.8 (can be done in parallel)
**Dependencies:** Wave 1 completed

#### Agent 4: Structured Logging (US-6.5)

**Goal:** Implement JSON structured logging with trace correlation

**Tasks:**
1. Create logging module structure
   ```
   observability/
   ├── logging/
   │   ├── __init__.py
   │   ├── config.py          # LoggingConfig
   │   ├── logger.py          # setup_logging(), get_logger()
   │   ├── formatters.py      # JSONFormatter
   │   ├── filters.py         # SensitiveDataFilter
   │   ├── context.py         # ContextInjectorFilter
   │   └── middleware/
   │       └── fastapi.py     # RequestLoggingMiddleware
   ```

2. Implement LoggingConfig (`config.py`)
   - Service identification (name, version, environment)
   - Log level, output format (JSON/text)
   - Sensitive field filtering list
   - Request/response body logging toggles
   - Excluded paths configuration

3. Implement JSONFormatter (`formatters.py`)
   - ISO 8601 timestamps
   - Service metadata block
   - Source location (file, line, function)
   - Trace context injection (trace_id, span_id from OTEL)
   - Exception formatting with stacktrace
   - `PrettyJSONFormatter` for development

4. Implement SensitiveDataFilter (`filters.py`)
   - Field name matching (password, token, api_key, secret, etc.)
   - Pattern matching (JWT tokens, API keys, credit cards)
   - Recursive dict/list masking
   - Configurable mask pattern

5. Implement context injection (`context.py`)
   - ContextVars for request_id, tenant_id, user_id
   - `ContextInjectorFilter` for automatic injection
   - `LoggerAdapter` for consistent context in log calls
   - `set_request_context()`, `clear_request_context()` helpers

6. Create logger factory (`logger.py`)
   - `setup_logging()` function for service initialization
   - Async logging with QueueHandler/QueueListener
   - `get_logger()` returns LoggerAdapter
   - Third-party library log level reduction (urllib3, httpx)

7. Implement RequestLoggingMiddleware (`middleware/fastapi.py`)
   - Request start/completion logging
   - Duration tracking
   - Error logging with stack traces
   - Request ID generation and propagation

8. Deploy Loki and Promtail
   - `k8s/loki.yaml` StatefulSet with retention settings
   - `k8s/promtail.yaml` DaemonSet with JSON parsing pipeline
   - Index configuration for trace_id, span_id labels

**Exit Criteria:**
- [ ] JSONFormatter produces valid JSON with trace context
- [ ] SensitiveDataFilter masks passwords, tokens, JWTs
- [ ] Context injection works across async calls
- [ ] RequestLoggingMiddleware logs HTTP requests
- [ ] Loki receives and indexes logs
- [ ] Logs queryable by trace_id in Grafana
- [ ] `pytest tests/observability/test_logging.py` passes

---

#### Agent 5: Grafana Dashboards (US-6.4)

**Goal:** Create operational dashboards for all RAG components

**Tasks:**
1. Create Grafana provisioning structure
   ```
   observability/
   ├── grafana/
   │   ├── provisioning/
   │   │   ├── dashboards/
   │   │   │   ├── dashboards.yaml
   │   │   │   ├── overview.json
   │   │   │   ├── retrieval.json
   │   │   │   ├── llm.json
   │   │   │   ├── ingestion.json
   │   │   │   ├── cache.json
   │   │   │   └── slo.json
   │   │   └── datasources/
   │   │       └── datasources.yaml
   │   └── templates/
   │       ├── base_dashboard.py
   │       └── panels.py
   ```

2. Configure datasources (`datasources.yaml`)
   - Prometheus (default)
   - Loki for logs
   - Jaeger/Tempo for traces
   - Trace-to-logs correlation configuration

3. Create Overview Dashboard (`overview.json`)
   - Stat panels: Request rate, Error rate, P95 latency, Active queries, LLM tokens (24h), Cache hit rate
   - Time series: Request rate over time, Latency distribution (p50/p95/p99)
   - Pie chart: Request breakdown by status
   - Bar gauge: Top tenants by volume
   - Template variables: service, tenant_id

4. Create Retrieval Dashboard (`retrieval.json`)
   - Retrieval rate and P95 latency by strategy
   - Avg results per query, Zero results rate
   - Latency comparison (vector vs keyword vs hybrid)
   - Result count heatmap
   - Reranking latency
   - Vector DB points over time

5. Create LLM Dashboard (`llm.json`)
   - Request rate, P95 latency, P50 TTFT
   - Tokens/sec throughput, Error rate by provider
   - Estimated cost (24h) with token pricing
   - Latency by model comparison
   - TTFT by model
   - Token usage over time (input vs output)
   - Prompt token distribution heatmap

6. Create Ingestion Dashboard (`ingestion.json`)
   - Documents ingested (24h), Rate, Queue depth
   - Error rate by source type, Data throughput
   - Chunks created (24h)
   - Rate by source type over time
   - Queue depth trends
   - Processing time by stage (extraction, chunking, embedding, indexing)

7. Create SLO Dashboard (`slo.json`)
   - SLO gauges (Query Latency 99%, Availability 99.9%, LLM TTFT 95%)
   - Error budget remaining gauges
   - SLO compliance over time
   - Error budget burn rate chart
   - Error budget remaining bar gauge

8. Implement Python dashboard generator (`templates/`)
   - `Dashboard` and `Panel` dataclasses
   - `create_stat_panel()`, `create_timeseries_panel()` helpers
   - JSON export functionality

9. Deploy Grafana
   - `k8s/grafana.yaml` Deployment
   - Volume mounts for provisioning
   - Service and Ingress configuration
   - Plugin installation (piechart)

**Exit Criteria:**
- [ ] Overview dashboard with key metrics visible
- [ ] Retrieval service dashboard functional
- [ ] LLM service dashboard functional
- [ ] Ingestion pipeline dashboard functional
- [ ] SLO/Error budget dashboard functional
- [ ] Template variables working across dashboards
- [ ] Thresholds configured with color coding
- [ ] Grafana deployed with provisioning
- [ ] Dashboards version controlled as JSON

---

#### Agent 6: Alerting (US-6.8)

**Goal:** Implement Prometheus alerting with Slack/PagerDuty notifications

**Tasks:**
1. Create alerting structure
   ```
   observability/
   ├── alerting/
   │   ├── alertmanager/
   │   │   ├── alertmanager.yaml
   │   │   └── templates/
   │   │       └── slack.tmpl
   │   ├── rules/
   │   │   ├── rag_alerts.yaml
   │   │   ├── slo_alerts.yaml
   │   │   └── infrastructure_alerts.yaml
   │   └── runbooks/
   │       ├── high_error_rate.md
   │       ├── high_latency.md
   │       └── llm_provider_errors.md
   ```

2. Configure Alertmanager (`alertmanager.yaml`)
   - Global settings (resolve_timeout, Slack API URL)
   - Route tree for severity-based routing
   - Slack receiver with channel per severity
   - PagerDuty receiver for critical alerts
   - Inhibition rules (critical suppresses warning)
   - Grouping by alertname, service

3. Create Slack templates (`templates/slack.tmpl`)
   - Title, status, severity formatting
   - Color coding (red=critical, orange=warning)
   - Description and runbook links
   - Firing/resolved status indicators

4. Define RAG alerts (`rules/rag_alerts.yaml`)
   - `RAGHighErrorRate` - >5% errors over 5m (critical)
   - `RAGHighLatency` - P95 > 2s over 5m (warning)
   - `RAGLLMProviderErrors` - >10% LLM errors over 5m (critical)
   - `RAGLLMHighTTFT` - P95 TTFT > 2s over 5m (warning)
   - `RAGRetrievalZeroResults` - >20% zero results over 15m (warning)
   - `RAGIngestionQueueBacklog` - Queue > 1000 for 15m (warning)
   - `RAGCacheLowHitRate` - <50% hit rate over 1h (warning)

5. Define SLO burn rate alerts (`rules/slo_alerts.yaml`)
   - Multi-window burn rate alerts for each SLO
   - Fast burn (14.4x over 1h) → page immediately
   - Slow burn (6x over 6h) → page
   - Very slow burn (1x over 3d) → create ticket
   - Error budget exhausted alerts (100% consumed)

6. Define infrastructure alerts (`rules/infrastructure_alerts.yaml`)
   - High CPU/memory usage (>90% for 5m)
   - Pod restart alerts (>3 restarts in 15m)
   - Disk space warnings (<10% free)
   - Database connection pool exhaustion
   - Vector DB health degradation
   - OTEL Collector backpressure

7. Create runbooks
   - Investigation steps for each alert
   - Remediation actions
   - Escalation procedures
   - Links to relevant dashboards
   - Common root causes

8. Deploy Alertmanager
   - `k8s/alertmanager.yaml` Deployment
   - Secret for Slack webhook URL
   - PrometheusRule CRDs for all rules
   - ServiceMonitor for Alertmanager

**Exit Criteria:**
- [ ] Alertmanager configured with routing
- [ ] Slack templates created and formatted
- [ ] RAG-specific alerts defined with correct thresholds
- [ ] SLO burn rate alerts configured
- [ ] Infrastructure alerts defined
- [ ] Runbooks created for all critical alerts
- [ ] Alertmanager deployed to cluster
- [ ] Test alert successfully reaches Slack
- [ ] `promtool check rules rules/*.yaml` passes

---

### Wave 2 Checkpoint

**Integration Test:** `tests/integration/test_wave2_logging_dashboards.py`

```python
# Verify JSON logging format
# Test trace_id appears in logs
# Verify Loki ingestion
# Test Grafana datasource connectivity
# Verify alert rule syntax
# Test Alertmanager routing
```

---

### Wave 3: Advanced Observability

**Duration:** 4-5 days
**User Stories:** US-6.6, US-6.7 (can be done in parallel)
**Dependencies:** Wave 1 & 2 completed

#### Agent 7: Ragas Evaluation (US-6.6)

**Goal:** Implement automated RAG quality evaluation with Ragas metrics

**Tasks:**
1. Create evaluation module structure
   ```
   observability/
   ├── evaluation/
   │   ├── __init__.py
   │   ├── config.py          # EvaluationConfig
   │   ├── ragas_evaluator.py # RagasEvaluator
   │   ├── datasets.py        # EvaluationSample, EvaluationDataset
   │   ├── metrics.py         # Custom metric implementations
   │   ├── pipeline.py        # EvaluationPipeline
   │   ├── reporters.py       # JSON, PostgreSQL, Grafana reporters
   │   └── schedulers/
   │       ├── celery_tasks.py
   │       └── k8s_cronjob.yaml
   ```

2. Implement EvaluationConfig (`config.py`)
   - Evaluator model configuration (gpt-4 or local)
   - Metrics selection list
   - Dataset paths and sampling config
   - Schedule configuration
   - Result storage settings

3. Implement RagasEvaluator (`ragas_evaluator.py`)
   - Wrapper around Ragas library
   - Supported metrics:
     - `context_precision` - Retrieved context relevance
     - `context_recall` - Coverage of ground truth
     - `faithfulness` - Answer grounded in context
     - `answer_relevancy` - Answer addresses question
   - Custom metric support
   - Batch evaluation with progress tracking

4. Implement dataset management (`datasets.py`)
   - `EvaluationSample` dataclass (question, contexts, answer, ground_truth)
   - `EvaluationDataset` class with loading/saving
   - JSON and HuggingFace format support
   - Dataset versioning

5. Implement EvaluationPipeline (`pipeline.py`)
   - Sample selection (random, stratified)
   - RAG execution against live pipeline
   - Evaluation execution with timeout
   - Result aggregation (mean, std, percentiles)
   - Trend comparison with previous runs

6. Implement reporters (`reporters.py`)
   - `JSONFileReporter` for local storage
   - `PostgreSQLReporter` for database persistence
   - `GrafanaAnnotationReporter` for dashboard markers
   - `SlackReporter` for notifications with summary

7. Create Celery scheduled tasks (`schedulers/celery_tasks.py`)
   - Weekly evaluation task (Sunday 2am)
   - On-demand evaluation task via API
   - Result notification task

8. Create Kubernetes CronJob (`schedulers/k8s_cronjob.yaml`)
   - Weekly schedule (0 2 * * 0)
   - Resource limits (4Gi RAM, no GPU required)
   - Secrets for API keys
   - Restart policy (OnFailure)

**Exit Criteria:**
- [ ] RagasEvaluator computes all four core metrics
- [ ] Dataset loading/saving works for JSON and HuggingFace
- [ ] EvaluationPipeline orchestrates end-to-end flow
- [ ] All reporters implemented and working
- [ ] Celery tasks scheduled and triggerable
- [ ] Kubernetes CronJob deployed
- [ ] Results visible as Grafana annotations
- [ ] `pytest tests/observability/test_ragas_evaluation.py` passes

---

#### Agent 8: Arize Phoenix Integration (US-6.7)

**Goal:** Integrate Arize Phoenix for LLM-specific observability

**Tasks:**
1. Create Phoenix module structure
   ```
   observability/
   ├── phoenix/
   │   ├── __init__.py
   │   ├── config.py          # PhoenixConfig
   │   ├── tracer.py          # PhoenixTracer
   │   ├── callbacks.py       # LangChain, OpenAI, LlamaIndex callbacks
   │   ├── feedback.py        # FeedbackCollector
   │   ├── experiments.py     # ExperimentTracker
   │   └── embeddings.py      # Embedding visualization
   ```

2. Implement PhoenixConfig (`config.py`)
   - Phoenix server endpoint
   - Project name, environment
   - Sampling configuration
   - Feature flags for components
   - Export settings

3. Implement PhoenixTracer (`tracer.py`)
   - LLM span creation with attributes
   - Prompt/completion capture
   - Token usage tracking
   - Latency measurements
   - Streaming support
   - Context propagation from OTEL

4. Create LLM callbacks (`callbacks.py`)
   - `PhoenixLangChainCallback` for LangChain integration
   - `PhoenixOpenAIInstrumentor` for OpenAI client
   - `PhoenixLlamaIndexInstrumentor` for LlamaIndex
   - Automatic prompt/response logging
   - Error capture and classification

5. Implement feedback collection (`feedback.py`)
   - `FeedbackCollector` class
   - Feedback types: thumbs up/down, rating (1-5), free-form comments
   - API endpoints for feedback submission
   - Feedback to span association via trace_id
   - Aggregation and reporting

6. Implement experiment tracking (`experiments.py`)
   - `ExperimentTracker` class
   - Prompt versioning (name, version, content hash)
   - A/B test assignment (user-based, random)
   - Metrics comparison between variants
   - Statistical significance calculation

7. Implement embedding visualization (`embeddings.py`)
   - Export embeddings to Phoenix
   - Cluster visualization support
   - Query-document similarity analysis

8. Deploy Phoenix
   - `k8s/phoenix.yaml` Deployment
   - PostgreSQL for storage (can share with main DB)
   - Service on port 6006
   - PVC for data persistence

**Exit Criteria:**
- [ ] PhoenixTracer captures LLM calls with full details
- [ ] Callbacks work with LangChain/OpenAI
- [ ] Feedback collection API working
- [ ] Feedback associated with traces
- [ ] Experiment tracking implemented
- [ ] Phoenix deployed and accessible
- [ ] LLM traces visible in Phoenix UI
- [ ] `pytest tests/observability/test_phoenix.py` passes

---

### Wave 3 Checkpoint

**Integration Test:** `tests/integration/test_wave3_evaluation.py`

```python
# Run sample Ragas evaluation
# Verify metrics computed correctly
# Test PostgreSQL result persistence
# Verify Phoenix captures LLM traces
# Test feedback submission and retrieval
# Verify experiment tracking
```

---

### Wave 4: Validation & Persistence

**Duration:** 2-3 days
**User Stories:** US-6.9, US-6.10 (can be done in parallel)
**Dependencies:** Wave 1, 2, 3 completed

#### Agent 9: Trace/Log Storage Validation (US-6.9)

**Goal:** Validate end-to-end trace and log storage with correlation

**Tasks:**
1. Verify OTLP exporter configuration
   - All services export to OTEL Collector
   - Trace context propagates across HTTP calls
   - Async message trace propagation (Celery)

2. Verify Loki ingestion pipeline
   - Promtail or OTEL log pipeline configured
   - JSON logs parsed correctly
   - trace_id/span_id extracted to indexed labels
   - Log retention configured (30 days)

3. Create validation dashboards/queries
   - Grafana panel linking traces to logs
   - LogQL query template: `{service="orchestrator"} |= "trace_id"`
   - Trace-to-log drill-down in Grafana

4. Write smoke tests
   - Send sample request through orchestrator
   - Verify trace appears in Tempo/Jaeger with spans from all services
   - Verify logs appear in Loki with matching trace_id
   - Verify trace-log correlation clickable in Grafana

5. Configure missing telemetry alerts (optional)
   - Alert if >X% traces missing for service
   - Alert if log ingestion rate drops significantly

6. Create troubleshooting runbook
   - Steps to query traces by request ID
   - Steps to query logs by trace ID
   - Troubleshooting missing telemetry
   - Common configuration issues

**Exit Criteria:**
- [ ] All services export traces to Tempo/Jaeger
- [ ] Logs include trace_id/span_id fields
- [ ] Loki indexes trace_id as searchable label
- [ ] Grafana trace-to-logs correlation works
- [ ] Smoke tests pass end-to-end
- [ ] Runbook documented
- [ ] `pytest tests/observability/test_trace_log_correlation.py` passes

---

#### Agent 10: Evaluation Data Persistence (US-6.10)

**Goal:** Persist evaluation datasets and results in PostgreSQL

**Tasks:**
1. Create database migrations
   - `eval_datasets` table:
     - id (UUID), name, description
     - config (JSONB), version
     - created_at, updated_at
   - `eval_examples` table:
     - id (UUID), dataset_id (FK)
     - question, contexts (JSONB), ground_truth, metadata (JSONB)
     - created_at
   - `eval_runs` table:
     - id (UUID), dataset_id (FK)
     - metrics (JSONB), aggregated_scores (JSONB)
     - pipeline_version, model_version
     - started_at, completed_at, status
     - error_message (nullable)

2. Update PostgreSQLReporter
   - Write eval results to `eval_runs`
   - Link to dataset/examples
   - Store full metrics as JSONB
   - Update run status on completion/failure

3. Create API/CLI for datasets
   - `POST /api/v1/eval/datasets` - Create dataset
   - `GET /api/v1/eval/datasets` - List datasets
   - `GET /api/v1/eval/datasets/{id}` - Get dataset details
   - `POST /api/v1/eval/datasets/{id}/examples` - Add examples
   - `GET /api/v1/eval/datasets/{id}/runs` - List runs
   - `GET /api/v1/eval/runs/{id}` - Get run details with metrics

4. Ensure trace context for eval jobs
   - Evaluation jobs create trace spans
   - Metrics emitted for eval duration
   - Error tracking with span events

5. Configure retry logic
   - Retry on transient database errors
   - Exponential backoff (1s, 2s, 4s, max 30s)
   - Max 3 retries before failure

6. Create evaluation metrics export
   - Prometheus metrics for eval runs
   - `rag_eval_run_duration_seconds`
   - `rag_eval_metric_value` with metric_name label

**Exit Criteria:**
- [ ] Database schema matches architecture spec
- [ ] Migrations run without errors
- [ ] Eval runs persist metrics and metadata
- [ ] API endpoints working and documented
- [ ] Retries handle transient database errors
- [ ] Tests cover CRUD operations
- [ ] `alembic upgrade head` succeeds
- [ ] `pytest tests/evaluation/test_eval_persistence.py` passes

---

### Wave 4 Checkpoint

**Integration Test:** `tests/integration/test_wave4_validation.py`

```python
# Verify trace-log correlation end-to-end
# Test evaluation data persistence
# Verify API endpoints for datasets/runs
# Test retry logic on DB errors
# Verify metrics export for evaluations
```

---

## Final Integration & Validation

### End-to-End Test Suite

**File:** `tests/e2e/test_observability_stack.py`

```python
# Full E2E test covering:
# 1. Request creates trace visible in Jaeger/Tempo
# 2. Trace spans include all services (orchestrator, retrieval, LLM)
# 3. Logs include trace_id and appear in Loki
# 4. Prometheus scrapes metrics from all services
# 5. Grafana dashboards load with real data
# 6. Alert fires when error threshold exceeded (synthetic)
# 7. Ragas evaluation runs and stores results
# 8. Phoenix captures LLM traces with prompts/completions
# 9. Feedback submission works
# 10. Eval results queryable via API
```

### Performance Validation

| Metric | Target | Test Method |
|--------|--------|-------------|
| Trace Overhead | <5ms per span | Benchmark with/without tracing |
| Metric Collection | <1ms per observation | Timing around metric.inc() |
| Log Latency | <10ms async | Time from log call to queue |
| Dashboard Load | <3s | Grafana page load time |
| Eval Run (100 samples) | <30min | Full Ragas evaluation |

### Load Testing

```bash
# Generate load and verify observability handles it
locust -f tests/load/locustfile.py --host http://orchestrator:8003

# Target: 100 concurrent users
# Duration: 10 minutes
# Verify: No dropped traces, metrics accurate, dashboards responsive
```

---

## Deployment Checklist

### Pre-deployment

- [ ] Kubernetes cluster operational
- [ ] PostgreSQL, Redis, Qdrant running
- [ ] Sufficient storage for Tempo/Loki (100Gi+)
- [ ] Slack webhook URL configured
- [ ] Container registry access configured

### Wave 1 Deployment

- [ ] `kubectl apply -f observability/k8s/otel-collector.yaml`
- [ ] `kubectl apply -f observability/k8s/jaeger.yaml` (or tempo.yaml)
- [ ] `kubectl apply -f observability/k8s/prometheus.yaml`
- [ ] Verify OTEL Collector healthy
- [ ] Verify Prometheus targets up
- [ ] Run Wave 1 integration tests

### Wave 2 Deployment

- [ ] `kubectl apply -f observability/k8s/loki.yaml`
- [ ] `kubectl apply -f observability/k8s/promtail.yaml`
- [ ] `kubectl apply -f observability/k8s/grafana.yaml`
- [ ] `kubectl apply -f observability/k8s/alertmanager.yaml`
- [ ] Import Grafana dashboards (automatic via provisioning)
- [ ] Verify Loki ingestion
- [ ] Run Wave 2 integration tests

### Wave 3 Deployment

- [ ] `kubectl apply -f observability/k8s/phoenix.yaml`
- [ ] Apply Celery beat schedule for Ragas
- [ ] `kubectl apply -f observability/evaluation/schedulers/k8s_cronjob.yaml`
- [ ] Verify Phoenix UI accessible
- [ ] Run Wave 3 integration tests

### Wave 4 Deployment

- [ ] Run database migrations: `alembic upgrade head`
- [ ] Verify eval_datasets, eval_examples, eval_runs tables exist
- [ ] Run Wave 4 integration tests

### Post-deployment

- [ ] Run full E2E test suite
- [ ] Run performance benchmarks
- [ ] Verify all alerts not firing (or expected)
- [ ] Test Slack notification delivery
- [ ] Document any deviations

---

## Rollback Plan

### Per-Component Rollback

```bash
# Rollback individual deployments
kubectl rollout undo deployment/otel-collector -n observability
kubectl rollout undo deployment/grafana -n observability
kubectl rollout undo deployment/alertmanager -n observability
kubectl rollout undo deployment/phoenix -n observability
```

### Database Migration Rollback

```bash
# Rollback to previous migration
alembic downgrade -1

# Rollback specific number of steps
alembic downgrade -3
```

### Full Epic Rollback

```bash
# Delete observability namespace (caution: destroys all data)
kubectl delete namespace observability

# Re-apply from previous known-good state
kubectl apply -k k8s/overlays/prod-previous/observability/
```

---

## Definition of Done (Epic Level)

- [ ] OTEL SDK integrated in all services (ingestion, retrieval, orchestrator, LLM gateway)
- [ ] Trace context propagates across service boundaries
- [ ] Prometheus scraping all services with RAG metrics
- [ ] Custom RAG metrics defined and exposed
- [ ] Grafana dashboards for all components operational
- [ ] Structured JSON logging with trace correlation
- [ ] Logs aggregated in Loki and queryable
- [ ] Traces stored in Tempo/Jaeger and queryable
- [ ] Trace-to-log correlation working in Grafana
- [ ] Ragas evaluation pipeline running weekly
- [ ] Phoenix capturing LLM traces with feedback support
- [ ] Evaluation datasets/runs persisted per architecture schema
- [ ] Alert rules for all critical scenarios deployed
- [ ] Alertmanager routing to Slack/PagerDuty
- [ ] Runbooks for all critical alerts
- [ ] SLO burn rate alerts configured
- [ ] >80% test coverage across all modules
- [ ] Documentation complete

---

## Appendix: Service Ports

| Service | Internal Port | Protocol | Purpose |
|---------|--------------|----------|---------|
| OTEL Collector (gRPC) | 4317 | gRPC | Trace/metric ingestion |
| OTEL Collector (HTTP) | 4318 | HTTP | Trace/metric ingestion |
| OTEL Collector Health | 13133 | HTTP | Health check |
| Jaeger UI | 16686 | HTTP | Trace visualization |
| Tempo | 3200 | HTTP | Trace query API |
| Prometheus | 9090 | HTTP | Metrics query API |
| Grafana | 3000 | HTTP | Dashboard UI |
| Loki | 3100 | HTTP | Log query API |
| Alertmanager | 9093 | HTTP | Alert management |
| Phoenix | 6006 | HTTP | LLM observability UI |

## Appendix: Environment Variables

### OTEL SDK
- `OTEL_SERVICE_NAME` - Service name for traces
- `OTEL_EXPORTER_OTLP_ENDPOINT` - Collector endpoint
- `OTEL_TRACES_SAMPLER` - head or tail
- `OTEL_TRACES_SAMPLER_ARG` - Sample rate (0.0-1.0)

### Logging
- `LOG_LEVEL` - DEBUG, INFO, WARNING, ERROR
- `LOG_JSON` - true/false for JSON format
- `LOG_TRACE_CONTEXT` - true/false for trace injection

### Metrics
- `PROMETHEUS_MULTIPROC_DIR` - Directory for multiprocess mode

### Phoenix
- `PHOENIX_ENDPOINT` - Phoenix server URL
- `PHOENIX_PROJECT_NAME` - Project identifier
- `PHOENIX_API_KEY` - API authentication (if enabled)

### Evaluation
- `EVAL_DATASET_PATH` - Path to evaluation dataset
- `EVAL_MODEL` - Model for Ragas evaluation
- `EVAL_SCHEDULE` - Cron schedule for evaluations

## Appendix: Key Dependencies

```txt
# OpenTelemetry
opentelemetry-api>=1.22.0
opentelemetry-sdk>=1.22.0
opentelemetry-exporter-otlp>=1.22.0
opentelemetry-instrumentation-fastapi>=0.43b0
opentelemetry-instrumentation-httpx>=0.43b0
opentelemetry-instrumentation-redis>=0.43b0
opentelemetry-instrumentation-sqlalchemy>=0.43b0
opentelemetry-propagator-b3>=1.22.0

# Metrics
prometheus-client>=0.19.0

# Logging
python-json-logger>=2.0.0

# Evaluation
ragas>=0.1.0
langchain-openai>=0.0.5
datasets>=2.14.0

# Phoenix
arize-phoenix>=4.0.0
openinference-instrumentation-openai>=0.1.0
```
