# US-4.4: Model Gateway

> **Story ID:** US-4.4  
> **Epic:** Orchestrator Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-4.1 (LangGraph Workflow), Epic 5 (LLM Serving)

## User Story

**As a** developer  
**I want** unified LLM access layer  
**So that** I can switch between models easily

## Context

The Model Gateway provides a unified abstraction layer for accessing different LLM providers and models. It implements the OpenAI-compatible API interface to communicate with vLLM-served models, handles retry logic with exponential backoff, implements rate limiting to prevent quota exhaustion, and tracks usage metrics for cost monitoring and optimization. The gateway supports both synchronous and streaming inference modes.

## Technical Requirements

### Directory Structure

```
orchestrator-service/
└── gateway/
    ├── __init__.py
    ├── client.py            # OpenAI-compatible client
    ├── models.py            # Pydantic models
    ├── config.py            # Model configurations
    ├── retry.py             # Retry logic
    ├── rate_limiter.py      # Rate limiting
    ├── usage.py             # Usage tracking
    └── exceptions.py        # Custom exceptions
```

### Data Models

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, AsyncIterator
from enum import Enum
from datetime import datetime
from uuid import UUID, uuid4

class ModelProvider(str, Enum):
    VLLM = "vllm"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"

class ModelConfig(BaseModel):
    """Configuration for a specific model."""
    name: str  # Model identifier (e.g., "meta-llama/Llama-3.1-8B-Instruct")
    provider: ModelProvider = ModelProvider.VLLM
    base_url: str = "http://localhost:8000/v1"
    api_key: Optional[str] = None
    
    # Model capabilities
    max_tokens: int = 8192
    supports_streaming: bool = True
    supports_function_calling: bool = False
    context_window: int = 128000
    
    # Performance settings
    timeout: float = 60.0
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    
    # Rate limiting
    requests_per_minute: Optional[int] = None
    tokens_per_minute: Optional[int] = None

class GatewayConfig(BaseModel):
    """Configuration for the model gateway."""
    # Default model
    default_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    
    # Available models
    models: dict[str, ModelConfig] = {}
    
    # Global settings
    enable_usage_tracking: bool = True
    enable_rate_limiting: bool = True
    enable_retries: bool = True
    
    # Fallback behavior
    fallback_model: Optional[str] = None
    fallback_on_rate_limit: bool = True
    fallback_on_timeout: bool = True
    
    # Connection pooling
    max_connections: int = 100
    connection_timeout: float = 10.0

class ChatMessage(BaseModel):
    """A message in a chat conversation."""
    role: Literal["system", "user", "assistant", "function"]
    content: str
    name: Optional[str] = None  # For function messages
    
class ChatCompletionRequest(BaseModel):
    """Request for chat completion."""
    model: str
    messages: list[ChatMessage]
    
    # Generation parameters
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: Optional[int] = None
    stop: Optional[list[str]] = None
    
    # Streaming
    stream: bool = False
    
    # Advanced settings
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    
    # Request metadata
    request_id: UUID = Field(default_factory=uuid4)
    user_id: Optional[str] = None

class ChatChoice(BaseModel):
    """A single completion choice."""
    index: int
    message: ChatMessage
    finish_reason: Optional[Literal["stop", "length", "content_filter"]] = None

class UsageInfo(BaseModel):
    """Token usage information."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatCompletionResponse(BaseModel):
    """Response from chat completion."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: UsageInfo
    
    # Extended metadata
    request_id: Optional[UUID] = None
    latency_ms: Optional[float] = None

class StreamChunk(BaseModel):
    """A streaming response chunk."""
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[dict]  # {"index": 0, "delta": {"content": "..."}}
    
class UsageRecord(BaseModel):
    """Record of API usage for tracking."""
    timestamp: datetime
    request_id: UUID
    model: str
    user_id: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    success: bool
    error: Optional[str] = None
```

### Model Gateway Implementation

```python
import httpx
import asyncio
from typing import Optional, AsyncIterator
from datetime import datetime
import json
import time
from uuid import uuid4

class ModelGateway:
    """
    Unified gateway for LLM access.
    
    Features:
    - OpenAI-compatible API interface
    - Multiple model/provider support
    - Retry with exponential backoff
    - Rate limiting
    - Usage tracking
    - Streaming support
    """
    
    def __init__(self, config: GatewayConfig = GatewayConfig()):
        self.config = config
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._usage_tracker = UsageTracker() if config.enable_usage_tracking else None
        self._setup_clients()
    
    def _setup_clients(self):
        """Initialize HTTP clients for each model."""
        for name, model_config in self.config.models.items():
            self._clients[name] = httpx.AsyncClient(
                base_url=model_config.base_url,
                timeout=httpx.Timeout(model_config.timeout),
                limits=httpx.Limits(
                    max_connections=self.config.max_connections,
                    max_keepalive_connections=20
                ),
                headers=self._get_headers(model_config)
            )
            
            if self.config.enable_rate_limiting and model_config.requests_per_minute:
                self._rate_limiters[name] = RateLimiter(
                    requests_per_minute=model_config.requests_per_minute,
                    tokens_per_minute=model_config.tokens_per_minute
                )
    
    def _get_headers(self, config: ModelConfig) -> dict:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return headers
    
    async def chat_completion(
        self,
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """
        Execute a chat completion request.
        
        Args:
            request: The completion request
        
        Returns:
            Chat completion response with generated text
        
        Raises:
            ModelNotFoundError: If model is not configured
            RateLimitError: If rate limit exceeded
            ModelTimeoutError: If request times out
            ModelError: For other API errors
        """
        model = request.model or self.config.default_model
        model_config = self._get_model_config(model)
        
        # Check rate limit
        if model in self._rate_limiters:
            await self._rate_limiters[model].acquire()
        
        start_time = time.perf_counter()
        
        try:
            response = await self._execute_with_retry(
                model, model_config, request
            )
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            response.latency_ms = latency_ms
            response.request_id = request.request_id
            
            # Track usage
            if self._usage_tracker:
                await self._usage_tracker.record(
                    UsageRecord(
                        timestamp=datetime.utcnow(),
                        request_id=request.request_id,
                        model=model,
                        user_id=request.user_id,
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        latency_ms=latency_ms,
                        success=True
                    )
                )
            
            return response
            
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            # Track failed request
            if self._usage_tracker:
                await self._usage_tracker.record(
                    UsageRecord(
                        timestamp=datetime.utcnow(),
                        request_id=request.request_id,
                        model=model,
                        user_id=request.user_id,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        latency_ms=latency_ms,
                        success=False,
                        error=str(e)
                    )
                )
            
            # Try fallback if configured
            if self._should_fallback(e):
                return await self._execute_fallback(request, e)
            
            raise
    
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute streaming chat completion.
        
        Args:
            request: The completion request (stream=True is set automatically)
        
        Yields:
            Stream chunks with incremental content
        """
        request.stream = True
        model = request.model or self.config.default_model
        model_config = self._get_model_config(model)
        
        if not model_config.supports_streaming:
            raise StreamingNotSupportedError(f"Model {model} does not support streaming")
        
        # Check rate limit
        if model in self._rate_limiters:
            await self._rate_limiters[model].acquire()
        
        client = self._clients.get(model)
        if not client:
            raise ModelNotFoundError(f"No client for model: {model}")
        
        start_time = time.perf_counter()
        total_tokens = 0
        
        try:
            async with client.stream(
                "POST",
                "/chat/completions",
                json=request.model_dump(exclude_none=True)
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk_data = json.loads(data)
                            chunk = StreamChunk(**chunk_data)
                            
                            # Count tokens for tracking
                            if chunk.choices:
                                delta = chunk.choices[0].get("delta", {})
                                content = delta.get("content", "")
                                total_tokens += len(content.split()) // 4  # Rough estimate
                            
                            yield chunk
                        except json.JSONDecodeError:
                            continue
            
            # Track usage after stream completes
            if self._usage_tracker:
                latency_ms = (time.perf_counter() - start_time) * 1000
                await self._usage_tracker.record(
                    UsageRecord(
                        timestamp=datetime.utcnow(),
                        request_id=request.request_id,
                        model=model,
                        user_id=request.user_id,
                        prompt_tokens=0,  # Not available in streaming
                        completion_tokens=total_tokens,
                        total_tokens=total_tokens,
                        latency_ms=latency_ms,
                        success=True
                    )
                )
                
        except httpx.HTTPStatusError as e:
            raise self._map_http_error(e)
    
    async def _execute_with_retry(
        self,
        model: str,
        config: ModelConfig,
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Execute request with exponential backoff retry."""
        client = self._clients.get(model)
        if not client:
            raise ModelNotFoundError(f"No client for model: {model}")
        
        last_error: Optional[Exception] = None
        
        for attempt in range(config.max_retries + 1):
            try:
                response = await client.post(
                    "/chat/completions",
                    json=request.model_dump(exclude_none=True)
                )
                response.raise_for_status()
                
                data = response.json()
                return ChatCompletionResponse(**data)
                
            except httpx.HTTPStatusError as e:
                last_error = self._map_http_error(e)
                
                # Don't retry on client errors (4xx) except rate limit
                if 400 <= e.response.status_code < 500:
                    if e.response.status_code != 429:
                        raise last_error
                
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = ModelTimeoutError(str(e))
            
            # Calculate backoff
            if attempt < config.max_retries:
                delay = min(
                    config.retry_base_delay * (2 ** attempt),
                    config.retry_max_delay
                )
                # Add jitter
                delay *= (0.5 + 0.5 * (hash(str(request.request_id)) % 100) / 100)
                await asyncio.sleep(delay)
        
        raise last_error or ModelError("Request failed after retries")
    
    def _get_model_config(self, model: str) -> ModelConfig:
        """Get configuration for a model."""
        if model in self.config.models:
            return self.config.models[model]
        
        # Create default config for unknown model
        return ModelConfig(name=model)
    
    def _should_fallback(self, error: Exception) -> bool:
        """Check if should try fallback model."""
        if not self.config.fallback_model:
            return False
        
        if isinstance(error, RateLimitError) and self.config.fallback_on_rate_limit:
            return True
        
        if isinstance(error, ModelTimeoutError) and self.config.fallback_on_timeout:
            return True
        
        return False
    
    async def _execute_fallback(
        self,
        request: ChatCompletionRequest,
        original_error: Exception
    ) -> ChatCompletionResponse:
        """Execute request with fallback model."""
        if not self.config.fallback_model:
            raise original_error
        
        fallback_request = request.model_copy()
        fallback_request.model = self.config.fallback_model
        
        try:
            return await self.chat_completion(fallback_request)
        except Exception:
            # If fallback fails, raise original error
            raise original_error
    
    def _map_http_error(self, error: httpx.HTTPStatusError) -> Exception:
        """Map HTTP errors to gateway exceptions."""
        status = error.response.status_code
        
        if status == 429:
            return RateLimitError("Rate limit exceeded")
        elif status == 401:
            return AuthenticationError("Invalid API key")
        elif status == 404:
            return ModelNotFoundError("Model not found")
        elif status >= 500:
            return ModelError(f"Server error: {status}")
        else:
            return ModelError(f"Request failed: {status}")
    
    async def close(self):
        """Close all HTTP clients."""
        for client in self._clients.values():
            await client.aclose()
    
    async def health_check(self, model: Optional[str] = None) -> dict:
        """Check health of model endpoint(s)."""
        models_to_check = [model] if model else list(self._clients.keys())
        results = {}
        
        for m in models_to_check:
            client = self._clients.get(m)
            if not client:
                results[m] = {"status": "error", "message": "No client configured"}
                continue
            
            try:
                response = await client.get("/health")
                results[m] = {
                    "status": "healthy" if response.is_success else "unhealthy",
                    "latency_ms": response.elapsed.total_seconds() * 1000
                }
            except Exception as e:
                results[m] = {"status": "error", "message": str(e)}
        
        return results
    
    def get_model_info(self, model: str) -> dict:
        """Get information about a configured model."""
        config = self._get_model_config(model)
        return {
            "name": config.name,
            "provider": config.provider.value,
            "max_tokens": config.max_tokens,
            "context_window": config.context_window,
            "supports_streaming": config.supports_streaming,
            "supports_function_calling": config.supports_function_calling
        }
    
    def list_models(self) -> list[str]:
        """List all configured models."""
        return list(self.config.models.keys())
```

### Rate Limiter Implementation

```python
import asyncio
from datetime import datetime, timedelta
from collections import deque
from typing import Optional

class RateLimiter:
    """
    Token bucket rate limiter for API requests.
    
    Supports both request-per-minute and tokens-per-minute limits.
    Uses sliding window for accurate rate limiting.
    """
    
    def __init__(
        self,
        requests_per_minute: Optional[int] = None,
        tokens_per_minute: Optional[int] = None
    ):
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self._request_times: deque = deque()
        self._token_usage: deque = deque()  # (timestamp, tokens)
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 0) -> None:
        """
        Acquire permission to make a request.
        
        Blocks until rate limit allows the request.
        
        Args:
            tokens: Estimated token count for token-based limiting
        
        Raises:
            RateLimitError: If rate limit cannot be satisfied
        """
        async with self._lock:
            now = datetime.utcnow()
            window_start = now - timedelta(minutes=1)
            
            # Clean old entries
            self._clean_old_entries(window_start)
            
            # Check request rate
            if self.requests_per_minute:
                while len(self._request_times) >= self.requests_per_minute:
                    # Wait until oldest request expires
                    oldest = self._request_times[0]
                    wait_time = (oldest + timedelta(minutes=1) - now).total_seconds()
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                    now = datetime.utcnow()
                    window_start = now - timedelta(minutes=1)
                    self._clean_old_entries(window_start)
            
            # Check token rate
            if self.tokens_per_minute and tokens > 0:
                current_tokens = sum(t for _, t in self._token_usage)
                while current_tokens + tokens > self.tokens_per_minute:
                    if not self._token_usage:
                        raise RateLimitError("Token limit too high for single request")
                    
                    oldest_time, _ = self._token_usage[0]
                    wait_time = (oldest_time + timedelta(minutes=1) - now).total_seconds()
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                    now = datetime.utcnow()
                    window_start = now - timedelta(minutes=1)
                    self._clean_old_entries(window_start)
                    current_tokens = sum(t for _, t in self._token_usage)
            
            # Record this request
            self._request_times.append(now)
            if tokens > 0:
                self._token_usage.append((now, tokens))
    
    def _clean_old_entries(self, window_start: datetime):
        """Remove entries older than the sliding window."""
        while self._request_times and self._request_times[0] < window_start:
            self._request_times.popleft()
        
        while self._token_usage and self._token_usage[0][0] < window_start:
            self._token_usage.popleft()
    
    def get_usage(self) -> dict:
        """Get current rate limit usage."""
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=1)
        self._clean_old_entries(window_start)
        
        return {
            "requests_used": len(self._request_times),
            "requests_limit": self.requests_per_minute,
            "tokens_used": sum(t for _, t in self._token_usage),
            "tokens_limit": self.tokens_per_minute
        }
```

### Usage Tracker Implementation

```python
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
import json

class UsageTracker:
    """
    Tracks API usage for cost monitoring and analytics.
    
    Features:
    - Per-model usage tracking
    - Per-user usage tracking
    - Aggregated metrics
    - Redis persistence (optional)
    """
    
    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._local_records: list[UsageRecord] = []
        self._lock = asyncio.Lock()
        
        # In-memory aggregations
        self._model_usage: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "errors": 0, "latency_sum": 0}
        )
        self._user_usage: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0}
        )
    
    async def record(self, record: UsageRecord) -> None:
        """Record a usage event."""
        async with self._lock:
            # Update in-memory aggregations
            model_stats = self._model_usage[record.model]
            model_stats["requests"] += 1
            model_stats["tokens"] += record.total_tokens
            model_stats["latency_sum"] += record.latency_ms
            if not record.success:
                model_stats["errors"] += 1
            
            if record.user_id:
                user_stats = self._user_usage[record.user_id]
                user_stats["requests"] += 1
                user_stats["tokens"] += record.total_tokens
            
            # Store record
            if self._redis:
                await self._store_to_redis(record)
            else:
                self._local_records.append(record)
                # Keep only last 10000 records in memory
                if len(self._local_records) > 10000:
                    self._local_records = self._local_records[-5000:]
    
    async def _store_to_redis(self, record: UsageRecord) -> None:
        """Store usage record to Redis."""
        key = f"usage:{record.timestamp.date().isoformat()}"
        await self._redis.lpush(key, record.model_dump_json())
        await self._redis.expire(key, 86400 * 30)  # 30 day retention
    
    async def get_model_stats(
        self,
        model: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> dict:
        """Get usage statistics for model(s)."""
        if model:
            stats = self._model_usage.get(model, {})
            if stats.get("requests", 0) > 0:
                stats["avg_latency_ms"] = stats["latency_sum"] / stats["requests"]
            return {model: stats}
        
        result = {}
        for m, stats in self._model_usage.items():
            result[m] = dict(stats)
            if stats["requests"] > 0:
                result[m]["avg_latency_ms"] = stats["latency_sum"] / stats["requests"]
        
        return result
    
    async def get_user_stats(self, user_id: str) -> dict:
        """Get usage statistics for a user."""
        return dict(self._user_usage.get(user_id, {}))
    
    async def get_summary(self) -> dict:
        """Get overall usage summary."""
        total_requests = sum(s["requests"] for s in self._model_usage.values())
        total_tokens = sum(s["tokens"] for s in self._model_usage.values())
        total_errors = sum(s["errors"] for s in self._model_usage.values())
        
        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "error_rate": total_errors / total_requests if total_requests > 0 else 0,
            "models": len(self._model_usage),
            "users": len(self._user_usage)
        }
    
    def reset(self):
        """Reset all usage statistics."""
        self._local_records.clear()
        self._model_usage.clear()
        self._user_usage.clear()
```

### Custom Exceptions

```python
class ModelGatewayError(Exception):
    """Base exception for model gateway errors."""
    pass

class ModelNotFoundError(ModelGatewayError):
    """Model is not configured or available."""
    pass

class ModelTimeoutError(ModelGatewayError):
    """Request timed out."""
    pass

class RateLimitError(ModelGatewayError):
    """Rate limit exceeded."""
    pass

class AuthenticationError(ModelGatewayError):
    """Invalid or missing API key."""
    pass

class ModelError(ModelGatewayError):
    """Generic model/API error."""
    pass

class StreamingNotSupportedError(ModelGatewayError):
    """Model does not support streaming."""
    pass
```

### Configuration Example

```yaml
# config/models.yaml
gateway:
  default_model: "meta-llama/Llama-3.1-8B-Instruct"
  fallback_model: "meta-llama/Llama-3.1-8B-Instruct"
  enable_usage_tracking: true
  enable_rate_limiting: true
  max_connections: 100

models:
  meta-llama/Llama-3.1-8B-Instruct:
    provider: vllm
    base_url: "http://vllm-service:8000/v1"
    max_tokens: 8192
    context_window: 128000
    supports_streaming: true
    timeout: 60.0
    max_retries: 3
    requests_per_minute: 60
    
  meta-llama/Llama-3.1-70B-Instruct:
    provider: vllm
    base_url: "http://vllm-70b-service:8000/v1"
    max_tokens: 8192
    context_window: 128000
    supports_streaming: true
    timeout: 120.0
    max_retries: 3
    requests_per_minute: 30
```

### LangGraph Integration

```python
from langgraph.graph import StateGraph

class OrchestratorState(TypedDict):
    query: str
    model: str
    messages: list[ChatMessage]
    response: Optional[str]
    usage: Optional[UsageInfo]
    error: Optional[str]

async def generate_response(state: OrchestratorState) -> OrchestratorState:
    """LangGraph node for LLM generation via gateway."""
    gateway = ModelGateway(config)
    
    request = ChatCompletionRequest(
        model=state["model"],
        messages=state["messages"],
        temperature=0.7,
        max_tokens=1024
    )
    
    try:
        response = await gateway.chat_completion(request)
        
        return {
            **state,
            "response": response.choices[0].message.content,
            "usage": response.usage
        }
    except ModelGatewayError as e:
        return {
            **state,
            "error": str(e)
        }

# Build graph
graph = StateGraph(OrchestratorState)
graph.add_node("generate", generate_response)
```

## Unit Tests

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from uuid import uuid4
import httpx

@pytest.fixture
def gateway_config():
    return GatewayConfig(
        default_model="test-model",
        models={
            "test-model": ModelConfig(
                name="test-model",
                base_url="http://test:8000/v1",
                max_retries=2,
                retry_base_delay=0.1
            )
        },
        enable_rate_limiting=False
    )

@pytest.fixture
def gateway(gateway_config):
    return ModelGateway(gateway_config)

@pytest.fixture
def chat_request():
    return ChatCompletionRequest(
        model="test-model",
        messages=[
            ChatMessage(role="user", content="Hello")
        ]
    )

@pytest.mark.asyncio
async def test_chat_completion_success(gateway, chat_request):
    """Test successful chat completion."""
    mock_response = {
        "id": "test-id",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8
        }
    }
    
    with patch.object(
        gateway._clients["test-model"],
        "post",
        return_value=AsyncMock(
            json=lambda: mock_response,
            raise_for_status=lambda: None,
            is_success=True
        )
    ):
        response = await gateway.chat_completion(chat_request)
    
    assert response.choices[0].message.content == "Hello!"
    assert response.usage.total_tokens == 8

@pytest.mark.asyncio
async def test_retry_on_server_error(gateway, chat_request):
    """Test retry behavior on 5xx errors."""
    mock_error = httpx.HTTPStatusError(
        "Server Error",
        request=MagicMock(),
        response=MagicMock(status_code=500)
    )
    
    call_count = 0
    
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise mock_error
        return AsyncMock(
            json=lambda: {"id": "test", "choices": [], "usage": {}},
            raise_for_status=lambda: None
        )
    
    with patch.object(gateway._clients["test-model"], "post", mock_post):
        # Should succeed after retries
        await gateway.chat_completion(chat_request)
    
    assert call_count == 3

@pytest.mark.asyncio
async def test_no_retry_on_client_error(gateway, chat_request):
    """Test no retry on 4xx errors (except 429)."""
    mock_error = httpx.HTTPStatusError(
        "Bad Request",
        request=MagicMock(),
        response=MagicMock(status_code=400)
    )
    
    with patch.object(
        gateway._clients["test-model"],
        "post",
        side_effect=mock_error
    ):
        with pytest.raises(ModelError):
            await gateway.chat_completion(chat_request)

@pytest.mark.asyncio
async def test_rate_limit_error_triggers_retry(gateway, chat_request):
    """Test retry on rate limit (429) errors."""
    gateway.config.models["test-model"].max_retries = 1
    
    mock_error = httpx.HTTPStatusError(
        "Rate Limited",
        request=MagicMock(),
        response=MagicMock(status_code=429)
    )
    
    call_count = 0
    
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise mock_error
        return AsyncMock(
            json=lambda: {"id": "test", "choices": [], "usage": {}},
            raise_for_status=lambda: None
        )
    
    with patch.object(gateway._clients["test-model"], "post", mock_post):
        await gateway.chat_completion(chat_request)
    
    assert call_count == 2

@pytest.mark.asyncio
async def test_usage_tracking(gateway_config, chat_request):
    """Test that usage is tracked."""
    gateway_config.enable_usage_tracking = True
    gateway = ModelGateway(gateway_config)
    
    mock_response = {
        "id": "test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
    }
    
    with patch.object(
        gateway._clients["test-model"],
        "post",
        return_value=AsyncMock(
            json=lambda: mock_response,
            raise_for_status=lambda: None
        )
    ):
        await gateway.chat_completion(chat_request)
    
    stats = await gateway._usage_tracker.get_model_stats("test-model")
    assert stats["test-model"]["requests"] == 1
    assert stats["test-model"]["tokens"] == 8

def test_model_not_found():
    """Test error when model not configured."""
    gateway = ModelGateway(GatewayConfig())
    request = ChatCompletionRequest(
        model="nonexistent-model",
        messages=[ChatMessage(role="user", content="Hi")]
    )
    
    # Should create default config for unknown model
    config = gateway._get_model_config("nonexistent-model")
    assert config.name == "nonexistent-model"

@pytest.mark.asyncio
async def test_fallback_on_timeout():
    """Test fallback to secondary model on timeout."""
    config = GatewayConfig(
        default_model="primary",
        fallback_model="secondary",
        fallback_on_timeout=True,
        models={
            "primary": ModelConfig(name="primary", base_url="http://primary:8000/v1"),
            "secondary": ModelConfig(name="secondary", base_url="http://secondary:8000/v1")
        }
    )
    gateway = ModelGateway(config)
    
    # Primary times out, secondary succeeds
    primary_calls = 0
    
    async def mock_primary(*args, **kwargs):
        nonlocal primary_calls
        primary_calls += 1
        raise httpx.TimeoutException("Timeout")
    
    async def mock_secondary(*args, **kwargs):
        return AsyncMock(
            json=lambda: {"id": "test", "choices": [], "usage": {}},
            raise_for_status=lambda: None
        )
    
    with patch.object(gateway._clients["primary"], "post", mock_primary):
        with patch.object(gateway._clients["secondary"], "post", mock_secondary):
            request = ChatCompletionRequest(
                model="primary",
                messages=[ChatMessage(role="user", content="Hi")]
            )
            await gateway.chat_completion(request)
    
    assert primary_calls > 0

@pytest.mark.asyncio
async def test_rate_limiter():
    """Test rate limiter functionality."""
    limiter = RateLimiter(requests_per_minute=5)
    
    # Should allow 5 requests immediately
    for _ in range(5):
        await limiter.acquire()
    
    usage = limiter.get_usage()
    assert usage["requests_used"] == 5
    assert usage["requests_limit"] == 5

@pytest.mark.asyncio
async def test_health_check(gateway):
    """Test health check endpoint."""
    with patch.object(
        gateway._clients["test-model"],
        "get",
        return_value=AsyncMock(
            is_success=True,
            elapsed=MagicMock(total_seconds=lambda: 0.1)
        )
    ):
        results = await gateway.health_check()
    
    assert "test-model" in results
    assert results["test-model"]["status"] == "healthy"

def test_list_models(gateway):
    """Test listing configured models."""
    models = gateway.list_models()
    assert "test-model" in models

def test_get_model_info(gateway):
    """Test getting model information."""
    info = gateway.get_model_info("test-model")
    assert info["name"] == "test-model"
    assert "max_tokens" in info
    assert "supports_streaming" in info
```

## Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_integration():
    """Test with real vLLM endpoint."""
    config = GatewayConfig(
        models={
            "llama": ModelConfig(
                name="meta-llama/Llama-3.1-8B-Instruct",
                base_url="http://localhost:8000/v1"
            )
        }
    )
    gateway = ModelGateway(config)
    
    request = ChatCompletionRequest(
        model="llama",
        messages=[ChatMessage(role="user", content="Say hello in one word")],
        max_tokens=10
    )
    
    try:
        response = await gateway.chat_completion(request)
        assert response.choices[0].message.content
        assert response.usage.total_tokens > 0
    finally:
        await gateway.close()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_integration():
    """Test streaming with real vLLM endpoint."""
    config = GatewayConfig(
        models={
            "llama": ModelConfig(
                name="meta-llama/Llama-3.1-8B-Instruct",
                base_url="http://localhost:8000/v1"
            )
        }
    )
    gateway = ModelGateway(config)
    
    request = ChatCompletionRequest(
        model="llama",
        messages=[ChatMessage(role="user", content="Count to 5")],
        max_tokens=50
    )
    
    chunks = []
    try:
        async for chunk in gateway.chat_completion_stream(request):
            chunks.append(chunk)
        
        assert len(chunks) > 0
    finally:
        await gateway.close()
```

## Dependencies

- `httpx>=0.25.0`
- `pydantic>=2.0.0`
- `asyncio`

## Definition of Done

- [ ] ModelGateway supports OpenAI-compatible chat completions
- [ ] Multiple model configurations supported
- [ ] Retry with exponential backoff implemented
- [ ] Jitter added to retry delays
- [ ] Rate limiting enforces requests/tokens per minute
- [ ] Usage tracking records all requests
- [ ] Per-model and per-user usage stats available
- [ ] Streaming responses work correctly
- [ ] Fallback to secondary model on failure
- [ ] Health check endpoint implemented
- [ ] Model info and listing APIs work
- [ ] Custom exceptions for error handling
- [ ] LangGraph integration example provided
- [ ] Configuration via YAML supported
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
