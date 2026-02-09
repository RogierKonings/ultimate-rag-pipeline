"""Extract verifiable claims from generated answers."""

import json
import time

import structlog
from gateway.client import ModelGateway
from gateway.models import ChatCompletionRequest, ChatMessage

from .models import Claim, ClaimExtractionResult

logger = structlog.get_logger(__name__)

CLAIM_EXTRACTION_PROMPT = """Extract the key factual claims from the following answer.
Focus on verifiable facts, not opinions or general statements.

Answer:
{answer}

Instructions:
1. Identify specific factual assertions
2. Extract up to {max_claims} most important claims
3. Categorize each claim (factual, numerical, temporal, attribution)
4. Return as JSON list

Example output:
[
  {{"text": "Python was released in 1991", "claim_type": "temporal"}},
  {{"text": "The function returns a list of integers", "claim_type": "factual"}}
]

Return ONLY the JSON array, no other text."""


class ClaimExtractor:
    """Extracts verifiable claims from generated answers."""

    def __init__(
        self,
        gateway: ModelGateway,
        max_claims: int = 5,
        model: str | None = None,
    ) -> None:
        """Initialize the claim extractor.

        Args:
            gateway: Model gateway for LLM calls.
            max_claims: Maximum number of claims to extract.
            model: Optional model override for extraction calls.
        """
        self.gateway = gateway
        self.max_claims = max_claims
        self.model = model or gateway.default_model

    async def extract(self, answer: str) -> ClaimExtractionResult:
        """Extract claims from an answer.

        Args:
            answer: The generated answer to extract claims from.

        Returns:
            ClaimExtractionResult with extracted claims and timing.
        """
        start = time.perf_counter()

        prompt = CLAIM_EXTRACTION_PROMPT.format(
            answer=answer,
            max_claims=self.max_claims,
        )

        request = ChatCompletionRequest(
            model=self.model,
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=500,
        )

        try:
            response = await self.gateway.chat_completion(request)
            content = response.choices[0].message.content if response.choices else ""

            claims = self._parse_claims(content)
        except Exception as e:
            logger.warning("claim_extraction_failed", error=str(e))
            claims = []

        extraction_time_ms = (time.perf_counter() - start) * 1000

        return ClaimExtractionResult(
            claims=claims[: self.max_claims],
            extraction_time_ms=extraction_time_ms,
        )

    def _parse_claims(self, content: str) -> list[Claim]:
        """Parse claims from LLM response.

        Args:
            content: Raw LLM response content.

        Returns:
            List of parsed claims.
        """
        try:
            # Try to extract JSON array from response
            content = content.strip()

            # Handle potential markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

            claims_data = json.loads(content)

            if not isinstance(claims_data, list):
                logger.warning("claim_extraction_not_list", content=content[:100])
                return []

            claims = []
            for item in claims_data:
                if isinstance(item, dict) and "text" in item:
                    claim_type = item.get("claim_type", "factual")
                    if claim_type not in ("factual", "numerical", "temporal", "attribution"):
                        claim_type = "factual"
                    claims.append(
                        Claim(
                            text=item["text"],
                            claim_type=claim_type,
                        )
                    )

            return claims

        except json.JSONDecodeError as e:
            logger.warning("claim_extraction_parse_error", error=str(e), content=content[:100])
            return []
