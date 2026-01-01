# US-6.7: Arize Phoenix Integration

> **Story ID:** US-6.7  
> **Epic:** Observability Stack  
> **Priority:** Medium  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-6.1 (OpenTelemetry Integration)

## User Story

**As a** ML engineer  
**I want** LLM observability  
**So that** I can debug and improve prompts

## Context

Arize Phoenix is an open-source LLM observability tool that provides:

- **LLM Tracing**: Detailed traces of LLM calls with prompts/responses
- **Embedding Analysis**: Visualize and analyze embedding spaces
- **Evaluation Tracking**: Track evaluation metrics over time
- **Prompt Debugging**: Compare prompt variations and their effects
- **Feedback Collection**: Capture user feedback for RLHF

Phoenix integrates with OpenTelemetry, making it compatible with our existing tracing infrastructure. It provides specialized views for LLM and RAG workflows that go beyond general-purpose APM tools.

## Technical Requirements

### Directory Structure

```
observability/
├── phoenix/
│   ├── __init__.py
│   ├── config.py              # Phoenix configuration
│   ├── tracer.py              # Phoenix tracer integration
│   ├── callbacks.py           # LLM framework callbacks
│   ├── feedback.py            # Feedback collection
│   ├── experiments.py         # A/B experiment tracking
│   └── embeddings.py          # Embedding analysis
├── docker/
│   └── phoenix-compose.yaml   # Docker Compose for Phoenix
└── k8s/
    └── phoenix.yaml           # Kubernetes deployment
```

### Phoenix Configuration

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import os


class PhoenixDeployment(str, Enum):
    """Phoenix deployment mode."""
    LOCAL = "local"  # Local server
    REMOTE = "remote"  # Remote Phoenix server
    ARIZE_CLOUD = "arize_cloud"  # Arize cloud service


class PhoenixConfig(BaseModel):
    """
    Configuration for Arize Phoenix integration.
    
    Phoenix provides LLM-specific observability including:
    - Prompt/response tracing
    - Token usage tracking
    - Evaluation metrics
    - Embedding visualization
    """
    # Deployment mode
    deployment: PhoenixDeployment = PhoenixDeployment.LOCAL
    
    # Server settings
    host: str = "localhost"
    port: int = 6006
    
    # Remote/cloud settings
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    
    # Project settings
    project_name: str = "rag-pipeline"
    
    # Tracing settings
    enable_tracing: bool = True
    trace_sample_rate: float = 1.0
    
    # What to capture
    capture_prompts: bool = True
    capture_responses: bool = True
    capture_embeddings: bool = True
    capture_metadata: bool = True
    
    # Token limits for captured content
    max_prompt_length: int = 10000
    max_response_length: int = 10000
    
    # Feedback collection
    enable_feedback: bool = True
    
    # A/B experiments
    enable_experiments: bool = True
    
    @classmethod
    def from_env(cls) -> "PhoenixConfig":
        """Create config from environment variables."""
        deployment = os.getenv("PHOENIX_DEPLOYMENT", "local")
        
        return cls(
            deployment=PhoenixDeployment(deployment),
            host=os.getenv("PHOENIX_HOST", "localhost"),
            port=int(os.getenv("PHOENIX_PORT", "6006")),
            endpoint=os.getenv("PHOENIX_ENDPOINT"),
            api_key=os.getenv("PHOENIX_API_KEY"),
            project_name=os.getenv("PHOENIX_PROJECT", "rag-pipeline"),
            trace_sample_rate=float(os.getenv("PHOENIX_SAMPLE_RATE", "1.0")),
        )
```

### Phoenix Tracer Integration

```python
import phoenix as px
from phoenix.otel import register
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from typing import Optional, Dict, Any
import logging


class PhoenixTracer:
    """
    Phoenix tracer for LLM observability.
    
    Integrates with OpenTelemetry to capture:
    - LLM calls with prompts/responses
    - Token usage
    - Latency breakdowns
    - Embedding operations
    
    Example:
        tracer = PhoenixTracer(config)
        tracer.initialize()
        
        with tracer.span("llm_call") as span:
            response = llm.generate(prompt)
            tracer.log_llm_call(span, prompt, response)
    """
    
    def __init__(self, config: PhoenixConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._initialized = False
        self._session = None
    
    def initialize(self) -> None:
        """
        Initialize Phoenix tracing.
        
        Sets up:
        1. Phoenix server (local) or connection (remote)
        2. OpenTelemetry tracer with Phoenix exporter
        3. Auto-instrumentation for supported LLM libraries
        """
        if self._initialized:
            return
        
        # Start Phoenix based on deployment mode
        if self.config.deployment == PhoenixDeployment.LOCAL:
            self._session = px.launch_app()
            endpoint = f"http://{self.config.host}:{self.config.port}"
        elif self.config.deployment == PhoenixDeployment.REMOTE:
            endpoint = self.config.endpoint
        else:
            # Arize Cloud
            endpoint = "https://app.arize.com/v1/traces"
        
        # Register with OpenTelemetry
        tracer_provider = register(
            project_name=self.config.project_name,
            endpoint=endpoint,
        )
        
        # Set as global tracer provider
        trace.set_tracer_provider(tracer_provider)
        
        self._initialized = True
        self.logger.info(f"Phoenix initialized at {endpoint}")
    
    def get_tracer(self, name: str = None) -> trace.Tracer:
        """Get a tracer for creating spans."""
        if not self._initialized:
            self.initialize()
        
        return trace.get_tracer(name or self.config.project_name)
    
    def shutdown(self) -> None:
        """Shutdown Phoenix and flush traces."""
        if self._session:
            self._session.close()
        self._initialized = False


# LLM-specific span attributes
class LLMSpanAttributes:
    """Standard attributes for LLM spans."""
    
    # Input
    INPUT_VALUE = "input.value"
    INPUT_MIME_TYPE = "input.mime_type"
    
    # Output
    OUTPUT_VALUE = "output.value"
    OUTPUT_MIME_TYPE = "output.mime_type"
    
    # LLM specifics
    LLM_MODEL_NAME = "llm.model_name"
    LLM_PROVIDER = "llm.provider"
    LLM_INVOCATION_PARAMS = "llm.invocation_parameters"
    LLM_PROMPT_TEMPLATE = "llm.prompt_template.template"
    LLM_PROMPT_TEMPLATE_VERSION = "llm.prompt_template.version"
    LLM_PROMPT_TEMPLATE_VARIABLES = "llm.prompt_template.variables"
    
    # Token usage
    LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
    LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
    LLM_TOKEN_COUNT_TOTAL = "llm.token_count.total"
    
    # Retrieval
    RETRIEVAL_DOCUMENTS = "retrieval.documents"
    
    # Embedding
    EMBEDDING_MODEL_NAME = "embedding.model_name"
    EMBEDDING_TEXT = "embedding.text"
    EMBEDDING_VECTOR = "embedding.vector"


def log_llm_span(
    span: trace.Span,
    model: str,
    provider: str,
    prompt: str,
    response: str,
    prompt_tokens: int,
    completion_tokens: int,
    temperature: Optional[float] = None,
    **kwargs
) -> None:
    """
    Log LLM call details to a span.
    
    Args:
        span: The current span
        model: LLM model name
        provider: LLM provider (openai, anthropic, etc.)
        prompt: Input prompt
        response: Model response
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        temperature: Sampling temperature
        **kwargs: Additional attributes
    """
    span.set_attribute(LLMSpanAttributes.LLM_MODEL_NAME, model)
    span.set_attribute(LLMSpanAttributes.LLM_PROVIDER, provider)
    span.set_attribute(LLMSpanAttributes.INPUT_VALUE, prompt)
    span.set_attribute(LLMSpanAttributes.OUTPUT_VALUE, response)
    span.set_attribute(LLMSpanAttributes.LLM_TOKEN_COUNT_PROMPT, prompt_tokens)
    span.set_attribute(LLMSpanAttributes.LLM_TOKEN_COUNT_COMPLETION, completion_tokens)
    span.set_attribute(
        LLMSpanAttributes.LLM_TOKEN_COUNT_TOTAL,
        prompt_tokens + completion_tokens
    )
    
    if temperature is not None:
        span.set_attribute("llm.temperature", temperature)
    
    for key, value in kwargs.items():
        span.set_attribute(f"llm.{key}", value)


def log_retrieval_span(
    span: trace.Span,
    query: str,
    documents: List[Dict[str, Any]],
    scores: Optional[List[float]] = None,
) -> None:
    """
    Log retrieval operation to a span.
    
    Args:
        span: The current span
        query: Search query
        documents: Retrieved documents
        scores: Relevance scores
    """
    span.set_attribute(LLMSpanAttributes.INPUT_VALUE, query)
    span.set_attribute(LLMSpanAttributes.RETRIEVAL_DOCUMENTS, len(documents))
    
    # Log documents as events (limited to avoid payload size issues)
    for i, doc in enumerate(documents[:10]):
        span.add_event(
            f"retrieved_document_{i}",
            attributes={
                "document.id": doc.get("id", ""),
                "document.content": doc.get("content", "")[:500],
                "document.score": scores[i] if scores else 0,
            }
        )


def log_embedding_span(
    span: trace.Span,
    model: str,
    texts: List[str],
    token_count: int,
) -> None:
    """
    Log embedding generation to a span.
    
    Args:
        span: The current span
        model: Embedding model name
        texts: Input texts
        token_count: Total tokens processed
    """
    span.set_attribute(LLMSpanAttributes.EMBEDDING_MODEL_NAME, model)
    span.set_attribute("embedding.text_count", len(texts))
    span.set_attribute("embedding.token_count", token_count)
```

### LLM Framework Callbacks

```python
from typing import Any, Dict, List, Optional, Union
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import json


class PhoenixLangChainCallback:
    """
    LangChain callback handler for Phoenix tracing.
    
    Automatically traces:
    - LLM calls
    - Chain executions
    - Tool/Agent actions
    - Retriever queries
    """
    
    def __init__(self, config: PhoenixConfig):
        self.config = config
        self.tracer = trace.get_tracer("langchain")
        self._spans: Dict[str, trace.Span] = {}
    
    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        run_id: str,
        **kwargs
    ) -> None:
        """Called when LLM starts."""
        span = self.tracer.start_span(
            "llm",
            attributes={
                LLMSpanAttributes.LLM_MODEL_NAME: serialized.get("name", "unknown"),
                LLMSpanAttributes.INPUT_VALUE: prompts[0] if prompts else "",
            }
        )
        self._spans[run_id] = span
    
    def on_llm_end(
        self,
        response,
        run_id: str,
        **kwargs
    ) -> None:
        """Called when LLM completes."""
        span = self._spans.pop(run_id, None)
        if span:
            # Extract response text
            if hasattr(response, "generations") and response.generations:
                output = response.generations[0][0].text
            else:
                output = str(response)
            
            span.set_attribute(LLMSpanAttributes.OUTPUT_VALUE, output)
            
            # Extract token usage if available
            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage", {})
                span.set_attribute(
                    LLMSpanAttributes.LLM_TOKEN_COUNT_PROMPT,
                    usage.get("prompt_tokens", 0)
                )
                span.set_attribute(
                    LLMSpanAttributes.LLM_TOKEN_COUNT_COMPLETION,
                    usage.get("completion_tokens", 0)
                )
            
            span.set_status(Status(StatusCode.OK))
            span.end()
    
    def on_llm_error(
        self,
        error: Exception,
        run_id: str,
        **kwargs
    ) -> None:
        """Called when LLM errors."""
        span = self._spans.pop(run_id, None)
        if span:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()
    
    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        run_id: str,
        **kwargs
    ) -> None:
        """Called when chain starts."""
        span = self.tracer.start_span(
            "chain",
            attributes={
                "chain.name": serialized.get("name", "unknown"),
                LLMSpanAttributes.INPUT_VALUE: json.dumps(inputs)[:1000],
            }
        )
        self._spans[run_id] = span
    
    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        run_id: str,
        **kwargs
    ) -> None:
        """Called when chain completes."""
        span = self._spans.pop(run_id, None)
        if span:
            span.set_attribute(
                LLMSpanAttributes.OUTPUT_VALUE,
                json.dumps(outputs)[:1000]
            )
            span.set_status(Status(StatusCode.OK))
            span.end()
    
    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        run_id: str,
        **kwargs
    ) -> None:
        """Called when retriever starts."""
        span = self.tracer.start_span(
            "retriever",
            attributes={
                "retriever.name": serialized.get("name", "unknown"),
                LLMSpanAttributes.INPUT_VALUE: query,
            }
        )
        self._spans[run_id] = span
    
    def on_retriever_end(
        self,
        documents: List[Any],
        run_id: str,
        **kwargs
    ) -> None:
        """Called when retriever completes."""
        span = self._spans.pop(run_id, None)
        if span:
            span.set_attribute(LLMSpanAttributes.RETRIEVAL_DOCUMENTS, len(documents))
            
            for i, doc in enumerate(documents[:5]):
                span.add_event(
                    f"document_{i}",
                    attributes={
                        "content": doc.page_content[:500] if hasattr(doc, "page_content") else str(doc)[:500],
                    }
                )
            
            span.set_status(Status(StatusCode.OK))
            span.end()


class PhoenixOpenAIInstrumentor:
    """
    OpenAI auto-instrumentation for Phoenix.
    
    Wraps OpenAI client to automatically trace all calls.
    """
    
    def __init__(self, config: PhoenixConfig):
        self.config = config
    
    def instrument(self) -> None:
        """Instrument OpenAI library."""
        from openinference.instrumentation.openai import OpenAIInstrumentor
        
        OpenAIInstrumentor().instrument()
    
    def uninstrument(self) -> None:
        """Remove instrumentation."""
        from openinference.instrumentation.openai import OpenAIInstrumentor
        
        OpenAIInstrumentor().uninstrument()


class PhoenixLlamaIndexInstrumentor:
    """
    LlamaIndex auto-instrumentation for Phoenix.
    
    Traces all LlamaIndex operations including:
    - Query engines
    - Retrievers
    - LLM calls
    - Embeddings
    """
    
    def __init__(self, config: PhoenixConfig):
        self.config = config
    
    def instrument(self) -> None:
        """Instrument LlamaIndex library."""
        from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
        
        LlamaIndexInstrumentor().instrument()
    
    def uninstrument(self) -> None:
        """Remove instrumentation."""
        from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
        
        LlamaIndexInstrumentor().uninstrument()
```

### Feedback Collection

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4
from enum import Enum


class FeedbackType(str, Enum):
    """Types of feedback."""
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    RATING = "rating"
    CORRECTION = "correction"
    COMMENT = "comment"


@dataclass
class Feedback:
    """
    User feedback on a RAG response.
    
    Used for:
    - Quality monitoring
    - RLHF data collection
    - Issue identification
    """
    id: str
    span_id: str  # Links to the Phoenix trace
    trace_id: str
    feedback_type: FeedbackType
    value: Any  # Boolean for thumbs, 1-5 for rating, string for correction/comment
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class FeedbackCollector:
    """
    Collects and stores user feedback linked to Phoenix traces.
    
    Feedback is stored in:
    1. PostgreSQL for persistence
    2. Phoenix for correlation with traces
    
    Example:
        collector = FeedbackCollector(config)
        
        # Record thumbs up
        collector.record_feedback(
            span_id="span-123",
            trace_id="trace-456",
            feedback_type=FeedbackType.THUMBS_UP,
            value=True,
        )
    """
    
    def __init__(self, config: PhoenixConfig, db_url: Optional[str] = None):
        self.config = config
        self.db_url = db_url
        self._feedback_buffer: List[Feedback] = []
    
    def record_feedback(
        self,
        span_id: str,
        trace_id: str,
        feedback_type: FeedbackType,
        value: Any,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Feedback:
        """
        Record user feedback for a trace.
        
        Args:
            span_id: Phoenix span ID
            trace_id: Phoenix trace ID
            feedback_type: Type of feedback
            value: Feedback value
            user_id: Optional user identifier
            metadata: Additional context
        
        Returns:
            Created Feedback object
        """
        feedback = Feedback(
            id=str(uuid4()),
            span_id=span_id,
            trace_id=trace_id,
            feedback_type=feedback_type,
            value=value,
            user_id=user_id,
            metadata=metadata,
        )
        
        self._feedback_buffer.append(feedback)
        
        # Send to Phoenix
        self._send_to_phoenix(feedback)
        
        return feedback
    
    def _send_to_phoenix(self, feedback: Feedback) -> None:
        """Send feedback to Phoenix."""
        import phoenix as px
        
        # Phoenix annotation API
        px.Client().log_annotation(
            span_id=feedback.span_id,
            name=feedback.feedback_type.value,
            label=str(feedback.value),
            score=self._feedback_to_score(feedback),
            metadata=feedback.metadata,
        )
    
    def _feedback_to_score(self, feedback: Feedback) -> Optional[float]:
        """Convert feedback to numeric score."""
        if feedback.feedback_type == FeedbackType.THUMBS_UP:
            return 1.0 if feedback.value else 0.0
        elif feedback.feedback_type == FeedbackType.THUMBS_DOWN:
            return 0.0 if feedback.value else 1.0
        elif feedback.feedback_type == FeedbackType.RATING:
            return feedback.value / 5.0  # Normalize to 0-1
        return None
    
    async def flush_to_database(self) -> None:
        """Flush buffered feedback to database."""
        if not self.db_url or not self._feedback_buffer:
            return
        
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        engine = create_async_engine(self.db_url)
        
        async with engine.begin() as conn:
            for feedback in self._feedback_buffer:
                await conn.execute(
                    text("""
                        INSERT INTO feedback 
                        (id, span_id, trace_id, feedback_type, value, user_id, metadata, timestamp)
                        VALUES (:id, :span_id, :trace_id, :feedback_type, :value, :user_id, :metadata, :timestamp)
                    """),
                    {
                        "id": feedback.id,
                        "span_id": feedback.span_id,
                        "trace_id": feedback.trace_id,
                        "feedback_type": feedback.feedback_type.value,
                        "value": str(feedback.value),
                        "user_id": feedback.user_id,
                        "metadata": json.dumps(feedback.metadata) if feedback.metadata else None,
                        "timestamp": feedback.timestamp,
                    }
                )
        
        self._feedback_buffer.clear()
    
    def get_feedback_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get aggregate feedback statistics."""
        # Query database for stats
        pass
```

### A/B Experiment Tracking

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4
import random


@dataclass
class Experiment:
    """
    A/B experiment definition.
    
    Tracks different configurations/prompts to compare performance.
    """
    id: str
    name: str
    description: str
    variants: List[Dict[str, Any]]  # List of variant configs
    traffic_split: List[float]  # Traffic allocation per variant
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "running"  # running, paused, completed
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExperimentTracker:
    """
    Tracks A/B experiments for prompt optimization.
    
    Features:
    - Traffic splitting
    - Variant assignment
    - Metric collection per variant
    - Statistical analysis
    
    Example:
        tracker = ExperimentTracker(config)
        
        # Create experiment
        experiment = tracker.create_experiment(
            name="prompt_v2_test",
            variants=[
                {"prompt_template": "v1", "temperature": 0.7},
                {"prompt_template": "v2", "temperature": 0.5},
            ],
            traffic_split=[0.5, 0.5],
        )
        
        # Get variant for user
        variant = tracker.get_variant(experiment.id, user_id="user-123")
    """
    
    def __init__(self, config: PhoenixConfig):
        self.config = config
        self._experiments: Dict[str, Experiment] = {}
        self._assignments: Dict[str, Dict[str, int]] = {}  # experiment_id -> user_id -> variant_idx
    
    def create_experiment(
        self,
        name: str,
        description: str,
        variants: List[Dict[str, Any]],
        traffic_split: Optional[List[float]] = None,
    ) -> Experiment:
        """
        Create a new experiment.
        
        Args:
            name: Experiment name
            description: Description of what's being tested
            variants: List of variant configurations
            traffic_split: Traffic allocation (must sum to 1.0)
        
        Returns:
            Created experiment
        """
        if traffic_split is None:
            # Equal split
            traffic_split = [1.0 / len(variants)] * len(variants)
        
        assert abs(sum(traffic_split) - 1.0) < 0.01, "Traffic split must sum to 1.0"
        
        experiment = Experiment(
            id=str(uuid4()),
            name=name,
            description=description,
            variants=variants,
            traffic_split=traffic_split,
            start_time=datetime.utcnow(),
        )
        
        self._experiments[experiment.id] = experiment
        self._assignments[experiment.id] = {}
        
        return experiment
    
    def get_variant(
        self,
        experiment_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Get assigned variant for a user.
        
        Uses deterministic assignment based on user_id for consistency.
        
        Args:
            experiment_id: Experiment ID
            user_id: User identifier
        
        Returns:
            Variant configuration
        """
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != "running":
            return experiment.variants[0] if experiment else {}
        
        # Check existing assignment
        if user_id in self._assignments[experiment_id]:
            idx = self._assignments[experiment_id][user_id]
            return experiment.variants[idx]
        
        # Deterministic assignment based on hash
        hash_val = hash(f"{experiment_id}:{user_id}") % 1000
        cumulative = 0
        
        for idx, split in enumerate(experiment.traffic_split):
            cumulative += split * 1000
            if hash_val < cumulative:
                self._assignments[experiment_id][user_id] = idx
                return experiment.variants[idx]
        
        # Fallback to last variant
        self._assignments[experiment_id][user_id] = len(experiment.variants) - 1
        return experiment.variants[-1]
    
    def log_experiment_metric(
        self,
        experiment_id: str,
        user_id: str,
        metric_name: str,
        metric_value: float,
        span_id: Optional[str] = None,
    ) -> None:
        """
        Log a metric for an experiment variant.
        
        Args:
            experiment_id: Experiment ID
            user_id: User identifier
            metric_name: Metric name (e.g., "latency", "satisfaction")
            metric_value: Metric value
            span_id: Optional Phoenix span ID for correlation
        """
        variant_idx = self._assignments.get(experiment_id, {}).get(user_id, 0)
        
        # Log to Phoenix
        import phoenix as px
        
        px.Client().log_annotation(
            span_id=span_id,
            name=f"experiment.{experiment_id}",
            label=f"variant_{variant_idx}",
            score=metric_value,
            metadata={
                "metric_name": metric_name,
                "experiment_id": experiment_id,
                "variant_idx": variant_idx,
            }
        )
    
    def get_experiment_results(
        self,
        experiment_id: str,
    ) -> Dict[str, Any]:
        """
        Get experiment results with statistical analysis.
        
        Returns:
            Results including per-variant metrics and significance tests
        """
        # Query Phoenix for experiment metrics
        # Perform statistical analysis
        pass
```

### Kubernetes Deployment

```yaml
# phoenix.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: phoenix
  namespace: observability
spec:
  replicas: 1
  selector:
    matchLabels:
      app: phoenix
  template:
    metadata:
      labels:
        app: phoenix
    spec:
      containers:
        - name: phoenix
          image: arizephoenix/phoenix:latest
          ports:
            - containerPort: 6006
              name: http
            - containerPort: 4317
              name: otlp-grpc
          env:
            - name: PHOENIX_WORKING_DIR
              value: /phoenix
            - name: PHOENIX_PORT
              value: "6006"
          resources:
            requests:
              memory: 512Mi
              cpu: 250m
            limits:
              memory: 2Gi
              cpu: 1000m
          volumeMounts:
            - name: data
              mountPath: /phoenix
          livenessProbe:
            httpGet:
              path: /health
              port: 6006
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 6006
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: phoenix-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: phoenix
  namespace: observability
spec:
  selector:
    app: phoenix
  ports:
    - name: http
      port: 6006
      targetPort: 6006
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
  type: ClusterIP
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: phoenix-pvc
  namespace: observability
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 50Gi
---
# Ingress for Phoenix UI
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: phoenix
  namespace: observability
  annotations:
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: phoenix-auth
spec:
  rules:
    - host: phoenix.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: phoenix
                port:
                  number: 6006
```

### FastAPI Integration

```python
from fastapi import FastAPI, Request, Depends
from contextlib import asynccontextmanager


@asynccontextmanager
async def phoenix_lifespan(app: FastAPI):
    """Lifespan handler to manage Phoenix."""
    config = PhoenixConfig.from_env()
    tracer = PhoenixTracer(config)
    tracer.initialize()
    
    # Instrument libraries
    if config.enable_tracing:
        PhoenixOpenAIInstrumentor(config).instrument()
        PhoenixLlamaIndexInstrumentor(config).instrument()
    
    app.state.phoenix_tracer = tracer
    app.state.feedback_collector = FeedbackCollector(config)
    
    yield
    
    tracer.shutdown()


def get_phoenix_tracer(request: Request) -> PhoenixTracer:
    """Dependency to get Phoenix tracer."""
    return request.app.state.phoenix_tracer


def get_feedback_collector(request: Request) -> FeedbackCollector:
    """Dependency to get feedback collector."""
    return request.app.state.feedback_collector


# Example usage in endpoint
@app.post("/query")
async def query(
    request: QueryRequest,
    tracer: PhoenixTracer = Depends(get_phoenix_tracer),
):
    with tracer.get_tracer().start_as_current_span("rag_query") as span:
        # Your RAG logic here
        span.set_attribute(LLMSpanAttributes.INPUT_VALUE, request.query)
        
        response = await rag_pipeline.query(request.query)
        
        span.set_attribute(LLMSpanAttributes.OUTPUT_VALUE, response.answer)
        
        return response


@app.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    collector: FeedbackCollector = Depends(get_feedback_collector),
):
    feedback = collector.record_feedback(
        span_id=request.span_id,
        trace_id=request.trace_id,
        feedback_type=FeedbackType(request.feedback_type),
        value=request.value,
        user_id=request.user_id,
    )
    
    return {"feedback_id": feedback.id}
```

## Unit Tests

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


@pytest.fixture
def phoenix_config():
    """Create test Phoenix configuration."""
    return PhoenixConfig(
        deployment=PhoenixDeployment.LOCAL,
        project_name="test-project",
        capture_prompts=True,
        capture_responses=True,
    )


def test_phoenix_config_from_env(monkeypatch):
    """Test configuration from environment."""
    monkeypatch.setenv("PHOENIX_DEPLOYMENT", "remote")
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://phoenix:6006")
    monkeypatch.setenv("PHOENIX_PROJECT", "my-project")
    
    config = PhoenixConfig.from_env()
    
    assert config.deployment == PhoenixDeployment.REMOTE
    assert config.project_name == "my-project"


def test_log_llm_span():
    """Test LLM span logging."""
    mock_span = Mock()
    
    log_llm_span(
        span=mock_span,
        model="gpt-4",
        provider="openai",
        prompt="Test prompt",
        response="Test response",
        prompt_tokens=10,
        completion_tokens=20,
        temperature=0.7,
    )
    
    mock_span.set_attribute.assert_any_call(LLMSpanAttributes.LLM_MODEL_NAME, "gpt-4")
    mock_span.set_attribute.assert_any_call(LLMSpanAttributes.INPUT_VALUE, "Test prompt")
    mock_span.set_attribute.assert_any_call(LLMSpanAttributes.LLM_TOKEN_COUNT_TOTAL, 30)


def test_log_retrieval_span():
    """Test retrieval span logging."""
    mock_span = Mock()
    
    documents = [
        {"id": "doc1", "content": "Content 1"},
        {"id": "doc2", "content": "Content 2"},
    ]
    
    log_retrieval_span(
        span=mock_span,
        query="test query",
        documents=documents,
        scores=[0.9, 0.8],
    )
    
    mock_span.set_attribute.assert_any_call(LLMSpanAttributes.INPUT_VALUE, "test query")
    mock_span.set_attribute.assert_any_call(LLMSpanAttributes.RETRIEVAL_DOCUMENTS, 2)
    assert mock_span.add_event.call_count == 2


def test_feedback_creation():
    """Test feedback object creation."""
    feedback = Feedback(
        id="fb-1",
        span_id="span-123",
        trace_id="trace-456",
        feedback_type=FeedbackType.THUMBS_UP,
        value=True,
    )
    
    assert feedback.id == "fb-1"
    assert feedback.timestamp is not None


def test_feedback_to_score():
    """Test feedback score conversion."""
    collector = FeedbackCollector(PhoenixConfig())
    
    # Thumbs up
    feedback = Feedback(
        id="fb-1",
        span_id="s1",
        trace_id="t1",
        feedback_type=FeedbackType.THUMBS_UP,
        value=True,
    )
    assert collector._feedback_to_score(feedback) == 1.0
    
    # Rating
    feedback = Feedback(
        id="fb-2",
        span_id="s1",
        trace_id="t1",
        feedback_type=FeedbackType.RATING,
        value=4,
    )
    assert collector._feedback_to_score(feedback) == 0.8


def test_experiment_creation():
    """Test experiment creation."""
    tracker = ExperimentTracker(PhoenixConfig())
    
    experiment = tracker.create_experiment(
        name="test_experiment",
        description="Testing",
        variants=[
            {"prompt": "v1"},
            {"prompt": "v2"},
        ],
    )
    
    assert experiment.name == "test_experiment"
    assert len(experiment.variants) == 2
    assert sum(experiment.traffic_split) == pytest.approx(1.0)


def test_experiment_variant_assignment():
    """Test deterministic variant assignment."""
    tracker = ExperimentTracker(PhoenixConfig())
    
    experiment = tracker.create_experiment(
        name="test",
        description="Test",
        variants=[{"v": 1}, {"v": 2}],
        traffic_split=[0.5, 0.5],
    )
    
    # Same user should get same variant
    variant1 = tracker.get_variant(experiment.id, "user-123")
    variant2 = tracker.get_variant(experiment.id, "user-123")
    
    assert variant1 == variant2


def test_langchain_callback_llm_start():
    """Test LangChain callback LLM start."""
    config = PhoenixConfig()
    callback = PhoenixLangChainCallback(config)
    
    with patch.object(callback.tracer, 'start_span') as mock_start:
        mock_span = Mock()
        mock_start.return_value = mock_span
        
        callback.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["Test prompt"],
            run_id="run-1",
        )
        
        mock_start.assert_called_once()
        assert "run-1" in callback._spans
```

## Integration Tests

```python
@pytest.mark.integration
def test_phoenix_tracer_initialization():
    """Test Phoenix tracer initializes correctly."""
    config = PhoenixConfig(
        deployment=PhoenixDeployment.LOCAL,
        port=16006,  # Use different port for testing
    )
    
    tracer = PhoenixTracer(config)
    tracer.initialize()
    
    assert tracer._initialized
    
    tracer.shutdown()


@pytest.mark.integration
def test_openai_instrumentation():
    """Test OpenAI auto-instrumentation."""
    config = PhoenixConfig()
    instrumentor = PhoenixOpenAIInstrumentor(config)
    
    instrumentor.instrument()
    
    # Verify instrumentation is active
    from openai import OpenAI
    
    # Would trace actual OpenAI calls
    
    instrumentor.uninstrument()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_feedback_collection():
    """Test feedback collection end-to-end."""
    config = PhoenixConfig()
    collector = FeedbackCollector(config)
    
    feedback = collector.record_feedback(
        span_id="span-test",
        trace_id="trace-test",
        feedback_type=FeedbackType.THUMBS_UP,
        value=True,
        user_id="user-test",
    )
    
    assert feedback.id is not None
```

## Dependencies

```
arize-phoenix>=4.0.0
openinference-instrumentation-openai>=0.1.0
openinference-instrumentation-llama-index>=0.1.0  # Optional
openinference-instrumentation-langchain>=0.1.0    # Optional
opentelemetry-sdk>=1.22.0
```

## Definition of Done

- [ ] PhoenixConfig with environment variable support
- [ ] PhoenixTracer with OTEL integration
- [ ] LLMSpanAttributes for standard span attributes
- [ ] log_llm_span helper function
- [ ] log_retrieval_span helper function
- [ ] log_embedding_span helper function
- [ ] PhoenixLangChainCallback implemented
- [ ] PhoenixOpenAIInstrumentor implemented
- [ ] PhoenixLlamaIndexInstrumentor implemented
- [ ] FeedbackCollector with Phoenix integration
- [ ] Feedback storage to database
- [ ] ExperimentTracker for A/B tests
- [ ] Deterministic variant assignment
- [ ] Experiment metric logging
- [ ] Kubernetes deployment manifests
- [ ] FastAPI lifespan integration
- [ ] Phoenix UI accessible
- [ ] >90% test coverage
- [ ] Documentation complete
