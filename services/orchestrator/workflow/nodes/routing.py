"""Routing node for the RAG workflow.

This node determines the appropriate strategy for handling the query:
- simple: Standard retrieval + generation
- complex: Multi-step retrieval for complex queries
- no_retrieval: Direct LLM response without retrieval
"""

import re
import time
from typing import TYPE_CHECKING

from opentelemetry import trace

from shared.observability.otel.span_names import SpanNames

if TYPE_CHECKING:
    from workflow.state import RAGState

tracer = trace.get_tracer(__name__)


# Simple heuristics for routing decisions (stub implementation)
# These patterns match as whole words only
NO_RETRIEVAL_PATTERNS = [
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bthanks\b",
    r"\bthank you\b",
    r"\bgoodbye\b",
    r"\bbye\b",
    r"\bhow are you\b",
]

COMPLEX_INDICATORS = [
    r"\bcompare\b",
    r"\bcontrast\b",
    r"\banalyze\b",
    r"\bsummarize multiple\b",
    r"\bacross\b",
    r"\brelationship between\b",
]


def _classify_query(query: str) -> str:
    """
    Classify query into routing strategy.

    Args:
        query: The user's query

    Returns:
        Strategy string: "simple", "complex", or "no_retrieval"
    """
    query_lower = query.lower().strip()

    # Check for no_retrieval patterns (greetings, etc.) - word boundary matching
    for pattern in NO_RETRIEVAL_PATTERNS:
        if re.search(pattern, query_lower):
            return "no_retrieval"

    # Check for complex query indicators - word boundary matching
    for indicator in COMPLEX_INDICATORS:
        if re.search(indicator, query_lower):
            return "complex"

    # Default to simple retrieval
    return "simple"


async def routing_node(state: "RAGState") -> "RAGState":
    """
    Determine handling strategy for the query.

    This node:
    - Analyzes query characteristics
    - Considers conversation history if available
    - Selects appropriate strategy (simple/complex/no_retrieval)

    Args:
        state: Current RAGState with query

    Returns:
        Updated RAGState with strategy set
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_ROUTING) as span:
        start = time.time()

        query = state.get("query", "")
        tenant_id = state.get("tenant_id")
        timing = dict(state.get("timing", {}))

        # Set span attributes for query context
        span.set_attribute("orchestrator.query_length", len(query) if query else 0)
        if tenant_id:
            span.set_attribute("orchestrator.tenant_id", tenant_id)

        # Classify the query
        strategy = _classify_query(query)

        # Set strategy attribute on span
        span.set_attribute("orchestrator.strategy", strategy)

        timing["routing"] = (time.time() - start) * 1000

        return {
            **state,
            "strategy": strategy,
            "timing": timing,
        }
