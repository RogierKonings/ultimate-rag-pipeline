"""Decomposition node for multi-hop queries (US-10.4.3).

This node decomposes complex queries into simpler sub-questions that can be
answered independently. It's used for multi-hop, aggregation, and comparison
queries to enable parallel retrieval across sub-questions.
"""

import json
import time
from typing import TYPE_CHECKING

import httpx
import structlog
from model_policy import select_decomposition_model
from model_router import ModelRouter
from observability.business_metrics import record_decomposition, record_multi_hop_query
from opentelemetry import trace

from config import get_config
from orchestrator.observability.otel.span_names import SpanNames

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)
_model_router = ModelRouter()


# Prompt templates for different multi-hop types
DECOMPOSITION_PROMPTS = {
    "comparison": """Break down this comparison question into sub-questions that gather information about each entity being compared.

Original question: {query}

Instructions:
1. Identify the entities being compared
2. Create 2-4 sub-questions to gather key facts about each entity
3. Each sub-question should be answerable with a single retrieval
4. Focus on comparable aspects
5. Return as JSON array of strings

Example:
Original: "Compare Python and JavaScript for web development"
Sub-questions:
["What are the key features of Python for web development?",
 "What are the key features of JavaScript for web development?",
 "What are the main use cases for Python in web backends?",
 "What are the main use cases for JavaScript in web frontends?"]

Return ONLY the JSON array of sub-questions, no other text.""",
    "aggregation": """Break down this question that requires gathering multiple pieces of information.

Original question: {query}

Instructions:
1. Identify the different aspects or items to gather
2. Create 2-5 sub-questions to collect each piece of information
3. Each sub-question should be answerable with a single retrieval
4. Cover the full scope of what's being asked
5. Return as JSON array of strings

Example:
Original: "List all the authentication methods supported by our API"
Sub-questions:
["What OAuth authentication methods does the API support?",
 "What API key authentication is available?",
 "What JWT/token-based authentication is supported?",
 "What session-based authentication options exist?"]

Return ONLY the JSON array of sub-questions, no other text.""",
    "sequential": """Break down this question that requires sequential reasoning into logical steps.

Original question: {query}

Instructions:
1. Identify the sequence of information needed
2. Create 2-5 sub-questions in logical order
3. Each sub-question should be answerable with a single retrieval
4. Maintain the logical flow from start to end
5. Return as JSON array of strings

Example:
Original: "How do I set up CI/CD and then deploy to production?"
Sub-questions:
["How do I set up the CI/CD pipeline configuration?",
 "What are the required build steps in the CI pipeline?",
 "How do I configure deployment targets?",
 "What is the process for deploying to production?"]

Return ONLY the JSON array of sub-questions, no other text.""",
}

# Default prompt for general multi-hop queries
DEFAULT_DECOMPOSITION_PROMPT = """Break down this complex question into simpler sub-questions that can be answered independently.

Original question: {query}

Instructions:
1. Identify the key information needs
2. Create 2-5 independent sub-questions
3. Each sub-question should be answerable with a single retrieval
4. Preserve the context from the original question
5. Return as JSON array of strings

Return ONLY the JSON array of sub-questions, no other text."""


class QueryDecomposer:
    """Decomposes complex queries into sub-questions using LLM."""

    def __init__(
        self,
        llm_gateway_url: str,
        model: str,
        max_sub_questions: int = 5,
        timeout: float = 10.0,
    ):
        self.llm_gateway_url = llm_gateway_url
        self.model = model
        self.max_sub_questions = max_sub_questions
        self.timeout = timeout

    async def decompose(
        self,
        query: str,
        multi_hop_type: str | None = None,
    ) -> list[str]:
        """
        Decompose query into sub-questions.

        Args:
            query: The original query to decompose
            multi_hop_type: Type of multi-hop query (comparison, aggregation, sequential)

        Returns:
            List of sub-questions (returns [query] if decomposition fails)
        """
        # Select appropriate prompt template
        prompt_template = DECOMPOSITION_PROMPTS.get(
            multi_hop_type or "",
            DEFAULT_DECOMPOSITION_PROMPT,
        )
        prompt = prompt_template.format(query=query)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.llm_gateway_url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,  # Deterministic for decomposition
                        "max_tokens": 500,
                    },
                )
                response.raise_for_status()

                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse JSON array from response
                sub_questions = self._parse_sub_questions(content)

                # Limit to max sub-questions
                return sub_questions[: self.max_sub_questions]

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning(
                "decomposition_failed",
                extra={"query": query[:100], "error": str(e)},
            )
            # Fallback: return original query
            return [query]

    def _parse_sub_questions(self, content: str) -> list[str]:
        """
        Parse sub-questions from LLM response.

        Args:
            content: Raw LLM response content

        Returns:
            List of sub-questions
        """
        # Try to extract JSON array from content
        content = content.strip()

        # Handle case where content is wrapped in markdown code block
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (code block markers)
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            content = content.strip()

        try:
            sub_questions = json.loads(content)
            if isinstance(sub_questions, list) and all(isinstance(q, str) for q in sub_questions):
                return [q for q in sub_questions if q.strip()]
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract questions line by line
        lines = content.split("\n")
        questions = []
        for line in lines:
            line = line.strip()
            # Remove common prefixes like "1.", "- ", etc.
            if line and (line[0].isdigit() or line.startswith(("-", "*"))):
                # Remove the prefix
                parts = line.split(".", 1) if line[0].isdigit() else [line[0], line[1:]]
                if len(parts) > 1:
                    question = parts[1].strip().strip('"').strip("'")
                    if question:
                        questions.append(question)
            elif line.startswith(('"', "'")):
                question = line.strip('"').strip("'").strip(",")
                if question:
                    questions.append(question)

        return questions if questions else []


async def decomposition_node(state: "RAGState") -> "RAGState":
    """
    Decompose complex query into sub-questions for multi-hop retrieval.

    This node:
    - Checks if the query requires decomposition (multi_hop, comparison, aggregation strategies)
    - Uses LLM to break query into 2-5 independent sub-questions
    - Preserves original query in state
    - Skips decomposition for non-multi-hop strategies

    Args:
        state: Current RAGState with query and strategy

    Returns:
        Updated RAGState with sub_questions and original_query
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_DECOMPOSITION) as span:
        start = time.time()

        timing = dict(state.get("timing", {}))
        query = state.get("query", "")
        strategy = state.get("strategy", "simple")
        multi_hop_type = state.get("multi_hop_type")

        # Set span attributes
        span.set_attribute("orchestrator.query_length", len(query) if query else 0)
        span.set_attribute("orchestrator.strategy", strategy)
        if multi_hop_type:
            span.set_attribute("orchestrator.multi_hop_type", multi_hop_type)

        # Check if decomposition is needed
        multi_hop_strategies = {"multi_hop", "comparison", "aggregation"}
        if strategy not in multi_hop_strategies:
            # Not a multi-hop query, skip decomposition
            span.set_attribute("orchestrator.decomposition_skipped", True)
            timing["decomposition"] = (time.time() - start) * 1000

            return {
                **state,
                "sub_questions": [query],  # Single question for regular retrieval
                "timing": timing,
            }

        # Perform decomposition
        config = get_config()
        options = state.get("options", {})
        stage_models = options.get("stage_models", {})
        model_selection = select_decomposition_model(
            config=config,
            max_tokens_override=options.get("max_tokens"),
            model_override=stage_models.get("decomposition"),
            router=_model_router,
        )

        span.set_attribute("orchestrator.decomposition_model", model_selection.model)
        span.set_attribute("orchestrator.decomposition_model_tier", model_selection.tier)

        decomposer = QueryDecomposer(
            llm_gateway_url=config.llm_gateway_url,
            model=model_selection.model,
            max_sub_questions=5,
            timeout=config.retrieval_timeout,
        )

        sub_questions = await decomposer.decompose(query, multi_hop_type)

        # Set span attributes for results
        span.set_attribute("orchestrator.sub_questions_count", len(sub_questions))
        span.set_attribute("orchestrator.decomposition_skipped", False)

        # Record metrics (US-10.4.3)
        decomposition_time = time.time() - start
        tenant_id = state.get("tenant_id")

        if multi_hop_type:
            record_multi_hop_query(multi_hop_type, tenant_id)
            record_decomposition(
                multi_hop_type=multi_hop_type,
                sub_question_count=len(sub_questions),
                latency_seconds=decomposition_time,
            )

        logger.info(
            "query_decomposed",
            extra={
                "original_query": query[:100],
                "sub_question_count": len(sub_questions),
                "multi_hop_type": multi_hop_type,
            },
        )

        timing["decomposition"] = decomposition_time * 1000

        return {
            **state,
            "sub_questions": sub_questions,
            "original_query": query,  # Preserve for response synthesis
            "timing": timing,
        }
