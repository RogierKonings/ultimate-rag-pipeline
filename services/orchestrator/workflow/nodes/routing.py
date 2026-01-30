"""Routing node for the RAG workflow.

This node determines the appropriate strategy for handling the query:
- simple: Standard retrieval + generation
- complex: Multi-step retrieval for complex queries
- no_retrieval: Direct LLM response without retrieval
- multi_hop: Sequential reasoning requiring decomposition (US-10.4.3)
- aggregation: Collect and summarize from multiple sources (US-10.4.3)
- comparison: Compare multiple entities (US-10.4.3)
"""

import re
import time
from typing import TYPE_CHECKING

from opentelemetry import trace

from orchestrator.observability.otel.span_names import SpanNames

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

# Multi-hop detection patterns (US-10.4.3)
COMPARISON_PATTERNS = [
    r"\bcompare\s+",
    r"\bdifference\s+between\b",
    r"\bvs\.?\s+",
    r"\bversus\s+",
    r"\bbetter\s+than\b",
    r"\bhow\s+does\s+.+\s+differ\b",
    r"\bsimilarit(?:y|ies)\s+and\s+difference",
    r"\bcontrast\b",
    r"\bwhich\s+is\s+better\b",
    r"\bpros\s+and\s+cons\b",
]

AGGREGATION_PATTERNS = [
    r"\blist\s+all\b",
    r"\bwhat\s+are\s+all\b",
    r"\bsummarize\s+",
    r"\boverview\s+of\b",
    r"\beverything\s+about\b",
    r"\ball\s+the\s+",
    r"\benumerate\b",
    r"\bcollect\s+",
]

SEQUENTIAL_PATTERNS = [
    r"\bfirst.+then\b",
    r"\bstep\s+by\s+step\b",
    r"\bwhat\s+happens\s+.+\s+and\s+then\b",
    r"\bafter\s+that\b",
    r"\bbefore\s+and\s+after\b",
    r"\bsequence\s+of\b",
    r"\bprocess\s+for\b",
]

MULTI_ENTITY_PATTERNS = [
    r"\bboth\s+.+\s+and\s+",
    r"\bbetween\s+.+\s+and\s+",
    r"(\w+),\s*(\w+),?\s*and\s+(\w+)",  # Lists like "A, B, and C"
]

# General complex indicators (fallback to COMPLEX strategy)
COMPLEX_INDICATORS = [
    r"\banalyze\b",
    r"\bsummarize multiple\b",
    r"\bacross\b",
    r"\brelationship between\b",
]


def _detect_multi_hop_type(query: str) -> str | None:
    """
    Detect type of multi-hop query.

    Args:
        query: The user's query (lowercase)

    Returns:
        Multi-hop type: "comparison", "aggregation", "sequential", or None
    """
    # Check comparison patterns first (most specific)
    for pattern in COMPARISON_PATTERNS:
        if re.search(pattern, query):
            return "comparison"

    # Check aggregation patterns
    for pattern in AGGREGATION_PATTERNS:
        if re.search(pattern, query):
            return "aggregation"

    # Check sequential/multi-hop patterns
    for pattern in SEQUENTIAL_PATTERNS:
        if re.search(pattern, query):
            return "sequential"

    # Check multi-entity patterns (indicates comparison or aggregation)
    for pattern in MULTI_ENTITY_PATTERNS:
        if re.search(pattern, query):
            return "comparison"

    return None


def _classify_query(query: str) -> tuple[str, str | None]:
    """
    Classify query into routing strategy.

    Args:
        query: The user's query

    Returns:
        Tuple of (strategy string, multi_hop_type or None)
        Strategy: "simple", "complex", "no_retrieval", "multi_hop", "aggregation", "comparison"
    """
    query_lower = query.lower().strip()

    # Check for no_retrieval patterns (greetings, etc.) - word boundary matching
    for pattern in NO_RETRIEVAL_PATTERNS:
        if re.search(pattern, query_lower):
            return ("no_retrieval", None)

    # Check for multi-hop patterns first (US-10.4.3)
    multi_hop_type = _detect_multi_hop_type(query_lower)
    if multi_hop_type == "comparison":
        return ("comparison", "comparison")
    if multi_hop_type == "aggregation":
        return ("aggregation", "aggregation")
    if multi_hop_type == "sequential":
        return ("multi_hop", "sequential")

    # Check for general complex query indicators - word boundary matching
    for indicator in COMPLEX_INDICATORS:
        if re.search(indicator, query_lower):
            return ("complex", None)

    # Default to simple retrieval
    return ("simple", None)


async def routing_node(state: "RAGState") -> "RAGState":
    """
    Determine handling strategy for the query.

    This node:
    - Analyzes query characteristics
    - Detects multi-hop patterns (comparison, aggregation, sequential)
    - Considers conversation history if available
    - Selects appropriate strategy

    Strategies:
    - simple: Standard single retrieval + generation
    - complex: Multi-step retrieval for complex queries
    - no_retrieval: Direct LLM response without retrieval
    - multi_hop: Sequential reasoning requiring decomposition (US-10.4.3)
    - aggregation: Collect and summarize from multiple sources (US-10.4.3)
    - comparison: Compare multiple entities (US-10.4.3)

    Args:
        state: Current RAGState with query

    Returns:
        Updated RAGState with strategy and multi_hop_type set
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

        # Classify the query (returns strategy and optional multi_hop_type)
        strategy, multi_hop_type = _classify_query(query)

        # Set span attributes
        span.set_attribute("orchestrator.strategy", strategy)
        if multi_hop_type:
            span.set_attribute("orchestrator.multi_hop_type", multi_hop_type)

        timing["routing"] = (time.time() - start) * 1000

        result = {
            **state,
            "strategy": strategy,
            "timing": timing,
        }

        # Add multi_hop_type to state if present (US-10.4.3)
        if multi_hop_type:
            result["multi_hop_type"] = multi_hop_type

        return result
