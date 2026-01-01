# US-4.9: Graceful Degradation

> **Story ID:** US-4.9  
> **Epic:** Orchestrator Service  
> **Priority:** Medium  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-4.4 (Model Gateway), US-4.1 (LangGraph Workflow)

## User Story

**As a** system operator  
**I want** the system to degrade gracefully when services fail  
**So that** users receive useful responses even during partial outages

## Context

A production RAG system must handle failures gracefully. When embedding services, rerankers, or LLMs fail, the system should fall back to cached responses, alternative models, or informative error messages rather than failing completely.

## Architecture Reference

- **Framework:** LangGraph state machine (per `docs/architecture.md`)
- **Circuit Breaker:** For external service calls
- **Fallback Strategy:** Cached responses, model tiering, graceful error messages

## Technical Requirements

### Directory Structure

```
orchestrator-service/
├── resilience/
│   ├── __init__.py
│   ├── circuit_breaker.py      # Circuit breaker implementation
│   ├── fallbacks.py            # Fallback handlers
│   ├── degradation_manager.py  # Degradation state management
│   └── cached_responses.py     # Response cache for fallbacks
└── config/
    └── resilience.py           # Resilience configuration
```

### Configuration

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class DegradationLevel(str, Enum):
    NORMAL = "normal"           # All systems operational
    DEGRADED = "degraded"       # Some components failing, using fallbacks
    MINIMAL = "minimal"         # Critical failures, minimal functionality
    MAINTENANCE = "maintenance" # System in maintenance mode

class CircuitBreakerConfig(BaseModel):
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: float = 30.0      # Seconds before half-open
    half_open_max_calls: int = 3        # Calls allowed in half-open
    success_threshold: int = 2          # Successes to close

class FallbackConfig(BaseModel):
    enable_cache_fallback: bool = True
    cache_ttl_seconds: int = 3600
    enable_model_fallback: bool = True
    fallback_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    enable_retrieval_fallback: bool = True
    min_cached_results: int = 3

class ResilienceConfig(BaseModel):
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    fallback: FallbackConfig = FallbackConfig()
    
    # Service-specific configs
    embedding_timeout: float = 5.0
    reranker_timeout: float = 10.0
    llm_timeout: float = 60.0
    retrieval_timeout: float = 5.0
```

### Circuit Breaker Implementation

```python
import asyncio
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, TypeVar, Generic
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject calls
    HALF_OPEN = "half_open" # Testing if service recovered

T = TypeVar('T')

@dataclass
class CircuitStats:
    failures: int = 0
    successes: int = 0
    last_failure_time: Optional[datetime] = None
    half_open_calls: int = 0

class CircuitBreaker(Generic[T]):
    """
    Circuit breaker pattern for external service calls.
    
    States:
    - CLOSED: Normal operation, calls pass through
    - OPEN: Service failing, calls rejected immediately
    - HALF_OPEN: Testing recovery, limited calls allowed
    """
    
    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig,
        fallback: Optional[Callable[..., T]] = None
    ):
        self.name = name
        self.config = config
        self.fallback = fallback
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        return self._state
    
    async def call(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """Execute function through circuit breaker."""
        async with self._lock:
            if self._should_reject():
                logger.warning(f"Circuit {self.name} is open, rejecting call")
                if self.fallback:
                    return await self._execute_fallback(*args, **kwargs)
                raise CircuitBreakerOpenError(self.name)
        
        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except Exception as e:
            await self._record_failure(e)
            if self.fallback:
                return await self._execute_fallback(*args, **kwargs)
            raise
    
    def _should_reject(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return False
        
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._stats.last_failure_time:
                elapsed = (datetime.utcnow() - self._stats.last_failure_time).total_seconds()
                if elapsed >= self.config.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._stats.half_open_calls = 0
                    logger.info(f"Circuit {self.name} entering half-open state")
                    return False
            return True
        
        # HALF_OPEN: Allow limited calls
        if self._stats.half_open_calls >= self.config.half_open_max_calls:
            return True
        
        self._stats.half_open_calls += 1
        return False
    
    async def _record_success(self):
        async with self._lock:
            self._stats.successes += 1
            
            if self._state == CircuitState.HALF_OPEN:
                if self._stats.successes >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._stats = CircuitStats()
                    logger.info(f"Circuit {self.name} closed after recovery")
    
    async def _record_failure(self, error: Exception):
        async with self._lock:
            self._stats.failures += 1
            self._stats.last_failure_time = datetime.utcnow()
            
            logger.warning(f"Circuit {self.name} recorded failure: {error}")
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit {self.name} reopened after half-open failure")
            elif self._stats.failures >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit {self.name} opened after {self._stats.failures} failures")
    
    async def _execute_fallback(self, *args, **kwargs) -> T:
        logger.info(f"Circuit {self.name} executing fallback")
        if asyncio.iscoroutinefunction(self.fallback):
            return await self.fallback(*args, **kwargs)
        return self.fallback(*args, **kwargs)
    
    async def reset(self):
        """Manually reset the circuit breaker."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._stats = CircuitStats()

class CircuitBreakerOpenError(Exception):
    def __init__(self, name: str):
        super().__init__(f"Circuit breaker '{name}' is open")
        self.circuit_name = name
```

### Fallback Handlers

```python
from typing import Optional, Any
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

class FallbackHandlers:
    """Fallback handlers for various service failures."""
    
    def __init__(
        self,
        cache: "ResponseCache",
        config: FallbackConfig
    ):
        self.cache = cache
        self.config = config
    
    async def embedding_fallback(
        self,
        query: str,
        tenant_id: str
    ) -> Optional[list[float]]:
        """
        Fallback when embedding service fails.
        
        Strategy:
        1. Check embedding cache
        2. Use pre-computed query embeddings
        3. Return None (skip semantic search)
        """
        # Try cache first
        cached = await self.cache.get_embedding(query)
        if cached:
            logger.info("Using cached embedding for query")
            return cached
        
        logger.warning("No embedding fallback available, skipping semantic search")
        return None
    
    async def retrieval_fallback(
        self,
        query: str,
        tenant_id: str,
        session_id: Optional[UUID] = None
    ) -> list[dict]:
        """
        Fallback when retrieval service fails.
        
        Strategy:
        1. Return cached results for similar queries
        2. Return frequently accessed documents
        3. Return empty with explanation
        """
        # Try cached results
        cached = await self.cache.get_retrieval_results(query, tenant_id)
        if cached and len(cached) >= self.config.min_cached_results:
            logger.info("Using cached retrieval results")
            return cached
        
        # Return popular documents for tenant
        popular = await self.cache.get_popular_documents(tenant_id)
        if popular:
            logger.info("Using popular documents as fallback")
            return popular
        
        logger.warning("No retrieval fallback available")
        return []
    
    async def reranker_fallback(
        self,
        results: list[dict]
    ) -> list[dict]:
        """
        Fallback when reranker fails.
        
        Strategy: Return results in original order (already ranked by fusion)
        """
        logger.info("Reranker fallback: using fusion scores")
        return results
    
    async def llm_fallback(
        self,
        query: str,
        context: str,
        original_model: str
    ) -> dict:
        """
        Fallback when primary LLM fails.
        
        Strategy:
        1. Try smaller/faster model
        2. Return cached response
        3. Return "unable to respond" message
        """
        # Try fallback model
        if self.config.enable_model_fallback:
            try:
                from services.model_gateway import ModelGateway
                gateway = ModelGateway()
                response = await gateway.generate(
                    model=self.config.fallback_model,
                    messages=[{"role": "user", "content": query}],
                    context=context
                )
                logger.info(f"Using fallback model: {self.config.fallback_model}")
                return {
                    "response": response.content,
                    "model_used": self.config.fallback_model,
                    "is_fallback": True
                }
            except Exception as e:
                logger.error(f"Fallback model also failed: {e}")
        
        # Try cached response
        if self.config.enable_cache_fallback:
            cached = await self.cache.get_response(query)
            if cached:
                logger.info("Using cached response")
                return {
                    "response": cached,
                    "model_used": "cache",
                    "is_fallback": True,
                    "is_cached": True
                }
        
        # Return informative error
        return {
            "response": "I'm sorry, I'm currently unable to process your request. "
                       "Please try again in a few moments.",
            "model_used": "none",
            "is_fallback": True,
            "is_error": True
        }
```

### Degradation Manager

```python
from typing import Optional, Dict
from datetime import datetime
from dataclasses import dataclass
import asyncio
import logging

logger = logging.getLogger(__name__)

@dataclass
class ServiceStatus:
    name: str
    healthy: bool
    last_check: datetime
    consecutive_failures: int = 0
    error_message: Optional[str] = None

class DegradationManager:
    """
    Manages overall system degradation state.
    
    Monitors service health and determines appropriate
    degradation level for the system.
    """
    
    def __init__(
        self,
        circuit_breakers: Dict[str, CircuitBreaker]
    ):
        self.circuits = circuit_breakers
        self._services: Dict[str, ServiceStatus] = {}
        self._level = DegradationLevel.NORMAL
        self._check_interval = 10.0  # seconds
    
    @property
    def level(self) -> DegradationLevel:
        return self._level
    
    def get_service_status(self, name: str) -> Optional[ServiceStatus]:
        return self._services.get(name)
    
    async def update_status(self, name: str, healthy: bool, error: Optional[str] = None):
        """Update status of a service."""
        now = datetime.utcnow()
        
        if name in self._services:
            status = self._services[name]
            if healthy:
                status.healthy = True
                status.consecutive_failures = 0
                status.error_message = None
            else:
                status.healthy = False
                status.consecutive_failures += 1
                status.error_message = error
            status.last_check = now
        else:
            self._services[name] = ServiceStatus(
                name=name,
                healthy=healthy,
                last_check=now,
                error_message=error
            )
        
        await self._recalculate_level()
    
    async def _recalculate_level(self):
        """Recalculate system degradation level based on service health."""
        unhealthy_count = sum(1 for s in self._services.values() if not s.healthy)
        total_services = len(self._services)
        
        if total_services == 0:
            self._level = DegradationLevel.NORMAL
            return
        
        unhealthy_ratio = unhealthy_count / total_services
        
        # Check circuit breaker states
        open_circuits = sum(
            1 for cb in self.circuits.values()
            if cb.state == CircuitState.OPEN
        )
        
        if unhealthy_ratio == 0 and open_circuits == 0:
            self._level = DegradationLevel.NORMAL
        elif unhealthy_ratio < 0.5 or open_circuits < len(self.circuits) / 2:
            self._level = DegradationLevel.DEGRADED
        else:
            self._level = DegradationLevel.MINIMAL
        
        logger.info(f"Degradation level updated to: {self._level}")
    
    def get_status_summary(self) -> dict:
        """Get summary of all service statuses."""
        return {
            "level": self._level,
            "services": {
                name: {
                    "healthy": status.healthy,
                    "last_check": status.last_check.isoformat(),
                    "failures": status.consecutive_failures,
                    "error": status.error_message
                }
                for name, status in self._services.items()
            },
            "circuits": {
                name: cb.state.value
                for name, cb in self.circuits.items()
            }
        }
```

### LangGraph Integration

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional, List

class RAGState(TypedDict):
    query: str
    context: Optional[str]
    response: Optional[str]
    sources: List[dict]
    degradation_level: str
    fallbacks_used: List[str]
    error: Optional[str]

def create_resilient_rag_workflow(
    retrieval_circuit: CircuitBreaker,
    reranker_circuit: CircuitBreaker,
    llm_circuit: CircuitBreaker,
    fallback_handlers: FallbackHandlers,
    degradation_manager: DegradationManager
) -> StateGraph:
    """Create RAG workflow with resilience patterns."""
    
    async def retrieve_with_fallback(state: RAGState) -> RAGState:
        """Retrieve with circuit breaker and fallback."""
        try:
            results = await retrieval_circuit.call(
                retrieve_documents,
                state["query"]
            )
            state["sources"] = results
        except CircuitBreakerOpenError:
            # Use fallback
            results = await fallback_handlers.retrieval_fallback(
                state["query"],
                state.get("tenant_id", "")
            )
            state["sources"] = results
            state["fallbacks_used"].append("retrieval")
        
        return state
    
    async def rerank_with_fallback(state: RAGState) -> RAGState:
        """Rerank with circuit breaker and fallback."""
        if not state["sources"]:
            return state
        
        try:
            reranked = await reranker_circuit.call(
                rerank_results,
                state["query"],
                state["sources"]
            )
            state["sources"] = reranked
        except CircuitBreakerOpenError:
            # Use fallback (keep original order)
            reranked = await fallback_handlers.reranker_fallback(
                state["sources"]
            )
            state["sources"] = reranked
            state["fallbacks_used"].append("reranker")
        
        return state
    
    async def generate_with_fallback(state: RAGState) -> RAGState:
        """Generate with circuit breaker and fallback."""
        context = "\n".join(s["content"] for s in state["sources"])
        
        try:
            response = await llm_circuit.call(
                generate_response,
                state["query"],
                context
            )
            state["response"] = response
        except CircuitBreakerOpenError:
            # Use fallback
            fallback_result = await fallback_handlers.llm_fallback(
                state["query"],
                context,
                "primary"
            )
            state["response"] = fallback_result["response"]
            state["fallbacks_used"].append("llm")
            if fallback_result.get("is_error"):
                state["error"] = "Service temporarily unavailable"
        
        return state
    
    async def check_degradation(state: RAGState) -> RAGState:
        """Update degradation level in state."""
        state["degradation_level"] = degradation_manager.level.value
        return state
    
    # Build workflow
    workflow = StateGraph(RAGState)
    
    workflow.add_node("check_degradation", check_degradation)
    workflow.add_node("retrieve", retrieve_with_fallback)
    workflow.add_node("rerank", rerank_with_fallback)
    workflow.add_node("generate", generate_with_fallback)
    
    workflow.set_entry_point("check_degradation")
    workflow.add_edge("check_degradation", "retrieve")
    workflow.add_edge("retrieve", "rerank")
    workflow.add_edge("rerank", "generate")
    workflow.add_edge("generate", END)
    
    return workflow.compile()
```

### Health Endpoint with Degradation Status

```python
@router.get("/health/detailed")
async def detailed_health(
    degradation_manager: DegradationManager = Depends(get_degradation_manager)
) -> dict:
    """
    Get detailed health status including degradation level.
    
    Returns:
    - Overall degradation level
    - Per-service health status
    - Circuit breaker states
    - Active fallbacks
    """
    return degradation_manager.get_status_summary()
```

## Acceptance Criteria

- [ ] Circuit breaker opens after configured failure threshold
- [ ] Circuit breaker transitions to half-open after timeout
- [ ] Retrieval fallback returns cached or popular documents
- [ ] Reranker fallback returns results in fusion order
- [ ] LLM fallback tries alternative model, then cache, then error message
- [ ] Degradation level accurately reflects system state
- [ ] Health endpoint shows degradation status
- [ ] Fallbacks are logged and tracked in metrics
- [ ] Response includes `is_fallback` flag when fallback used
- [ ] System remains partially functional during component failures

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Test circuit opens after threshold failures."""
    config = CircuitBreakerConfig(failure_threshold=3)
    circuit = CircuitBreaker("test", config)
    
    failing_func = AsyncMock(side_effect=Exception("fail"))
    
    for _ in range(3):
        try:
            await circuit.call(failing_func)
        except:
            pass
    
    assert circuit.state == CircuitState.OPEN

@pytest.mark.asyncio
async def test_fallback_used_when_circuit_open():
    """Test fallback is invoked when circuit is open."""
    fallback = AsyncMock(return_value="fallback_result")
    circuit = CircuitBreaker("test", CircuitBreakerConfig(), fallback=fallback)
    
    # Force open
    circuit._state = CircuitState.OPEN
    circuit._stats.last_failure_time = datetime.utcnow()
    
    result = await circuit.call(AsyncMock())
    
    assert result == "fallback_result"
    fallback.assert_called_once()

@pytest.mark.asyncio
async def test_llm_fallback_tries_alternative_model():
    """Test LLM fallback uses alternative model."""
    handlers = FallbackHandlers(
        cache=AsyncMock(),
        config=FallbackConfig(enable_model_fallback=True)
    )
    
    with patch("services.model_gateway.ModelGateway") as mock_gateway:
        mock_gateway.return_value.generate = AsyncMock(
            return_value=AsyncMock(content="fallback response")
        )
        
        result = await handlers.llm_fallback("query", "context", "primary")
        
        assert result["is_fallback"] is True
        assert "fallback response" in result["response"]

@pytest.mark.asyncio
async def test_degradation_level_updates():
    """Test degradation level changes based on health."""
    manager = DegradationManager({})
    
    # All healthy
    await manager.update_status("service1", healthy=True)
    await manager.update_status("service2", healthy=True)
    assert manager.level == DegradationLevel.NORMAL
    
    # One unhealthy
    await manager.update_status("service1", healthy=False)
    assert manager.level == DegradationLevel.DEGRADED
```

## Definition of Done

- [ ] Circuit breaker pattern implemented
- [ ] Fallback handlers for all external services
- [ ] DegradationManager tracks system state
- [ ] LangGraph workflow uses resilience patterns
- [ ] Health endpoint shows degradation status
- [ ] Metrics track fallback usage
- [ ] Documentation for operating in degraded mode
- [ ] >80% test coverage for resilience code
