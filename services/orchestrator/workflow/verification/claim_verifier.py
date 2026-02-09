"""Verify claims against retrieved context."""

import asyncio
import json

import structlog
from gateway.client import ModelGateway
from gateway.models import ChatCompletionRequest, ChatMessage

from .models import Claim, ClaimVerificationResult, VerificationStatus

logger = structlog.get_logger(__name__)

CLAIM_VERIFICATION_PROMPT = """Verify if the following claim is supported by the provided context.

Claim: {claim}

Context:
{context}

Instructions:
1. Check if the context supports the claim
2. Determine if the support is full, partial, or none
3. Quote relevant supporting evidence if found

Respond with JSON:
{{
  "status": "supported" | "partially_supported" | "unsupported" | "unverifiable",
  "evidence": "quoted text from context or null",
  "reasoning": "brief explanation"
}}

Return ONLY the JSON object, no other text."""


class ClaimVerifier:
    """Verifies claims against retrieved context."""

    def __init__(self, gateway: ModelGateway, model: str | None = None) -> None:
        """Initialize the claim verifier.

        Args:
            gateway: Model gateway for LLM calls.
            model: Optional model override for verification calls.
        """
        self.gateway = gateway
        self.model = model or gateway.default_model

    async def verify(
        self,
        claim: Claim,
        context: str,
    ) -> ClaimVerificationResult:
        """Verify a single claim against context.

        Args:
            claim: The claim to verify.
            context: The context to verify against.

        Returns:
            ClaimVerificationResult with verification status.
        """
        prompt = CLAIM_VERIFICATION_PROMPT.format(
            claim=claim.text,
            context=context,
        )

        request = ChatCompletionRequest(
            model=self.model,
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=300,
        )

        try:
            response = await self.gateway.chat_completion(request)
            content = response.choices[0].message.content if response.choices else ""

            status, evidence = self._parse_verification(content)
        except Exception as e:
            logger.warning("claim_verification_failed", claim=claim.text[:50], error=str(e))
            status = VerificationStatus.UNVERIFIABLE
            evidence = None

        return ClaimVerificationResult(
            claim_text=claim.text,
            status=status,
            supporting_evidence=evidence,
        )

    def _parse_verification(self, content: str) -> tuple[VerificationStatus, str | None]:
        """Parse verification result from LLM response.

        Args:
            content: Raw LLM response content.

        Returns:
            Tuple of (status, evidence).
        """
        try:
            content = content.strip()

            # Handle potential markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

            result = json.loads(content)

            status_str = result.get("status", "unverifiable")
            try:
                status = VerificationStatus(status_str)
            except ValueError:
                status = VerificationStatus.UNVERIFIABLE

            evidence = result.get("evidence")
            if evidence == "null" or evidence == "":
                evidence = None

            return status, evidence

        except json.JSONDecodeError as e:
            logger.warning("verification_parse_error", error=str(e), content=content[:100])
            return VerificationStatus.UNVERIFIABLE, None

    async def verify_all(
        self,
        claims: list[Claim],
        context: str,
    ) -> list[ClaimVerificationResult]:
        """Verify all claims in parallel.

        Args:
            claims: List of claims to verify.
            context: The context to verify against.

        Returns:
            List of ClaimVerificationResult for each claim.
        """
        if not claims:
            return []

        tasks = [self.verify(claim, context) for claim in claims]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions that occurred
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "claim_verification_exception",
                    claim=claims[i].text[:50],
                    error=str(result),
                )
                processed_results.append(
                    ClaimVerificationResult(
                        claim_text=claims[i].text,
                        status=VerificationStatus.UNVERIFIABLE,
                        supporting_evidence=None,
                    )
                )
            else:
                processed_results.append(result)

        return processed_results
