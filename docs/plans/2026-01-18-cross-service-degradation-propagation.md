# Cross-Service Degradation Propagation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable the orchestrator to receive and respond to degradation signals from the retrieval service, adjusting prompts and user expectations appropriately.

**Architecture:** The retrieval service already has circuit breakers and degradation detection (US-10.2.1). We need to: (1) populate degradation fields in retrieval API responses, (2) parse these in the orchestrator's retrieval node, (3) adjust prompts based on degradation, (4) include degradation info in streaming events and final responses.

**Tech Stack:** FastAPI, Pydantic v2, Python 3.11+, httpx

---

## Prerequisites

- US-10.2.1 (Retrieval Resilience Layer) is complete
- Retrieval service has `DegradationMode`, `DegradationStatus`, and `RetrievalDegradationManager`
- `RetrieveResponse` schema has `degradation_mode`, `components_used`, `components_skipped` fields (unpopulated)

---

## Task 1: Populate Degradation Info in Retrieval Route

**Files:**
- Modify: `services/retrieval/api/routes/retrieve.py:29-183`
- Test: `services/retrieval/tests/api/test_retrieve_degradation.py` (new)

### Step 1: Write the failing test

Create `services/retrieval/tests/api/test_retrieve_degradation.py`:

```python
"""Tests for degradation info in retrieval responses."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.schemas.retrieve import RetrieveRequest, RetrieveResponse, SearchMode
from resilience.degradation import DegradationMode, DegradationStatus


@pytest.fixture
def mock_degradation_manager():
    """Create a mock degradation manager."""
    manager = MagicMock()
    manager.get_status.return_value = DegradationStatus(
        mode=DegradationMode.HYBRID_FULL,
        qdrant_healthy=True,
        opensearch_healthy=True,
        reranker_healthy=True,
        components_available=["qdrant", "opensearch", "reranker"],
        components_unavailable=[],
    )
    return manager


class TestRetrieveDegradationInfo:
    """Tests for degradation info in retrieve endpoint."""

    @pytest.mark.asyncio
    async def test_retrieve_includes_degradation_mode_normal(
        self, test_client, mock_degradation_manager
    ):
        """Retrieve should include normal degradation mode when all healthy."""
        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=mock_degradation_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "hybrid_full"
        assert "qdrant" in data["components_used"]
        assert "opensearch" in data["components_used"]
        assert data["components_skipped"] == []

    @pytest.mark.asyncio
    async def test_retrieve_includes_degradation_mode_semantic_only(
        self, test_client
    ):
        """Retrieve should show semantic_only when opensearch is down."""
        degraded_manager = MagicMock()
        degraded_manager.get_status.return_value = DegradationStatus(
            mode=DegradationMode.SEMANTIC_ONLY,
            qdrant_healthy=True,
            opensearch_healthy=False,
            reranker_healthy=True,
            components_available=["qdrant", "reranker"],
            components_unavailable=["opensearch"],
        )

        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=degraded_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "semantic_only"
        assert "qdrant" in data["components_used"]
        assert "opensearch" in data["components_skipped"]

    @pytest.mark.asyncio
    async def test_retrieve_includes_degradation_mode_minimal(
        self, test_client
    ):
        """Retrieve should show minimal when multiple components down."""
        minimal_manager = MagicMock()
        minimal_manager.get_status.return_value = DegradationStatus(
            mode=DegradationMode.MINIMAL,
            qdrant_healthy=True,
            opensearch_healthy=False,
            reranker_healthy=False,
            components_available=["qdrant"],
            components_unavailable=["opensearch", "reranker"],
        )

        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=minimal_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "minimal"
        assert data["components_used"] == ["qdrant"]
        assert "opensearch" in data["components_skipped"]
        assert "reranker" in data["components_skipped"]
```

### Step 2: Run test to verify it fails

```bash
cd services/retrieval && python -m pytest tests/api/test_retrieve_degradation.py -v
```

Expected: FAIL - `get_degradation_manager` not imported or used in retrieve route

### Step 3: Update the retrieve route to include degradation info

Modify `services/retrieval/api/routes/retrieve.py`:

At the top, add import:
```python
from resilience.degradation import get_degradation_manager
```

Before the `return RetrieveResponse(...)` statement (around line 160), add:
```python
    # Get degradation status
    degradation_manager = get_degradation_manager()
    degradation_status = degradation_manager.get_status()
```

Update the return statement to include the degradation fields:
```python
    return RetrieveResponse(
        results=response_results,
        total_results=len(response_results),
        query=body.query,
        mode=body.mode,
        metrics=SearchMetrics(
            query_preprocessing_ms=preprocess_time,
            embedding_ms=processed.processing_time_ms,
            semantic_search_ms=semantic_time,
            keyword_search_ms=keyword_time,
            fusion_ms=fusion_time,
            rerank_ms=rerank_time,
            total_ms=total_time,
            semantic_results_count=semantic_count,
            keyword_results_count=keyword_count,
            fused_results_count=fused_count,
            final_results_count=len(response_results),
        ),
        query_id=query_id,
        processed_at=datetime.now(tz=UTC),
        # Degradation info (US-10.2.2)
        degradation_mode=degradation_status.mode.value,
        components_used=degradation_status.components_available,
        components_skipped=degradation_status.components_unavailable,
    )
```

### Step 4: Run test to verify it passes

```bash
cd services/retrieval && python -m pytest tests/api/test_retrieve_degradation.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/retrieval/api/routes/retrieve.py services/retrieval/tests/api/test_retrieve_degradation.py
git commit -m "$(cat <<'EOF'
feat(retrieval): populate degradation info in retrieve response

Add degradation_mode, components_used, and components_skipped to
retrieval API responses based on circuit breaker states.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add Retrieval Quality Fields to Orchestrator State

**Files:**
- Modify: `services/orchestrator/workflow/state.py:10-64`
- Test: `services/orchestrator/tests/workflow/test_state_retrieval_quality.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/workflow/test_state_retrieval_quality.py`:

```python
"""Tests for retrieval quality fields in RAGState."""

import pytest
from workflow.state import RAGState, create_initial_state


class TestRAGStateRetrievalQuality:
    """Tests for retrieval quality tracking in state."""

    def test_state_has_retrieval_quality_field(self):
        """RAGState should have retrieval_quality field."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test",
            "retrieval_quality": {
                "degradation_level": "normal",
                "mode": "hybrid_full",
                "components_used": ["qdrant", "opensearch", "reranker"],
                "components_skipped": [],
            },
        }
        assert state["retrieval_quality"]["degradation_level"] == "normal"

    def test_state_has_context_quality_field(self):
        """RAGState should have context_quality field."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test",
            "context_quality": "full",
        }
        assert state["context_quality"] == "full"

    def test_context_quality_values(self):
        """context_quality should accept full, partial, minimal."""
        for quality in ["full", "partial", "minimal"]:
            state: RAGState = {
                "request_id": "test-123",
                "query": "test",
                "context_quality": quality,
            }
            assert state["context_quality"] == quality

    def test_create_initial_state_defaults(self):
        """create_initial_state should set default retrieval quality."""
        state = create_initial_state(
            request_id="test-123",
            query="test query",
        )
        # Should not have retrieval_quality until retrieval runs
        assert "retrieval_quality" not in state or state.get("retrieval_quality") is None
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/workflow/test_state_retrieval_quality.py -v
```

Expected: FAIL - `retrieval_quality` and `context_quality` not in RAGState type hints

### Step 3: Add retrieval quality fields to RAGState

Modify `services/orchestrator/workflow/state.py`. Add after the "Retrieval Fields" section:

```python
    # =========================================================================
    # Retrieval Quality Fields (US-10.2.2)
    # =========================================================================
    retrieval_quality: dict  # {degradation_level, mode, components_used, components_skipped}
    context_quality: str  # "full", "partial", "minimal"
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/workflow/test_state_retrieval_quality.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/workflow/state.py services/orchestrator/tests/workflow/test_state_retrieval_quality.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add retrieval quality fields to RAGState

Add retrieval_quality and context_quality fields for tracking
degradation information from retrieval service.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Parse Degradation Info in Retrieval Node

**Files:**
- Modify: `services/orchestrator/workflow/nodes/retrieval.py:65-152`
- Test: `services/orchestrator/tests/workflow/test_retrieval_node_degradation.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/workflow/test_retrieval_node_degradation.py`:

```python
"""Tests for degradation handling in retrieval node."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from workflow.nodes.retrieval import retrieval_node
from workflow.state import RAGState


@pytest.fixture
def mock_httpx_response_normal():
    """Mock response with normal degradation."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.9, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "hybrid_full",
        "components_used": ["qdrant", "opensearch", "reranker"],
        "components_skipped": [],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_degraded():
    """Mock response with degraded mode."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.8, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "semantic_only",
        "components_used": ["qdrant", "reranker"],
        "components_skipped": ["opensearch"],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_minimal():
    """Mock response with minimal mode."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.7, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "minimal",
        "components_used": ["qdrant"],
        "components_skipped": ["opensearch", "reranker"],
    }
    response.raise_for_status = MagicMock()
    return response


class TestRetrievalNodeDegradation:
    """Tests for degradation handling in retrieval node."""

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_normal_degradation(self, mock_httpx_response_normal):
        """Retrieval node should parse normal degradation info."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_httpx_response_normal
            )

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "normal"
        assert result["retrieval_quality"]["mode"] == "hybrid_full"
        assert "qdrant" in result["retrieval_quality"]["components_used"]
        assert result["context_quality"] == "full"
        assert "retrieval:" not in str(result.get("fallbacks_used", []))

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_degraded_mode(self, mock_httpx_response_degraded):
        """Retrieval node should parse degraded mode and track fallback."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_httpx_response_degraded
            )

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "degraded"
        assert result["retrieval_quality"]["mode"] == "semantic_only"
        assert "opensearch" in result["retrieval_quality"]["components_skipped"]
        assert result["context_quality"] == "partial"
        assert "retrieval:semantic_only" in result["fallbacks_used"]

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_minimal_mode(self, mock_httpx_response_minimal):
        """Retrieval node should parse minimal mode."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_httpx_response_minimal
            )

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "minimal"
        assert result["context_quality"] == "minimal"
        assert "retrieval:minimal" in result["fallbacks_used"]
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/workflow/test_retrieval_node_degradation.py -v
```

Expected: FAIL - retrieval_quality not set in returned state

### Step 3: Update retrieval node to parse degradation info

Modify `services/orchestrator/workflow/nodes/retrieval.py`. After `result = response.json()` (around line 114), add:

```python
            # Parse degradation info (US-10.2.2)
            degradation_mode = result.get("degradation_mode", "hybrid_full")
            components_used = result.get("components_used", [])
            components_skipped = result.get("components_skipped", [])

            # Determine degradation level
            if degradation_mode == "hybrid_full":
                degradation_level = "normal"
            elif degradation_mode == "minimal":
                degradation_level = "minimal"
            else:
                degradation_level = "degraded"

            # Build retrieval quality info
            retrieval_quality = {
                "degradation_level": degradation_level,
                "mode": degradation_mode,
                "components_used": components_used,
                "components_skipped": components_skipped,
            }

            # Set context quality based on degradation
            if degradation_level == "minimal":
                context_quality = "minimal"
            elif degradation_level == "degraded":
                context_quality = "partial"
            else:
                context_quality = "full"

            # Track degradation as fallback if not normal
            if degradation_level != "normal":
                fallbacks_used.append(f"retrieval:{degradation_mode}")
```

Update the return statement to include the new fields:

```python
    # Set default retrieval quality if retrieval failed
    if "retrieval_quality" not in locals():
        retrieval_quality = {
            "degradation_level": "unknown",
            "mode": "unknown",
            "components_used": [],
            "components_skipped": [],
        }
        context_quality = "minimal"

    return {
        **state,
        "documents": documents,
        "context": context,
        "timing": timing,
        "fallbacks_used": fallbacks_used,
        "retrieval_quality": retrieval_quality,
        "context_quality": context_quality,
    }
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/workflow/test_retrieval_node_degradation.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/workflow/nodes/retrieval.py services/orchestrator/tests/workflow/test_retrieval_node_degradation.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): parse degradation info in retrieval node

Extract degradation_mode, components_used, components_skipped from
retrieval response and store in RAGState for downstream processing.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add Degradation Disclaimers to Prompt Building

**Files:**
- Modify: `services/orchestrator/workflow/nodes/prompt_building.py:1-106`
- Test: `services/orchestrator/tests/workflow/test_prompt_degradation.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/workflow/test_prompt_degradation.py`:

```python
"""Tests for degradation disclaimers in prompt building."""

import pytest
from workflow.nodes.prompt_building import prompt_building_node, DEGRADATION_DISCLAIMERS
from workflow.state import RAGState


class TestPromptDegradationDisclaimers:
    """Tests for degradation disclaimers in prompts."""

    def test_degradation_disclaimers_defined(self):
        """DEGRADATION_DISCLAIMERS should be defined for all modes."""
        assert "semantic_only" in DEGRADATION_DISCLAIMERS
        assert "keyword_only" in DEGRADATION_DISCLAIMERS
        assert "hybrid_no_rerank" in DEGRADATION_DISCLAIMERS
        assert "minimal" in DEGRADATION_DISCLAIMERS

    @pytest.mark.asyncio
    async def test_prompt_no_disclaimer_when_normal(self):
        """Prompt should have no disclaimer when degradation is normal."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test query",
            "context": "Some context here",
            "strategy": "simple",
            "timing": {},
            "retrieval_quality": {
                "degradation_level": "normal",
                "mode": "hybrid_full",
                "components_used": ["qdrant", "opensearch"],
                "components_skipped": [],
            },
        }

        result = await prompt_building_node(state)

        system_message = result["messages"][0]["content"]
        # Should not contain any disclaimer keywords
        assert "unavailable" not in system_message.lower()
        assert "degraded" not in system_message.lower()
        assert "limited" not in system_message.lower()

    @pytest.mark.asyncio
    async def test_prompt_includes_semantic_only_disclaimer(self):
        """Prompt should include disclaimer for semantic_only mode."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test query",
            "context": "Some context here",
            "strategy": "simple",
            "timing": {},
            "retrieval_quality": {
                "degradation_level": "degraded",
                "mode": "semantic_only",
                "components_used": ["qdrant"],
                "components_skipped": ["opensearch"],
            },
        }

        result = await prompt_building_node(state)

        system_message = result["messages"][0]["content"]
        assert "keyword" in system_message.lower()
        assert "unavailable" in system_message.lower()

    @pytest.mark.asyncio
    async def test_prompt_includes_keyword_only_disclaimer(self):
        """Prompt should include disclaimer for keyword_only mode."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test query",
            "context": "Some context here",
            "strategy": "simple",
            "timing": {},
            "retrieval_quality": {
                "degradation_level": "degraded",
                "mode": "keyword_only",
                "components_used": ["opensearch"],
                "components_skipped": ["qdrant"],
            },
        }

        result = await prompt_building_node(state)

        system_message = result["messages"][0]["content"]
        assert "semantic" in system_message.lower()
        assert "unavailable" in system_message.lower()

    @pytest.mark.asyncio
    async def test_prompt_includes_minimal_disclaimer(self):
        """Prompt should include strong disclaimer for minimal mode."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test query",
            "context": "Some context here",
            "strategy": "simple",
            "timing": {},
            "retrieval_quality": {
                "degradation_level": "minimal",
                "mode": "minimal",
                "components_used": ["qdrant"],
                "components_skipped": ["opensearch", "reranker"],
            },
        }

        result = await prompt_building_node(state)

        system_message = result["messages"][0]["content"]
        assert "significantly degraded" in system_message.lower() or "incomplete" in system_message.lower()
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/workflow/test_prompt_degradation.py -v
```

Expected: FAIL - `DEGRADATION_DISCLAIMERS` not defined

### Step 3: Add degradation disclaimers to prompt building

Modify `services/orchestrator/workflow/nodes/prompt_building.py`. Add after the template definitions:

```python
# Degradation disclaimers (US-10.2.2)
DEGRADATION_DISCLAIMERS = {
    "semantic_only": (
        "\n\nNote: The search results below were obtained using semantic similarity only. "
        "Keyword matching was unavailable, so some exact term matches may be missing."
    ),
    "keyword_only": (
        "\n\nNote: The search results below were obtained using keyword matching only. "
        "Semantic search was unavailable, so conceptually similar content may be missing."
    ),
    "hybrid_no_rerank": (
        "\n\nNote: Search results were not reranked for relevance. "
        "Results may not be in optimal order."
    ),
    "minimal": (
        "\n\nIMPORTANT: Search capabilities are significantly degraded. "
        "The context provided may be incomplete or less relevant than usual. "
        "Please indicate if the available information is insufficient to answer."
    ),
}
```

Update `_build_messages` to accept and use degradation info:

```python
def _build_messages(
    query: str,
    context: str,
    strategy: str,
    history: list[dict] | None = None,
    retrieval_quality: dict | None = None,
) -> list[dict]:
    """
    Build the message list for LLM generation.

    Args:
        query: User's query
        context: Retrieved context (may be empty)
        strategy: Routing strategy
        history: Optional conversation history
        retrieval_quality: Optional retrieval quality info for degradation disclaimers

    Returns:
        List of message dictionaries for LLM
    """
    # Build system prompt with optional degradation disclaimer
    system_content = SYSTEM_PROMPT

    if retrieval_quality:
        degradation_level = retrieval_quality.get("degradation_level", "normal")
        mode = retrieval_quality.get("mode", "hybrid_full")

        if degradation_level != "normal" and mode in DEGRADATION_DISCLAIMERS:
            system_content += DEGRADATION_DISCLAIMERS[mode]

    messages = [{"role": "system", "content": system_content}]

    # Add conversation history if available
    if history:
        for msg in history:
            messages.append(msg)

    # Build user message based on strategy and context
    if strategy == "no_retrieval" or not context:
        user_content = NO_CONTEXT_PROMPT_TEMPLATE.format(query=query)
    else:
        user_content = RAG_PROMPT_TEMPLATE.format(context=context, query=query)

    messages.append({"role": "user", "content": user_content})

    return messages
```

Update `prompt_building_node` to pass retrieval_quality:

```python
async def prompt_building_node(state: "RAGState") -> "RAGState":
    """..."""
    start = time.time()

    query = state.get("query", "")
    context = state.get("context", "")
    strategy = state.get("strategy", "simple")
    timing = dict(state.get("timing", {}))
    retrieval_quality = state.get("retrieval_quality")

    # Note: History handling would come from session/memory in production
    history: list[dict] = []

    # Build messages for LLM
    messages = _build_messages(query, context, strategy, history, retrieval_quality)

    timing["prompt_building"] = (time.time() - start) * 1000

    return {
        **state,
        "messages": messages,
        "timing": timing,
    }
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/workflow/test_prompt_degradation.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/workflow/nodes/prompt_building.py services/orchestrator/tests/workflow/test_prompt_degradation.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add degradation disclaimers to prompts

When retrieval service is degraded, include contextual warnings in
the system prompt to set appropriate expectations for the LLM.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add Degradation Info to Streaming Events

**Files:**
- Modify: `services/orchestrator/streaming/models.py:32-43` (StartEventData)
- Modify: `services/orchestrator/streaming/models.py:67-79` (DoneEventData)
- Modify: `services/orchestrator/streaming/manager.py:64-181` (stream_response)
- Test: `services/orchestrator/tests/streaming/test_degradation_events.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/streaming/test_degradation_events.py`:

```python
"""Tests for degradation info in streaming events."""

import pytest
from streaming.models import StartEventData, DoneEventData, StreamEventType


class TestStreamingDegradationEvents:
    """Tests for degradation info in streaming events."""

    def test_start_event_has_degradation_field(self):
        """StartEventData should have optional degradation field."""
        event = StartEventData(
            request_id="test-123",
            model="test-model",
            session_id=None,
            degradation=None,
        )
        assert event.degradation is None

    def test_start_event_with_degradation_info(self):
        """StartEventData should accept degradation info."""
        event = StartEventData(
            request_id="test-123",
            model="test-model",
            session_id=None,
            degradation={
                "level": "degraded",
                "mode": "semantic_only",
                "message": "Keyword search unavailable",
            },
        )
        assert event.degradation["level"] == "degraded"
        assert event.degradation["mode"] == "semantic_only"

    def test_done_event_has_quality_fields(self):
        """DoneEventData should have context_quality and retrieval_mode."""
        event = DoneEventData(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
            context_quality="partial",
            retrieval_mode="semantic_only",
        )
        assert event.context_quality == "partial"
        assert event.retrieval_mode == "semantic_only"

    def test_done_event_quality_defaults(self):
        """DoneEventData should have sensible defaults for quality fields."""
        event = DoneEventData(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
        )
        assert event.context_quality == "full"
        assert event.retrieval_mode == "hybrid_full"
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/streaming/test_degradation_events.py -v
```

Expected: FAIL - `degradation` not in StartEventData, quality fields not in DoneEventData

### Step 3: Update streaming event models

Modify `services/orchestrator/streaming/models.py`:

Update `StartEventData`:
```python
class StartEventData(BaseModel):
    """Data payload for stream start events.

    Attributes:
        request_id: Unique identifier for this request.
        model: The model being used for generation.
        session_id: Optional session identifier for conversation tracking.
        degradation: Optional degradation info if service is degraded.
    """

    request_id: str
    model: str
    session_id: str | None = None
    degradation: dict | None = None  # {level, mode, message}
```

Update `DoneEventData`:
```python
class DoneEventData(BaseModel):
    """Data payload for stream completion events.

    Attributes:
        request_id: Unique identifier for the completed request.
        usage: Token usage statistics with prompt_tokens,
            completion_tokens, and total_tokens.
        latency_ms: Total response latency in milliseconds.
        context_quality: Quality of retrieved context (full, partial, minimal).
        retrieval_mode: The retrieval mode used (hybrid_full, semantic_only, etc).
    """

    request_id: str
    usage: dict[str, int]
    latency_ms: float
    context_quality: str = "full"
    retrieval_mode: str = "hybrid_full"
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/streaming/test_degradation_events.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/streaming/models.py services/orchestrator/tests/streaming/test_degradation_events.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add degradation fields to streaming event models

Add degradation info to StartEventData and quality fields to
DoneEventData for frontend degradation awareness.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update StreamManager to Include Degradation Info

**Files:**
- Modify: `services/orchestrator/streaming/manager.py:64-181`
- Test: `services/orchestrator/tests/streaming/test_manager_degradation.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/streaming/test_manager_degradation.py`:

```python
"""Tests for degradation info in StreamManager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from streaming.manager import StreamManager
from streaming.models import StreamEventType


@pytest.fixture
def mock_gateway():
    """Create a mock model gateway."""
    gateway = MagicMock()
    gateway.chat_completion_stream = AsyncMock(return_value=iter(["Hello", " world"]))
    return gateway


class TestStreamManagerDegradation:
    """Tests for degradation handling in StreamManager."""

    @pytest.mark.asyncio
    async def test_stream_response_includes_degradation_in_start(self, mock_gateway):
        """Start event should include degradation info when provided."""
        manager = StreamManager(gateway=mock_gateway)
        retrieval_quality = {
            "degradation_level": "degraded",
            "mode": "semantic_only",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch"],
        }

        # Make gateway return async iterator
        async def mock_stream(*args, **kwargs):
            for token in ["Hello", " world"]:
                yield token

        mock_gateway.chat_completion_stream = mock_stream

        events = []
        async for event in manager.stream_response(
            request_id="test-123",
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
            retrieval_quality=retrieval_quality,
        ):
            events.append(event)

        start_event = events[0]
        assert start_event.event_type == StreamEventType.START
        assert start_event.data.degradation is not None
        assert start_event.data.degradation["level"] == "degraded"

    @pytest.mark.asyncio
    async def test_stream_response_includes_quality_in_done(self, mock_gateway):
        """Done event should include context quality and retrieval mode."""
        manager = StreamManager(gateway=mock_gateway)
        retrieval_quality = {
            "degradation_level": "degraded",
            "mode": "semantic_only",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch"],
        }

        async def mock_stream(*args, **kwargs):
            for token in ["Hello"]:
                yield token

        mock_gateway.chat_completion_stream = mock_stream

        events = []
        async for event in manager.stream_response(
            request_id="test-123",
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
            retrieval_quality=retrieval_quality,
        ):
            events.append(event)

        done_event = [e for e in events if e.event_type == StreamEventType.DONE][0]
        assert done_event.data.context_quality == "partial"
        assert done_event.data.retrieval_mode == "semantic_only"

    @pytest.mark.asyncio
    async def test_stream_response_no_degradation_when_normal(self, mock_gateway):
        """Start event should have no degradation info when normal."""
        manager = StreamManager(gateway=mock_gateway)
        retrieval_quality = {
            "degradation_level": "normal",
            "mode": "hybrid_full",
            "components_used": ["qdrant", "opensearch"],
            "components_skipped": [],
        }

        async def mock_stream(*args, **kwargs):
            for token in ["Hello"]:
                yield token

        mock_gateway.chat_completion_stream = mock_stream

        events = []
        async for event in manager.stream_response(
            request_id="test-123",
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
            retrieval_quality=retrieval_quality,
        ):
            events.append(event)

        start_event = events[0]
        assert start_event.data.degradation is None
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/streaming/test_manager_degradation.py -v
```

Expected: FAIL - `retrieval_quality` parameter not accepted

### Step 3: Update StreamManager to accept and propagate degradation info

Modify `services/orchestrator/streaming/manager.py`. Update `stream_response` signature:

```python
    async def stream_response(
        self,
        request_id: str,
        model: str,
        messages: list[dict[str, Any]],
        session_id: str | None = None,
        documents: list[dict[str, Any]] | None = None,
        gateway: ModelGateway | None = None,
        retrieval_quality: dict[str, Any] | None = None,  # NEW
    ) -> AsyncGenerator[StreamEvent, None]:
```

Update `_create_start_event`:
```python
    def _create_start_event(
        self,
        request_id: str,
        model: str,
        session_id: str | None,
        retrieval_quality: dict[str, Any] | None = None,
    ) -> StreamEvent:
        """Create a start event with optional degradation info."""
        # Build degradation info for start event
        degradation = None
        if retrieval_quality and retrieval_quality.get("degradation_level") != "normal":
            mode = retrieval_quality.get("mode", "unknown")
            messages = {
                "semantic_only": "Using semantic search only",
                "keyword_only": "Using keyword search only",
                "hybrid_no_rerank": "Results may be less precisely ordered",
                "minimal": "Search capabilities limited",
            }
            degradation = {
                "level": retrieval_quality.get("degradation_level"),
                "mode": mode,
                "message": messages.get(mode, ""),
            }

        return StreamEvent.start(request_id, model, session_id, degradation)
```

Update `_create_done_event`:
```python
    def _create_done_event(
        self,
        request_id: str,
        usage: dict[str, int],
        latency_ms: float,
        retrieval_quality: dict[str, Any] | None = None,
    ) -> StreamEvent:
        """Create a done event with quality info."""
        context_quality = "full"
        retrieval_mode = "hybrid_full"

        if retrieval_quality:
            level = retrieval_quality.get("degradation_level", "normal")
            if level == "minimal":
                context_quality = "minimal"
            elif level == "degraded":
                context_quality = "partial"
            retrieval_mode = retrieval_quality.get("mode", "hybrid_full")

        return StreamEvent.done(request_id, usage, latency_ms, context_quality, retrieval_mode)
```

Update `StreamEvent.start` and `StreamEvent.done` class methods in models.py:
```python
    @classmethod
    def start(
        cls,
        request_id: str,
        model: str,
        session_id: str | None = None,
        degradation: dict | None = None,
    ) -> "StreamEvent":
        return cls(
            event_type=StreamEventType.START,
            data=StartEventData(
                request_id=request_id,
                model=model,
                session_id=session_id,
                degradation=degradation,
            ),
        )

    @classmethod
    def done(
        cls,
        request_id: str,
        usage: dict[str, int],
        latency_ms: float,
        context_quality: str = "full",
        retrieval_mode: str = "hybrid_full",
    ) -> "StreamEvent":
        return cls(
            event_type=StreamEventType.DONE,
            data=DoneEventData(
                request_id=request_id,
                usage=usage,
                latency_ms=latency_ms,
                context_quality=context_quality,
                retrieval_mode=retrieval_mode,
            ),
        )
```

Update the calls in `stream_response`:
```python
        # Emit start event with degradation info
        yield self._create_start_event(request_id, model, session_id, retrieval_quality)

        # ... (streaming code) ...

        # Emit done event with quality info
        latency_ms = (time.perf_counter() - start_time) * 1000
        yield self._create_done_event(request_id, usage, latency_ms, retrieval_quality)
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/streaming/test_manager_degradation.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/streaming/manager.py services/orchestrator/streaming/models.py services/orchestrator/tests/streaming/test_manager_degradation.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): include degradation info in streaming events

StreamManager now accepts retrieval_quality and includes degradation
info in start events and quality info in done events.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add Quality Metadata to QueryResponse

**Files:**
- Modify: `services/orchestrator/api/models/responses.py:40-73`
- Test: `services/orchestrator/tests/api/test_response_metadata.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/api/test_response_metadata.py`:

```python
"""Tests for quality metadata in query response."""

import pytest
from uuid import uuid4
from api.models.responses import QueryResponse, UsageInfo, SourceDocument


class TestQueryResponseMetadata:
    """Tests for quality metadata fields in QueryResponse."""

    def test_query_response_has_retrieval_mode(self):
        """QueryResponse should have retrieval_mode field."""
        response = QueryResponse(
            request_id="test-123",
            response="Test response",
            sources=[],
            model="test-model",
            retrieval_mode="semantic_only",
        )
        assert response.retrieval_mode == "semantic_only"

    def test_query_response_has_context_quality(self):
        """QueryResponse should have context_quality field."""
        response = QueryResponse(
            request_id="test-123",
            response="Test response",
            sources=[],
            model="test-model",
            context_quality="partial",
        )
        assert response.context_quality == "partial"

    def test_query_response_has_components_available(self):
        """QueryResponse should have components_available dict."""
        response = QueryResponse(
            request_id="test-123",
            response="Test response",
            sources=[],
            model="test-model",
            components_available={
                "semantic_search": True,
                "keyword_search": False,
                "reranking": True,
            },
        )
        assert response.components_available["semantic_search"] is True
        assert response.components_available["keyword_search"] is False

    def test_query_response_defaults(self):
        """QueryResponse should have sensible defaults for quality fields."""
        response = QueryResponse(
            request_id="test-123",
            response="Test response",
            sources=[],
            model="test-model",
        )
        assert response.retrieval_mode is None  # or default value
        assert response.context_quality is None  # or default value
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/api/test_response_metadata.py -v
```

Expected: FAIL - fields not defined in QueryResponse

### Step 3: Add quality metadata fields to QueryResponse

Modify `services/orchestrator/api/models/responses.py`:

```python
class QueryResponse(BaseModel):
    """Response model for synchronous RAG query.

    Attributes:
        request_id: Unique identifier for this request.
        response: The generated response text.
        sources: List of source documents used.
        session_id: Session ID if conversation tracking is enabled.
        model: The model used for generation.
        usage: Token usage statistics.
        latency_ms: Response latency in milliseconds.
        strategy_used: The retrieval strategy used (simple, rerank, etc.).
        retrieval_mode: The retrieval mode used (hybrid_full, semantic_only, etc).
        context_quality: Quality of retrieved context (full, partial, minimal).
        components_available: Which retrieval components were available.
        fallbacks_used: List of fallback strategies that were applied.
    """

    request_id: str = Field(..., description="Unique request identifier")
    response: str = Field(..., description="Generated response text")
    sources: list[SourceDocument] = Field(
        default_factory=list,
        description="Source documents used in response",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Session ID for conversation tracking",
    )
    model: str = Field(..., description="Model used for generation")
    usage: UsageInfo = Field(
        default_factory=UsageInfo,
        description="Token usage statistics",
    )
    latency_ms: float = Field(default=0.0, description="Response latency in milliseconds")
    strategy_used: str | None = Field(
        default=None,
        description="Retrieval strategy used",
    )
    # Quality metadata (US-10.2.2)
    retrieval_mode: str | None = Field(
        default=None,
        description="Retrieval mode used (hybrid_full, semantic_only, etc)",
    )
    context_quality: str | None = Field(
        default=None,
        description="Quality of retrieved context (full, partial, minimal)",
    )
    components_available: dict[str, bool] | None = Field(
        default=None,
        description="Which retrieval components were available",
    )
    fallbacks_used: list[str] = Field(
        default_factory=list,
        description="List of fallback strategies applied",
    )
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/api/test_response_metadata.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/api/models/responses.py services/orchestrator/tests/api/test_response_metadata.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add quality metadata to QueryResponse

Add retrieval_mode, context_quality, components_available, and
fallbacks_used fields to QueryResponse for frontend awareness.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire Up Quality Metadata in Query Route

**Files:**
- Modify: `services/orchestrator/api/routes/query.py` (wherever QueryResponse is built)
- Test: `services/orchestrator/tests/api/test_query_route_degradation.py` (new)

### Step 1: Write the failing test

Create `services/orchestrator/tests/api/test_query_route_degradation.py`:

```python
"""Tests for degradation info in query route responses."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestQueryRouteDegradation:
    """Tests for degradation handling in query routes."""

    @pytest.mark.asyncio
    async def test_query_response_includes_retrieval_quality(self, test_client):
        """Query response should include retrieval quality metadata."""
        # Mock workflow to return state with retrieval quality
        mock_state = {
            "request_id": "test-123",
            "response": "Test response",
            "documents": [],
            "model_used": "test-model",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "timing": {"total": 500},
            "retrieval_quality": {
                "degradation_level": "degraded",
                "mode": "semantic_only",
                "components_used": ["qdrant"],
                "components_skipped": ["opensearch"],
            },
            "context_quality": "partial",
            "fallbacks_used": ["retrieval:semantic_only"],
        }

        with patch("api.routes.query.build_rag_workflow") as mock_workflow:
            mock_workflow.return_value.ainvoke = AsyncMock(return_value=mock_state)

            response = test_client.post(
                "/api/v1/query",
                json={"query": "test question"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["retrieval_mode"] == "semantic_only"
        assert data["context_quality"] == "partial"
        assert data["components_available"]["semantic_search"] is True
        assert data["components_available"]["keyword_search"] is False
        assert "retrieval:semantic_only" in data["fallbacks_used"]
```

### Step 2: Run test to verify it fails

```bash
cd services/orchestrator && python -m pytest tests/api/test_query_route_degradation.py -v
```

Expected: FAIL - response doesn't include quality metadata

### Step 3: Update query route to include quality metadata

Find where `QueryResponse` is constructed in `services/orchestrator/api/routes/query.py` and update it to include the new fields:

```python
# After workflow completes, extract quality info
retrieval_quality = state.get("retrieval_quality", {})
components_used = retrieval_quality.get("components_used", [])

return QueryResponse(
    request_id=state["request_id"],
    response=state.get("response", ""),
    sources=sources,
    session_id=session_id,
    model=state.get("model_used", config.default_model),
    usage=usage,
    latency_ms=state.get("timing", {}).get("total", 0),
    strategy_used=state.get("strategy"),
    # Quality metadata (US-10.2.2)
    retrieval_mode=retrieval_quality.get("mode"),
    context_quality=state.get("context_quality"),
    components_available={
        "semantic_search": "qdrant" in components_used,
        "keyword_search": "opensearch" in components_used,
        "reranking": "reranker" in components_used,
    } if retrieval_quality else None,
    fallbacks_used=state.get("fallbacks_used", []),
)
```

### Step 4: Run test to verify it passes

```bash
cd services/orchestrator && python -m pytest tests/api/test_query_route_degradation.py -v
```

Expected: PASS

### Step 5: Commit

```bash
git add services/orchestrator/api/routes/query.py services/orchestrator/tests/api/test_query_route_degradation.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): include quality metadata in query response

Wire up retrieval_quality from RAGState to QueryResponse for
complete end-to-end degradation propagation.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Integration Test for End-to-End Degradation Flow

**Files:**
- Test: `services/orchestrator/tests/test_degradation_integration.py` (new)

### Step 1: Write the integration test

Create `services/orchestrator/tests/test_degradation_integration.py`:

```python
"""Integration tests for end-to-end degradation propagation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from workflow.graph import build_rag_workflow
from workflow.state import create_initial_state


class TestDegradationIntegration:
    """Integration tests for degradation flow from retrieval to response."""

    @pytest.mark.asyncio
    async def test_degradation_flows_through_entire_pipeline(self):
        """Degradation info should flow from retrieval to final response."""
        # Mock retrieval service response with degradation
        mock_retrieval_response = MagicMock()
        mock_retrieval_response.json.return_value = {
            "results": [
                {
                    "content": "Test content",
                    "score": 0.9,
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "metadata": {"title": "Test Doc"},
                }
            ],
            "degradation_mode": "semantic_only",
            "components_used": ["qdrant", "reranker"],
            "components_skipped": ["opensearch"],
        }
        mock_retrieval_response.raise_for_status = MagicMock()

        # Mock LLM gateway response
        mock_llm_response = MagicMock()
        mock_llm_response.choices = [
            MagicMock(message=MagicMock(content="Test LLM response"))
        ]
        mock_llm_response.usage = MagicMock(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        )

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_retrieval_response
            )

            with patch("workflow.nodes.generation.get_llm_client") as mock_llm:
                mock_llm.return_value.chat.completions.create = AsyncMock(
                    return_value=mock_llm_response
                )

                # Run workflow
                workflow = build_rag_workflow()
                initial_state = create_initial_state(
                    request_id="test-integration",
                    query="What is the test about?",
                )

                result = await workflow.ainvoke(initial_state)

        # Verify degradation info propagated
        assert result["retrieval_quality"]["degradation_level"] == "degraded"
        assert result["retrieval_quality"]["mode"] == "semantic_only"
        assert result["context_quality"] == "partial"
        assert "retrieval:semantic_only" in result["fallbacks_used"]

        # Verify prompt included disclaimer
        system_message = result["messages"][0]["content"]
        assert "keyword" in system_message.lower() or "unavailable" in system_message.lower()

    @pytest.mark.asyncio
    async def test_minimal_degradation_shows_strong_warning(self):
        """Minimal degradation should include strong warning in prompt."""
        mock_retrieval_response = MagicMock()
        mock_retrieval_response.json.return_value = {
            "results": [{"content": "Minimal content", "score": 0.5, "chunk_id": "1", "document_id": "1"}],
            "degradation_mode": "minimal",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch", "reranker"],
        }
        mock_retrieval_response.raise_for_status = MagicMock()

        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock(message=MagicMock(content="Response"))]
        mock_llm_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_retrieval_response
            )

            with patch("workflow.nodes.generation.get_llm_client") as mock_llm:
                mock_llm.return_value.chat.completions.create = AsyncMock(
                    return_value=mock_llm_response
                )

                workflow = build_rag_workflow()
                result = await workflow.ainvoke(
                    create_initial_state(request_id="test-minimal", query="test")
                )

        assert result["retrieval_quality"]["degradation_level"] == "minimal"
        assert result["context_quality"] == "minimal"

        # Check for strong warning
        system_message = result["messages"][0]["content"]
        assert "significantly degraded" in system_message.lower() or "incomplete" in system_message.lower()
```

### Step 2: Run integration test

```bash
cd services/orchestrator && python -m pytest tests/test_degradation_integration.py -v
```

Expected: PASS (if all previous tasks completed correctly)

### Step 3: Commit

```bash
git add services/orchestrator/tests/test_degradation_integration.py
git commit -m "$(cat <<'EOF'
test(orchestrator): add integration tests for degradation flow

Verify degradation info flows from retrieval service through
workflow nodes to final response and streaming events.

Part of US-10.2.2: Cross-Service Degradation Propagation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Run Full Test Suite and Final Verification

### Step 1: Run retrieval service tests

```bash
cd services/retrieval && python -m pytest -v --tb=short
```

Expected: All tests pass

### Step 2: Run orchestrator service tests

```bash
cd services/orchestrator && python -m pytest -v --tb=short
```

Expected: All tests pass

### Step 3: Update user story status

Update `workflow/refined/10-architectural-improvements/US-10.2.2-cross-service-degradation-propagation.md`:
- Change `Status: Draft` to `Status: Done`
- Check off all acceptance criteria

### Step 4: Final commit

```bash
git add workflow/refined/10-architectural-improvements/US-10.2.2-cross-service-degradation-propagation.md
git commit -m "$(cat <<'EOF'
docs: mark US-10.2.2 cross-service degradation propagation as done

All acceptance criteria met:
- AC-1: Retrieval response includes degradation_level, components, mode
- AC-2: Orchestrator parses and stores in RAGState
- AC-3: Prompt adjusted with degradation disclaimers
- AC-4: Streaming events include degradation status
- AC-5: Final response includes quality metadata

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Summary

This plan implements US-10.2.2 in 10 tasks:

1. **Retrieval Route** - Populate degradation fields in API response
2. **RAGState** - Add retrieval_quality and context_quality fields
3. **Retrieval Node** - Parse degradation info from retrieval response
4. **Prompt Building** - Add degradation disclaimers to system prompt
5. **Streaming Models** - Add degradation fields to event data classes
6. **StreamManager** - Include degradation info in start/done events
7. **QueryResponse** - Add quality metadata fields
8. **Query Route** - Wire up quality metadata in response
9. **Integration Tests** - Verify end-to-end flow
10. **Final Verification** - Run all tests and update status

Each task follows TDD with failing test → implementation → passing test → commit.
