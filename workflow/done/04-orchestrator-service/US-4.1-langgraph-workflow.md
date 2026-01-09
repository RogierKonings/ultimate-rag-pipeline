# US-4.1: LangGraph Workflow

> **Story ID:** US-4.1  
> **Epic:** Orchestrator Service  
> **Priority:** Critical  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** None

## User Story

**As a** developer  
**I want** a graph-based RAG workflow  
**So that** I can orchestrate complex retrieval and generation

## Context

LangGraph provides a framework for building stateful, graph-based workflows that can handle complex orchestration patterns. The RAG workflow is modeled as a directed graph with nodes for each pipeline stage (routing, retrieval, prompt building, generation, guardrails) and conditional edges that enable dynamic routing based on query characteristics.

## Technical Requirements

### Directory Structure

```
orchestrator-service/
└── workflow/
    ├── __init__.py
    ├── graph.py             # LangGraph definition
    ├── state.py             # State models
    ├── edges.py             # Conditional edge functions
    └── nodes/
        ├── __init__.py
        ├── base.py          # Base node class
        ├── router.py        # Query routing node
        ├── retriever.py     # Retrieval node
        ├── generator.py     # Generation node
        └── guardrails.py    # Safety check nodes
```

### State Model

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal, Any
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum

class QueryStrategy(str, Enum):
    SIMPLE = "simple"           # Direct retrieval + generation
    COMPLEX = "complex"         # Multi-step retrieval
    NO_RETRIEVAL = "no_retrieval"  # Direct LLM response
    CLARIFICATION = "clarification"  # Need more info from user

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    ROUTING = "routing"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"

class RetrievedContext(BaseModel):
    """Context retrieved from the retrieval service."""
    chunk_id: UUID
    document_id: UUID
    content: str
    score: float
    source: Optional[str] = None
    title: Optional[str] = None
    metadata: dict = {}

class Message(BaseModel):
    """A single message in conversation history."""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class RAGState(BaseModel):
    """
    State object for the RAG workflow.
    
    This state is passed between nodes and accumulates
    information as the workflow progresses.
    """
    # Identifiers
    query_id: UUID = Field(default_factory=uuid4)
    session_id: Optional[UUID] = None
    
    # Input
    query: str
    original_query: str = ""  # Preserved original
    
    # User context
    tenant_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    
    # Conversation history
    history: list[Message] = []
    
    # Routing
    strategy: QueryStrategy = QueryStrategy.SIMPLE
    routing_confidence: float = 0.0
    
    # Retrieval
    contexts: list[RetrievedContext] = []
    retrieval_query: Optional[str] = None  # May differ from original
    
    # Generation
    prompt: Optional[str] = None
    response: Optional[str] = None
    model_used: Optional[str] = None
    
    # Guardrails
    input_validated: bool = False
    output_validated: bool = False
    guardrail_flags: list[str] = []
    
    # Metadata
    status: WorkflowStatus = WorkflowStatus.PENDING
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    
    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Metrics
    timings: dict[str, float] = {}  # Stage name -> ms
    
    class Config:
        arbitrary_types_allowed = True
    
    def add_timing(self, stage: str, duration_ms: float):
        """Record timing for a workflow stage."""
        self.timings[stage] = duration_ms
    
    def total_time_ms(self) -> float:
        """Calculate total workflow time."""
        return sum(self.timings.values())
```

### LangGraph Workflow Definition

```python
from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
import operator
import time

class GraphState(TypedDict):
    """LangGraph state dictionary."""
    rag_state: RAGState
    messages: Annotated[Sequence[Message], operator.add]

class RAGWorkflow:
    """
    LangGraph-based RAG workflow.
    
    The workflow consists of the following stages:
    1. Input Validation - Check input for safety issues
    2. Query Routing - Determine handling strategy
    3. Retrieval - Fetch relevant context (if needed)
    4. Prompt Building - Construct the LLM prompt
    5. Generation - Generate response with LLM
    6. Output Validation - Check output for safety
    7. Response - Return final response
    """
    
    def __init__(
        self,
        retrieval_client,
        llm_gateway,
        prompt_builder,
        input_guardrail,
        output_guardrail,
        query_router,
        enable_checkpoints: bool = False
    ):
        self.retrieval_client = retrieval_client
        self.llm_gateway = llm_gateway
        self.prompt_builder = prompt_builder
        self.input_guardrail = input_guardrail
        self.output_guardrail = output_guardrail
        self.query_router = query_router
        
        self.graph = self._build_graph()
        
        # Enable checkpointing for state persistence
        if enable_checkpoints:
            self.checkpointer = MemorySaver()
            self.app = self.graph.compile(checkpointer=self.checkpointer)
        else:
            self.app = self.graph.compile()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        # Create graph with state schema
        graph = StateGraph(GraphState)
        
        # Add nodes
        graph.add_node("input_validation", self._input_validation_node)
        graph.add_node("query_routing", self._query_routing_node)
        graph.add_node("retrieval", self._retrieval_node)
        graph.add_node("prompt_building", self._prompt_building_node)
        graph.add_node("generation", self._generation_node)
        graph.add_node("output_validation", self._output_validation_node)
        graph.add_node("error_handler", self._error_handler_node)
        
        # Set entry point
        graph.set_entry_point("input_validation")
        
        # Add edges
        # Input validation -> routing or error
        graph.add_conditional_edges(
            "input_validation",
            self._route_after_input_validation,
            {
                "query_routing": "query_routing",
                "error": "error_handler"
            }
        )
        
        # Query routing -> retrieval or prompt building
        graph.add_conditional_edges(
            "query_routing",
            self._route_after_routing,
            {
                "retrieval": "retrieval",
                "prompt_building": "prompt_building"
            }
        )
        
        # Retrieval -> prompt building
        graph.add_edge("retrieval", "prompt_building")
        
        # Prompt building -> generation
        graph.add_edge("prompt_building", "generation")
        
        # Generation -> output validation
        graph.add_edge("generation", "output_validation")
        
        # Output validation -> end or retry or error
        graph.add_conditional_edges(
            "output_validation",
            self._route_after_output_validation,
            {
                "end": END,
                "retry": "generation",
                "error": "error_handler"
            }
        )
        
        # Error handler -> end
        graph.add_edge("error_handler", END)
        
        return graph
    
    # ============ Node Implementations ============
    
    async def _input_validation_node(self, state: GraphState) -> GraphState:
        """Validate input for safety issues."""
        start = time.time()
        rag_state = state["rag_state"]
        rag_state.status = WorkflowStatus.ROUTING
        
        try:
            # Run input guardrail
            is_valid, flags = await self.input_guardrail.validate(rag_state.query)
            
            rag_state.input_validated = is_valid
            rag_state.guardrail_flags.extend(flags)
            rag_state.original_query = rag_state.query
            
        except Exception as e:
            rag_state.error = f"Input validation failed: {str(e)}"
            rag_state.status = WorkflowStatus.FAILED
        
        rag_state.add_timing("input_validation", (time.time() - start) * 1000)
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    async def _query_routing_node(self, state: GraphState) -> GraphState:
        """Route query to appropriate strategy."""
        start = time.time()
        rag_state = state["rag_state"]
        
        try:
            strategy, confidence = await self.query_router.route(
                query=rag_state.query,
                history=rag_state.history
            )
            
            rag_state.strategy = strategy
            rag_state.routing_confidence = confidence
            
        except Exception as e:
            # Default to simple retrieval on error
            rag_state.strategy = QueryStrategy.SIMPLE
            rag_state.routing_confidence = 0.5
        
        rag_state.add_timing("query_routing", (time.time() - start) * 1000)
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    async def _retrieval_node(self, state: GraphState) -> GraphState:
        """Retrieve relevant context."""
        start = time.time()
        rag_state = state["rag_state"]
        rag_state.status = WorkflowStatus.RETRIEVING
        
        try:
            # Use original query or modified retrieval query
            query = rag_state.retrieval_query or rag_state.query
            
            # Call retrieval service
            results = await self.retrieval_client.retrieve(
                query=query,
                tenant_id=rag_state.tenant_id,
                user_id=rag_state.user_id,
                top_k=10
            )
            
            # Convert to RetrievedContext
            rag_state.contexts = [
                RetrievedContext(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    content=r.content,
                    score=r.score,
                    source=r.source,
                    title=r.title,
                    metadata=r.metadata
                )
                for r in results
            ]
            
        except Exception as e:
            rag_state.error = f"Retrieval failed: {str(e)}"
            # Continue with empty context rather than failing
            rag_state.contexts = []
        
        rag_state.add_timing("retrieval", (time.time() - start) * 1000)
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    async def _prompt_building_node(self, state: GraphState) -> GraphState:
        """Build the prompt for LLM generation."""
        start = time.time()
        rag_state = state["rag_state"]
        
        try:
            prompt = await self.prompt_builder.build(
                query=rag_state.query,
                contexts=rag_state.contexts,
                history=rag_state.history,
                strategy=rag_state.strategy
            )
            
            rag_state.prompt = prompt
            
        except Exception as e:
            rag_state.error = f"Prompt building failed: {str(e)}"
            rag_state.status = WorkflowStatus.FAILED
        
        rag_state.add_timing("prompt_building", (time.time() - start) * 1000)
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    async def _generation_node(self, state: GraphState) -> GraphState:
        """Generate response using LLM."""
        start = time.time()
        rag_state = state["rag_state"]
        rag_state.status = WorkflowStatus.GENERATING
        
        try:
            response, model = await self.llm_gateway.generate(
                prompt=rag_state.prompt,
                max_tokens=1024,
                temperature=0.7
            )
            
            rag_state.response = response
            rag_state.model_used = model
            
        except Exception as e:
            rag_state.error = f"Generation failed: {str(e)}"
            rag_state.status = WorkflowStatus.FAILED
        
        rag_state.add_timing("generation", (time.time() - start) * 1000)
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    async def _output_validation_node(self, state: GraphState) -> GraphState:
        """Validate output for safety issues."""
        start = time.time()
        rag_state = state["rag_state"]
        rag_state.status = WorkflowStatus.VALIDATING
        
        try:
            if rag_state.response:
                is_valid, flags = await self.output_guardrail.validate(
                    rag_state.response
                )
                
                rag_state.output_validated = is_valid
                rag_state.guardrail_flags.extend(flags)
                
                if is_valid:
                    rag_state.status = WorkflowStatus.COMPLETED
                    rag_state.completed_at = datetime.utcnow()
            else:
                rag_state.status = WorkflowStatus.FAILED
                rag_state.error = "No response generated"
            
        except Exception as e:
            rag_state.error = f"Output validation failed: {str(e)}"
            rag_state.status = WorkflowStatus.FAILED
        
        rag_state.add_timing("output_validation", (time.time() - start) * 1000)
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    async def _error_handler_node(self, state: GraphState) -> GraphState:
        """Handle errors in the workflow."""
        rag_state = state["rag_state"]
        rag_state.status = WorkflowStatus.FAILED
        rag_state.completed_at = datetime.utcnow()
        
        # Generate fallback response
        if not rag_state.response:
            rag_state.response = (
                "I apologize, but I encountered an issue processing your request. "
                "Please try again or rephrase your question."
            )
        
        return {"rag_state": rag_state, "messages": state["messages"]}
    
    # ============ Routing Functions ============
    
    def _route_after_input_validation(self, state: GraphState) -> str:
        """Route after input validation."""
        rag_state = state["rag_state"]
        
        if rag_state.input_validated:
            return "query_routing"
        else:
            return "error"
    
    def _route_after_routing(self, state: GraphState) -> str:
        """Route based on query strategy."""
        rag_state = state["rag_state"]
        
        if rag_state.strategy == QueryStrategy.NO_RETRIEVAL:
            return "prompt_building"
        else:
            return "retrieval"
    
    def _route_after_output_validation(self, state: GraphState) -> str:
        """Route after output validation."""
        rag_state = state["rag_state"]
        
        if rag_state.output_validated:
            return "end"
        elif rag_state.retry_count < rag_state.max_retries:
            rag_state.retry_count += 1
            return "retry"
        else:
            return "error"
    
    # ============ Execution ============
    
    async def run(
        self,
        query: str,
        session_id: Optional[UUID] = None,
        history: Optional[list[Message]] = None,
        tenant_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None
    ) -> RAGState:
        """
        Execute the RAG workflow.
        
        Args:
            query: User's query
            session_id: Session ID for conversation tracking
            history: Conversation history
            tenant_id: Tenant for ACL
            user_id: User for ACL
        
        Returns:
            Final RAGState with response
        """
        initial_state = GraphState(
            rag_state=RAGState(
                query=query,
                session_id=session_id,
                history=history or [],
                tenant_id=tenant_id,
                user_id=user_id
            ),
            messages=[]
        )
        
        # Execute workflow
        config = {}
        if session_id:
            config["configurable"] = {"thread_id": str(session_id)}
        
        final_state = await self.app.ainvoke(initial_state, config=config)
        
        return final_state["rag_state"]
    
    def get_graph_visualization(self) -> str:
        """Get Mermaid diagram of the workflow."""
        return self.graph.get_graph().draw_mermaid()
```

### Workflow Executor with Streaming

```python
from typing import AsyncIterator
import asyncio

class StreamingRAGWorkflow(RAGWorkflow):
    """
    RAG workflow with streaming support.
    
    Yields intermediate states and final response tokens.
    """
    
    async def run_streaming(
        self,
        query: str,
        session_id: Optional[UUID] = None,
        history: Optional[list[Message]] = None,
        tenant_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None
    ) -> AsyncIterator[dict]:
        """
        Execute workflow with streaming.
        
        Yields:
            - Status updates for each stage
            - Retrieved contexts
            - Response tokens
        """
        initial_state = GraphState(
            rag_state=RAGState(
                query=query,
                session_id=session_id,
                history=history or [],
                tenant_id=tenant_id,
                user_id=user_id
            ),
            messages=[]
        )
        
        # Stream through workflow stages
        async for event in self.app.astream(initial_state):
            for node_name, state in event.items():
                rag_state = state["rag_state"]
                
                yield {
                    "type": "status",
                    "node": node_name,
                    "status": rag_state.status.value,
                    "timing": rag_state.timings.get(node_name)
                }
                
                # Yield contexts when retrieval completes
                if node_name == "retrieval" and rag_state.contexts:
                    yield {
                        "type": "contexts",
                        "contexts": [
                            {
                                "content": c.content[:200] + "...",
                                "source": c.source,
                                "score": c.score
                            }
                            for c in rag_state.contexts[:5]
                        ]
                    }
        
        # Final response
        yield {
            "type": "response",
            "content": rag_state.response,
            "model": rag_state.model_used,
            "timings": rag_state.timings
        }
```

## Acceptance Criteria

- [ ] LangGraph state machine defined with RAGState
- [ ] All nodes implemented (validation, routing, retrieval, prompt, generation)
- [ ] Conditional edges for routing based on strategy
- [ ] State persistence support via checkpointing
- [ ] Workflow visualization available (Mermaid)
- [ ] Streaming execution yields intermediate states
- [ ] Error handling with fallback responses
- [ ] Retry logic for transient failures
- [ ] Timing metrics captured for each stage

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

@pytest.fixture
def mock_retrieval_client():
    client = AsyncMock()
    client.retrieve.return_value = [
        MagicMock(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            score=0.9,
            source="test.md",
            title="Test",
            metadata={}
        )
    ]
    return client

@pytest.fixture
def mock_llm_gateway():
    gateway = AsyncMock()
    gateway.generate.return_value = ("Test response", "llama-3.1-8b")
    return gateway

@pytest.fixture
def mock_prompt_builder():
    builder = AsyncMock()
    builder.build.return_value = "Test prompt"
    return builder

@pytest.fixture
def mock_input_guardrail():
    guardrail = AsyncMock()
    guardrail.validate.return_value = (True, [])
    return guardrail

@pytest.fixture
def mock_output_guardrail():
    guardrail = AsyncMock()
    guardrail.validate.return_value = (True, [])
    return guardrail

@pytest.fixture
def mock_query_router():
    router = AsyncMock()
    router.route.return_value = (QueryStrategy.SIMPLE, 0.9)
    return router

@pytest.fixture
def workflow(
    mock_retrieval_client,
    mock_llm_gateway,
    mock_prompt_builder,
    mock_input_guardrail,
    mock_output_guardrail,
    mock_query_router
):
    return RAGWorkflow(
        retrieval_client=mock_retrieval_client,
        llm_gateway=mock_llm_gateway,
        prompt_builder=mock_prompt_builder,
        input_guardrail=mock_input_guardrail,
        output_guardrail=mock_output_guardrail,
        query_router=mock_query_router
    )

@pytest.mark.asyncio
async def test_workflow_completes_successfully(workflow):
    """Test complete workflow execution."""
    result = await workflow.run(
        query="What is machine learning?",
        session_id=uuid4()
    )
    
    assert result.status == WorkflowStatus.COMPLETED
    assert result.response == "Test response"
    assert len(result.contexts) == 1

@pytest.mark.asyncio
async def test_workflow_routes_to_retrieval(workflow, mock_query_router):
    """Test that SIMPLE strategy routes to retrieval."""
    mock_query_router.route.return_value = (QueryStrategy.SIMPLE, 0.9)
    
    result = await workflow.run(query="test query")
    
    assert result.strategy == QueryStrategy.SIMPLE
    assert len(result.contexts) > 0

@pytest.mark.asyncio
async def test_workflow_skips_retrieval_for_no_retrieval(
    workflow, mock_query_router, mock_retrieval_client
):
    """Test that NO_RETRIEVAL strategy skips retrieval."""
    mock_query_router.route.return_value = (QueryStrategy.NO_RETRIEVAL, 0.95)
    
    result = await workflow.run(query="Hello, how are you?")
    
    assert result.strategy == QueryStrategy.NO_RETRIEVAL
    mock_retrieval_client.retrieve.assert_not_called()

@pytest.mark.asyncio
async def test_workflow_handles_input_guardrail_failure(
    workflow, mock_input_guardrail
):
    """Test handling of input guardrail failure."""
    mock_input_guardrail.validate.return_value = (False, ["blocked_content"])
    
    result = await workflow.run(query="bad query")
    
    assert result.status == WorkflowStatus.FAILED
    assert "blocked_content" in result.guardrail_flags

@pytest.mark.asyncio
async def test_workflow_retries_on_output_failure(
    workflow, mock_output_guardrail, mock_llm_gateway
):
    """Test retry on output guardrail failure."""
    # First call fails, second succeeds
    mock_output_guardrail.validate.side_effect = [
        (False, ["unsafe"]),
        (True, [])
    ]
    
    result = await workflow.run(query="test")
    
    assert result.status == WorkflowStatus.COMPLETED
    assert result.retry_count == 1
    assert mock_llm_gateway.generate.call_count == 2

@pytest.mark.asyncio
async def test_workflow_captures_timings(workflow):
    """Test that timing metrics are captured."""
    result = await workflow.run(query="test")
    
    assert "input_validation" in result.timings
    assert "query_routing" in result.timings
    assert "retrieval" in result.timings
    assert "prompt_building" in result.timings
    assert "generation" in result.timings
    assert result.total_time_ms() > 0

def test_graph_visualization(workflow):
    """Test that graph visualization works."""
    mermaid = workflow.get_graph_visualization()
    
    assert "input_validation" in mermaid
    assert "query_routing" in mermaid
    assert "generation" in mermaid
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_with_real_services():
    """Integration test with real retrieval and LLM services."""
    from gateway.client import LLMGatewayClient
    from retrieval_client import RetrievalClient
    # ... setup real clients
    
    workflow = RAGWorkflow(
        retrieval_client=RetrievalClient("http://localhost:8002"),
        llm_gateway=LLMGatewayClient("http://localhost:8004"),
        # ... other components
    )
    
    result = await workflow.run(
        query="What is retrieval augmented generation?",
        session_id=uuid4()
    )
    
    assert result.status == WorkflowStatus.COMPLETED
    assert result.response is not None
    assert "retrieval" in result.response.lower() or "rag" in result.response.lower()
```

## Dependencies

- `langgraph>=0.0.40`
- `langchain-core>=0.1.0`
- `pydantic>=2.5.0`

## Performance Requirements

- Workflow orchestration overhead: < 10ms
- State serialization: < 5ms
- Checkpointing: < 20ms
- Graph compilation: < 100ms (startup only)

## Definition of Done

- [ ] RAGState model defined with all necessary fields
- [ ] LangGraph workflow compiled with all nodes
- [ ] Conditional routing implemented
- [ ] All node implementations complete
- [ ] Error handling with fallbacks
- [ ] Retry logic for output validation
- [ ] Timing metrics captured
- [ ] Streaming execution supported
- [ ] Checkpointing for state persistence
- [ ] Graph visualization available
- [ ] >90% test coverage
- [ ] Integration test passes
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
