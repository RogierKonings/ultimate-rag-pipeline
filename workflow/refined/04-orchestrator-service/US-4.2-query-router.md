# US-4.2: Query Router

> **Story ID:** US-4.2  
> **Epic:** Orchestrator Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-4.1 (LangGraph Workflow)

## User Story

**As a** developer  
**I want** intelligent query routing  
**So that** queries are handled by the appropriate strategy

## Context

Query routing determines how to handle different types of queries. Simple factual questions can use direct retrieval, while complex multi-part questions may need decomposition. Conversational queries like greetings don't require retrieval at all. The router uses a combination of rule-based heuristics and optional LLM classification for accurate routing.

## Technical Requirements

### Directory Structure

```
orchestrator-service/
└── routing/
    ├── __init__.py
    ├── router.py            # Main query router
    ├── classifiers.py       # Query type classifiers
    ├── decomposer.py        # Query decomposition
    └── models.py            # Pydantic models
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class QueryStrategy(str, Enum):
    SIMPLE = "simple"              # Direct retrieval + generation
    COMPLEX = "complex"            # Multi-step or decomposed retrieval
    NO_RETRIEVAL = "no_retrieval"  # Direct LLM response (greetings, chitchat)
    CLARIFICATION = "clarification"  # Need more info from user
    MULTI_HOP = "multi_hop"        # Requires multiple retrieval rounds

class QueryIntent(str, Enum):
    FACTUAL = "factual"          # Seeking factual information
    PROCEDURAL = "procedural"    # How-to questions
    CONCEPTUAL = "conceptual"    # Understanding concepts
    COMPARATIVE = "comparative"  # Comparing things
    CONVERSATIONAL = "conversational"  # Chitchat, greetings
    AMBIGUOUS = "ambiguous"      # Unclear intent

class RouterConfig(BaseModel):
    """Configuration for query router."""
    # Classification method
    use_llm_classifier: bool = True
    classifier_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    
    # Confidence thresholds
    min_confidence: float = 0.6
    no_retrieval_threshold: float = 0.8  # High confidence to skip retrieval
    
    # Query length thresholds
    min_query_length: int = 3
    max_simple_query_words: int = 15
    
    # LLM settings
    llm_gateway_url: str = "http://localhost:8004"
    classification_timeout: float = 5.0
    
    # Fallback
    default_strategy: QueryStrategy = QueryStrategy.SIMPLE

class RoutingResult(BaseModel):
    """Result of query routing."""
    strategy: QueryStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    intent: QueryIntent = QueryIntent.FACTUAL
    sub_queries: list[str] = []  # For complex/decomposed queries
    reasoning: Optional[str] = None
```

### Query Router Implementation

```python
import re
from typing import Optional, Tuple
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class QueryRouter:
    """
    Routes queries to appropriate handling strategies.
    
    Uses a combination of:
    1. Rule-based heuristics (fast, no API calls)
    2. LLM classification (more accurate, optional)
    
    Strategies:
    - SIMPLE: Direct retrieval for straightforward questions
    - COMPLEX: Multi-step retrieval for compound questions
    - NO_RETRIEVAL: Skip retrieval for greetings, chitchat
    - MULTI_HOP: Multiple retrieval rounds needed
    - CLARIFICATION: Query too ambiguous
    """
    
    def __init__(self, config: RouterConfig = RouterConfig()):
        self.config = config
        self._http_client = httpx.AsyncClient(
            base_url=config.llm_gateway_url,
            timeout=config.classification_timeout
        )
        self._heuristic_classifier = HeuristicClassifier()
        self._llm_classifier = LLMClassifier(self._http_client, config)
    
    async def route(
        self,
        query: str,
        history: Optional[list] = None
    ) -> Tuple[QueryStrategy, float]:
        """
        Route a query to appropriate strategy.
        
        Args:
            query: User's query
            history: Conversation history (for context)
        
        Returns:
            Tuple of (strategy, confidence)
        """
        # Quick validation
        if len(query.strip()) < self.config.min_query_length:
            return QueryStrategy.CLARIFICATION, 0.9
        
        # Try heuristic classification first (fast)
        heuristic_result = self._heuristic_classifier.classify(query)
        
        # If high confidence from heuristics, use that
        if heuristic_result.confidence >= 0.85:
            return heuristic_result.strategy, heuristic_result.confidence
        
        # Use LLM classifier for uncertain cases
        if self.config.use_llm_classifier:
            try:
                llm_result = await self._llm_classifier.classify(query, history)
                
                # Combine heuristic and LLM results
                if llm_result.confidence > heuristic_result.confidence:
                    return llm_result.strategy, llm_result.confidence
                else:
                    return heuristic_result.strategy, heuristic_result.confidence
                    
            except Exception:
                # Fall back to heuristics on LLM failure
                pass
        
        return heuristic_result.strategy, heuristic_result.confidence
    
    async def route_with_details(
        self,
        query: str,
        history: Optional[list] = None
    ) -> RoutingResult:
        """
        Route query and return detailed result including sub-queries.
        """
        strategy, confidence = await self.route(query, history)
        
        result = RoutingResult(
            strategy=strategy,
            confidence=confidence
        )
        
        # Decompose complex queries
        if strategy == QueryStrategy.COMPLEX:
            decomposer = QueryDecomposer(self._http_client, self.config)
            result.sub_queries = await decomposer.decompose(query)
        
        # Classify intent
        result.intent = self._heuristic_classifier.classify_intent(query)
        
        return result
    
    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()


class HeuristicClassifier:
    """
    Rule-based query classifier.
    
    Uses patterns and heuristics for fast classification
    without API calls.
    """
    
    # Patterns for different query types
    GREETING_PATTERNS = [
        r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))",
        r"^(how\s+are\s+you|what'?s\s+up|howdy)",
        r"^(thanks?|thank\s+you|thx)",
        r"^(bye|goodbye|see\s+you|farewell)",
    ]
    
    CLARIFICATION_PATTERNS = [
        r"^(what|huh|sorry|pardon)\?*$",
        r"^(can\s+you|could\s+you)\s+repeat",
        r"^(I\s+don'?t\s+understand)",
    ]
    
    COMPLEX_INDICATORS = [
        r"\b(and|also|additionally|furthermore)\b",
        r"\b(compare|contrast|difference|versus|vs\.?)\b",
        r"\b(first|second|third|then|after|before)\b",
        r"\b(how\s+does\s+.+\s+relate\s+to)\b",
        r"\b(what\s+are\s+the\s+(pros|cons|advantages|disadvantages))\b",
    ]
    
    MULTI_HOP_INDICATORS = [
        r"\b(who\s+.+\s+that\s+.+)\b",
        r"\b(what\s+.+\s+of\s+the\s+.+\s+that)\b",
        r"\b(find\s+.+\s+related\s+to\s+.+\s+by)\b",
    ]
    
    PROCEDURAL_PATTERNS = [
        r"^how\s+(do|can|to|should)",
        r"^what\s+(are\s+the\s+)?steps",
        r"^(guide|tutorial|instructions)",
        r"\b(implement|create|build|setup|configure)\b",
    ]
    
    def __init__(self):
        # Compile patterns
        self._greeting_re = [re.compile(p, re.I) for p in self.GREETING_PATTERNS]
        self._clarification_re = [re.compile(p, re.I) for p in self.CLARIFICATION_PATTERNS]
        self._complex_re = [re.compile(p, re.I) for p in self.COMPLEX_INDICATORS]
        self._multi_hop_re = [re.compile(p, re.I) for p in self.MULTI_HOP_INDICATORS]
        self._procedural_re = [re.compile(p, re.I) for p in self.PROCEDURAL_PATTERNS]
    
    def classify(self, query: str) -> RoutingResult:
        """
        Classify query using heuristics.
        
        Returns routing result with strategy and confidence.
        """
        query_clean = query.strip()
        word_count = len(query_clean.split())
        
        # Check for greetings/chitchat
        for pattern in self._greeting_re:
            if pattern.search(query_clean):
                return RoutingResult(
                    strategy=QueryStrategy.NO_RETRIEVAL,
                    confidence=0.95,
                    intent=QueryIntent.CONVERSATIONAL
                )
        
        # Check for clarification needed
        for pattern in self._clarification_re:
            if pattern.search(query_clean):
                return RoutingResult(
                    strategy=QueryStrategy.CLARIFICATION,
                    confidence=0.85,
                    intent=QueryIntent.AMBIGUOUS
                )
        
        # Very short queries are likely ambiguous
        if word_count < 3:
            return RoutingResult(
                strategy=QueryStrategy.CLARIFICATION,
                confidence=0.7,
                intent=QueryIntent.AMBIGUOUS
            )
        
        # Check for multi-hop patterns
        multi_hop_matches = sum(
            1 for p in self._multi_hop_re if p.search(query_clean)
        )
        if multi_hop_matches > 0:
            return RoutingResult(
                strategy=QueryStrategy.MULTI_HOP,
                confidence=0.75,
                intent=QueryIntent.FACTUAL
            )
        
        # Check for complex query indicators
        complex_matches = sum(
            1 for p in self._complex_re if p.search(query_clean)
        )
        
        if complex_matches >= 2 or word_count > 25:
            return RoutingResult(
                strategy=QueryStrategy.COMPLEX,
                confidence=0.7 + (0.05 * min(complex_matches, 4)),
                intent=QueryIntent.COMPARATIVE if "compare" in query_clean.lower() 
                       else QueryIntent.FACTUAL
            )
        
        # Check for procedural questions
        for pattern in self._procedural_re:
            if pattern.search(query_clean):
                return RoutingResult(
                    strategy=QueryStrategy.SIMPLE,
                    confidence=0.85,
                    intent=QueryIntent.PROCEDURAL
                )
        
        # Default to simple retrieval
        confidence = 0.75
        if word_count >= 5 and word_count <= 15:
            confidence = 0.85  # Sweet spot for simple queries
        
        return RoutingResult(
            strategy=QueryStrategy.SIMPLE,
            confidence=confidence,
            intent=self.classify_intent(query_clean)
        )
    
    def classify_intent(self, query: str) -> QueryIntent:
        """Classify the intent of a query."""
        query_lower = query.lower()
        
        if any(p.search(query) for p in self._procedural_re):
            return QueryIntent.PROCEDURAL
        
        if "compare" in query_lower or "versus" in query_lower or " vs " in query_lower:
            return QueryIntent.COMPARATIVE
        
        if any(w in query_lower for w in ["what is", "what are", "define", "meaning"]):
            return QueryIntent.CONCEPTUAL
        
        if any(w in query_lower for w in ["who", "when", "where", "how many", "how much"]):
            return QueryIntent.FACTUAL
        
        return QueryIntent.FACTUAL


class LLMClassifier:
    """
    LLM-based query classifier.
    
    Uses a small prompt to classify queries when heuristics
    are uncertain.
    """
    
    CLASSIFICATION_PROMPT = """Classify the following query into one of these categories:
- SIMPLE: Straightforward question that can be answered with a single search
- COMPLEX: Multi-part question requiring multiple pieces of information
- NO_RETRIEVAL: Greeting, chitchat, or general conversation not needing search
- CLARIFICATION: Ambiguous query that needs more information

Query: {query}

Respond with only the category name (SIMPLE, COMPLEX, NO_RETRIEVAL, or CLARIFICATION) and a confidence score from 0 to 1.
Format: CATEGORY|CONFIDENCE

Example: SIMPLE|0.85"""
    
    def __init__(self, http_client: httpx.AsyncClient, config: RouterConfig):
        self._client = http_client
        self.config = config
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True
    )
    async def classify(
        self,
        query: str,
        history: Optional[list] = None
    ) -> RoutingResult:
        """Classify query using LLM."""
        prompt = self.CLASSIFICATION_PROMPT.format(query=query)
        
        response = await self._client.post(
            "/v1/completions",
            json={
                "model": self.config.classifier_model,
                "prompt": prompt,
                "max_tokens": 20,
                "temperature": 0.1,
                "stop": ["\n"]
            }
        )
        response.raise_for_status()
        
        data = response.json()
        result_text = data["choices"][0]["text"].strip()
        
        # Parse response
        try:
            category, confidence_str = result_text.split("|")
            strategy = QueryStrategy[category.upper().strip()]
            confidence = float(confidence_str.strip())
        except (ValueError, KeyError):
            # Default on parse error
            strategy = QueryStrategy.SIMPLE
            confidence = 0.5
        
        return RoutingResult(
            strategy=strategy,
            confidence=min(confidence, 1.0)
        )


class QueryDecomposer:
    """
    Decomposes complex queries into sub-queries.
    
    Used for multi-step retrieval where a complex question
    needs to be broken into simpler parts.
    """
    
    DECOMPOSITION_PROMPT = """Break down the following complex query into simpler sub-queries that can be answered independently.
Each sub-query should be a complete question that can be searched separately.

Query: {query}

Sub-queries (one per line):"""
    
    def __init__(self, http_client: httpx.AsyncClient, config: RouterConfig):
        self._client = http_client
        self.config = config
    
    async def decompose(self, query: str) -> list[str]:
        """
        Decompose complex query into sub-queries.
        
        Returns list of simpler sub-queries.
        """
        prompt = self.DECOMPOSITION_PROMPT.format(query=query)
        
        try:
            response = await self._client.post(
                "/v1/completions",
                json={
                    "model": self.config.classifier_model,
                    "prompt": prompt,
                    "max_tokens": 200,
                    "temperature": 0.3,
                    "stop": ["\n\n"]
                }
            )
            response.raise_for_status()
            
            data = response.json()
            result_text = data["choices"][0]["text"].strip()
            
            # Parse sub-queries
            sub_queries = []
            for line in result_text.split("\n"):
                line = line.strip()
                # Remove numbering like "1.", "1)", "-"
                line = re.sub(r"^[\d\.\)\-\*]+\s*", "", line)
                if line and len(line) > 5:
                    sub_queries.append(line)
            
            return sub_queries[:5]  # Limit to 5 sub-queries
            
        except Exception:
            # Return original query if decomposition fails
            return [query]
```

## Acceptance Criteria

- [ ] Simple query detection (direct retrieval)
- [ ] Complex query detection (multi-step, comparisons)
- [ ] No-retrieval detection (greetings, chitchat)
- [ ] Multi-hop query detection
- [ ] Clarification needed detection
- [ ] Heuristic classification works without API
- [ ] LLM classification for uncertain cases
- [ ] Query decomposition for complex queries
- [ ] Confidence scores returned with routing
- [ ] Fallback to default strategy on errors

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def router():
    config = RouterConfig(use_llm_classifier=False)
    return QueryRouter(config)

@pytest.fixture
def heuristic_classifier():
    return HeuristicClassifier()

def test_greeting_routes_to_no_retrieval(heuristic_classifier):
    """Test greetings are classified correctly."""
    greetings = ["Hello!", "Hi there", "Good morning", "Hey", "How are you?"]
    
    for greeting in greetings:
        result = heuristic_classifier.classify(greeting)
        assert result.strategy == QueryStrategy.NO_RETRIEVAL
        assert result.confidence >= 0.9

def test_simple_questions_route_to_simple(heuristic_classifier):
    """Test simple questions route to SIMPLE strategy."""
    questions = [
        "What is machine learning?",
        "How does Python work?",
        "Who invented the telephone?"
    ]
    
    for q in questions:
        result = heuristic_classifier.classify(q)
        assert result.strategy == QueryStrategy.SIMPLE

def test_complex_questions_detected(heuristic_classifier):
    """Test complex multi-part questions are detected."""
    complex_qs = [
        "Compare and contrast Python and Java, and explain which is better for data science",
        "What are the advantages and disadvantages of microservices architecture?",
        "First explain what neural networks are, then describe how they learn"
    ]
    
    for q in complex_qs:
        result = heuristic_classifier.classify(q)
        assert result.strategy in [QueryStrategy.COMPLEX, QueryStrategy.MULTI_HOP]
        assert result.confidence >= 0.7

def test_short_queries_need_clarification(heuristic_classifier):
    """Test very short queries need clarification."""
    short = ["what", "huh", "?"]
    
    for q in short:
        result = heuristic_classifier.classify(q)
        assert result.strategy == QueryStrategy.CLARIFICATION

def test_procedural_intent_classified(heuristic_classifier):
    """Test procedural questions are classified correctly."""
    procedural = [
        "How do I install Python?",
        "What are the steps to deploy a Docker container?",
        "How can I implement authentication?"
    ]
    
    for q in procedural:
        result = heuristic_classifier.classify(q)
        assert result.intent == QueryIntent.PROCEDURAL

@pytest.mark.asyncio
async def test_router_combines_heuristic_and_llm():
    """Test router combines both classifiers."""
    config = RouterConfig(use_llm_classifier=True)
    router = QueryRouter(config)
    
    with patch.object(router._llm_classifier, 'classify') as mock_llm:
        mock_llm.return_value = RoutingResult(
            strategy=QueryStrategy.COMPLEX,
            confidence=0.9
        )
        
        strategy, confidence = await router.route(
            "Compare these two approaches and explain the tradeoffs"
        )
        
        # LLM should be called for uncertain cases
        mock_llm.assert_called_once()
        assert strategy == QueryStrategy.COMPLEX
    
    await router.close()

@pytest.mark.asyncio
async def test_router_falls_back_on_llm_error():
    """Test router falls back to heuristics on LLM failure."""
    config = RouterConfig(use_llm_classifier=True)
    router = QueryRouter(config)
    
    with patch.object(router._llm_classifier, 'classify') as mock_llm:
        mock_llm.side_effect = Exception("LLM error")
        
        strategy, confidence = await router.route("What is Python?")
        
        # Should still return a result from heuristics
        assert strategy == QueryStrategy.SIMPLE
    
    await router.close()

@pytest.mark.asyncio
async def test_query_decomposition():
    """Test complex query decomposition."""
    config = RouterConfig()
    decomposer = QueryDecomposer(
        httpx.AsyncClient(base_url="http://localhost:8004"),
        config
    )
    
    with patch.object(decomposer._client, 'post') as mock_post:
        mock_post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "choices": [{
                    "text": "1. What is machine learning?\n2. What is deep learning?\n3. How do they differ?"
                }]
            }
        )
        mock_post.return_value.raise_for_status = lambda: None
        
        sub_queries = await decomposer.decompose(
            "Compare machine learning and deep learning"
        )
        
        assert len(sub_queries) == 3
        assert "machine learning" in sub_queries[0].lower()
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_router_with_real_llm():
    """Integration test with real LLM gateway."""
    config = RouterConfig(
        llm_gateway_url="http://localhost:8004",
        use_llm_classifier=True
    )
    
    router = QueryRouter(config)
    
    try:
        # Test various query types
        test_cases = [
            ("Hello!", QueryStrategy.NO_RETRIEVAL),
            ("What is Python?", QueryStrategy.SIMPLE),
            ("Compare Python and Java for web development", QueryStrategy.COMPLEX),
        ]
        
        for query, expected_strategy in test_cases:
            result = await router.route_with_details(query)
            assert result.strategy == expected_strategy
            assert result.confidence > 0.5
    finally:
        await router.close()
```

## Dependencies

- `httpx>=0.25.0`
- `tenacity>=8.2.0`
- `pydantic>=2.5.0`

## Performance Requirements

- Heuristic classification: < 1ms
- LLM classification: < 500ms
- Query decomposition: < 1s
- Total routing overhead: < 100ms typical

## Definition of Done

- [ ] HeuristicClassifier covers all query patterns
- [ ] LLMClassifier provides fallback classification
- [ ] QueryRouter combines both approaches
- [ ] Query decomposition implemented
- [ ] Intent classification implemented
- [ ] Confidence scores accurate
- [ ] Fallback to default on errors
- [ ] >90% test coverage
- [ ] Integration test passes
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
