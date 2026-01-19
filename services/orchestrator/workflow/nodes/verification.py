"""Verification node for CRAG-style answer validation.

This node verifies that the generated answer is grounded in the retrieved
context by extracting claims and checking them against the source documents.
"""

import time
from typing import TYPE_CHECKING

import structlog

from config import get_config
from gateway.client import ModelGateway
from observability.verification_metrics import record_verification_metrics
from workflow.verification.claim_extractor import ClaimExtractor
from workflow.verification.claim_verifier import ClaimVerifier
from workflow.verification.models import VerificationResult, VerificationStatus

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = structlog.get_logger(__name__)

LOW_CONFIDENCE_DISCLAIMER = (
    "\n\n*Note: Some information in this response could not be fully "
    "verified against the available sources. Please verify important "
    "details independently.*"
)


def _create_skipped_result(
    skip_reason: str, verification_time_ms: float = 0.0
) -> VerificationResult:
    """Create a skipped verification result."""
    return VerificationResult(
        score=1.0,
        label="skipped",
        claims_total=0,
        claims_supported=0,
        claims_partial=0,
        claims_unsupported=0,
        verification_time_ms=verification_time_ms,
        skipped=True,
        skip_reason=skip_reason,
    )


async def verification_node(state: "RAGState") -> "RAGState":
    """
    Verify generated answer against retrieved context.

    This is an optional node that can be enabled per-request via options.
    It adds latency but improves answer quality assurance by checking
    that claims in the answer are supported by the retrieved documents.

    Args:
        state: Current RAGState with response and documents.

    Returns:
        Updated RAGState with verification_result.
    """
    start = time.perf_counter()

    config = get_config()
    timing = dict(state.get("timing", {}))
    options = state.get("options", {})

    # Check if verification is enabled (request-level option overrides config)
    enable_verification = options.get(
        "enable_verification", config.verification_enabled
    )

    # Extract request_id and tenant_id for logging/metrics
    request_id = state.get("request_id", "unknown")
    tenant_id = state.get("tenant_id")

    if not enable_verification:
        result = _create_skipped_result("verification_disabled")
        timing["verification"] = (time.perf_counter() - start) * 1000
        record_verification_metrics(result, tenant_id)
        return {
            **state,
            "verification_result": result.model_dump(),
            "timing": timing,
        }

    # Check if we have a response to verify
    response = state.get("response")
    if not response:
        result = _create_skipped_result("no_response")
        timing["verification"] = (time.perf_counter() - start) * 1000
        record_verification_metrics(result, tenant_id)
        return {
            **state,
            "verification_result": result.model_dump(),
            "timing": timing,
        }

    # Check if we have context (no verification for no_retrieval strategy)
    documents = state.get("documents", [])
    if not documents:
        result = _create_skipped_result("no_context")
        timing["verification"] = (time.perf_counter() - start) * 1000
        record_verification_metrics(result, tenant_id)
        return {
            **state,
            "verification_result": result.model_dump(),
            "timing": timing,
        }

    # Build context string from documents
    context = "\n\n".join(
        f"[{i + 1}] {doc.get('content', '')}"
        for i, doc in enumerate(documents[:10])  # Limit context size
    )

    # Initialize components
    gateway = ModelGateway(config)
    extractor = ClaimExtractor(gateway, max_claims=config.verification_max_claims)
    verifier = ClaimVerifier(gateway)

    try:
        # Extract claims from the response
        extraction_result = await extractor.extract(response)
        claims = extraction_result.claims

        if not claims:
            # No claims to verify - consider it verified
            result = _create_skipped_result(
                "no_claims_extracted",
                extraction_result.extraction_time_ms,
            )
            timing["verification"] = (time.perf_counter() - start) * 1000
            record_verification_metrics(result, tenant_id)
            await gateway.close()
            return {
                **state,
                "verification_result": result.model_dump(),
                "timing": timing,
            }

        # Verify all claims in parallel
        verification_results = await verifier.verify_all(claims, context)

        # Calculate scores
        supported = sum(
            1 for r in verification_results if r.status == VerificationStatus.SUPPORTED
        )
        partial = sum(
            1
            for r in verification_results
            if r.status == VerificationStatus.PARTIALLY_SUPPORTED
        )
        unsupported = sum(
            1
            for r in verification_results
            if r.status == VerificationStatus.UNSUPPORTED
        )
        total = len(verification_results)

        # Score: full support = 1, partial = 0.5, unsupported/unverifiable = 0
        score = (supported + 0.5 * partial) / total if total > 0 else 1.0

        # Determine label
        if score >= 0.9:
            label = "supported"
        elif score >= 0.5:
            label = "partial"
        else:
            label = "unsupported"

        verification_time_ms = (time.perf_counter() - start) * 1000

        result = VerificationResult(
            score=score,
            label=label,
            claims_total=total,
            claims_supported=supported,
            claims_partial=partial,
            claims_unsupported=unsupported,
            verification_time_ms=verification_time_ms,
        )

        # Add disclaimer if low confidence
        updated_response = response
        if (
            score < config.verification_confidence_threshold
            and config.verification_add_disclaimer
        ):
            updated_response = response + LOW_CONFIDENCE_DISCLAIMER
            logger.info(
                "low_confidence_disclaimer_added",
                score=score,
                threshold=config.verification_confidence_threshold,
            )

        logger.info(
            "verification_complete",
            request_id=request_id,
            tenant_id=tenant_id,
            score=score,
            label=label,
            claims_total=total,
            claims_supported=supported,
            claims_partial=partial,
            claims_unsupported=unsupported,
            verification_time_ms=verification_time_ms,
        )

        # Record Prometheus metrics
        record_verification_metrics(result, tenant_id)

        timing["verification"] = verification_time_ms
        await gateway.close()

        return {
            **state,
            "response": updated_response,
            "verification_result": result.model_dump(),
            "timing": timing,
        }

    except Exception as e:
        logger.exception("verification_failed", request_id=request_id, error=str(e))
        # On error, skip verification and return original response
        result = _create_skipped_result(f"error: {str(e)}")
        timing["verification"] = (time.perf_counter() - start) * 1000
        record_verification_metrics(result, tenant_id)
        await gateway.close()
        return {
            **state,
            "verification_result": result.model_dump(),
            "timing": timing,
        }
