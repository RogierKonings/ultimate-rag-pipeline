"""
Configuration validation for RAG pipeline timeout cascades.

This module validates that timeout configurations follow proper cascade hierarchy,
ensuring inner timeouts are always less than their outer container timeouts.

Cascade rules validated:
- Retrieval: max(embedding, qdrant, opensearch, reranker) < retrieval_total
- Orchestrator: orchestrator_retrieval < orchestrator_total
- Cross-service: retrieval_total < orchestrator_retrieval
- Ingestion: max(parsing, embedding, qdrant_upsert, opensearch_index) < ingestion_document

Usage:
    from shared.config.validation import validate_on_startup

    # At service startup
    validate_on_startup(fail_fast=True)
"""

from __future__ import annotations

import structlog

from .timeouts import ALL_TIMEOUTS

logger = structlog.get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed: {errors}")


def validate_timeout_cascade() -> list[str]:
    """
    Validate that inner timeouts are less than outer timeouts.

    Checks the following cascade relationships:
    - Retrieval: max(embedding, qdrant, opensearch, reranker) < retrieval_total
    - Orchestrator: orchestrator_retrieval < orchestrator_total
    - Cross-service: retrieval_total < orchestrator_retrieval
    - Ingestion: max(parsing, embedding, qdrant_upsert, opensearch_index) < ingestion_document

    Returns:
        List of error messages (empty if all validations pass)
    """
    errors: list[str] = []

    # Get timeout values in milliseconds
    retrieval_embedding = ALL_TIMEOUTS["RETRIEVAL_EMBEDDING"].timeout_ms
    retrieval_qdrant = ALL_TIMEOUTS["RETRIEVAL_QDRANT"].timeout_ms
    retrieval_opensearch = ALL_TIMEOUTS["RETRIEVAL_OPENSEARCH"].timeout_ms
    retrieval_reranker = ALL_TIMEOUTS["RETRIEVAL_RERANKER"].timeout_ms
    retrieval_total = ALL_TIMEOUTS["RETRIEVAL_TOTAL"].timeout_ms

    orchestrator_retrieval = ALL_TIMEOUTS["ORCHESTRATOR_RETRIEVAL"].timeout_ms
    orchestrator_total = ALL_TIMEOUTS["ORCHESTRATOR_TOTAL"].timeout_ms

    ingestion_parsing = ALL_TIMEOUTS["INGESTION_PARSING"].timeout_ms
    ingestion_embedding = ALL_TIMEOUTS["INGESTION_EMBEDDING"].timeout_ms
    ingestion_qdrant_upsert = ALL_TIMEOUTS["INGESTION_QDRANT_UPSERT"].timeout_ms
    ingestion_opensearch_index = ALL_TIMEOUTS["INGESTION_OPENSEARCH_INDEX"].timeout_ms
    ingestion_document = ALL_TIMEOUTS["INGESTION_DOCUMENT"].timeout_ms

    # Validate retrieval cascade
    max_retrieval_inner = max(
        retrieval_embedding,
        retrieval_qdrant,
        retrieval_opensearch,
        retrieval_reranker,
    )
    if max_retrieval_inner >= retrieval_total:
        errors.append(
            f"Retrieval cascade violation: max inner timeout ({max_retrieval_inner}ms) "
            f">= retrieval_total ({retrieval_total}ms). "
            f"Inner timeouts: embedding={retrieval_embedding}ms, qdrant={retrieval_qdrant}ms, "
            f"opensearch={retrieval_opensearch}ms, reranker={retrieval_reranker}ms"
        )
        logger.error(
            "retrieval_cascade_violation",
            max_inner_timeout_ms=max_retrieval_inner,
            retrieval_total_ms=retrieval_total,
            embedding_ms=retrieval_embedding,
            qdrant_ms=retrieval_qdrant,
            opensearch_ms=retrieval_opensearch,
            reranker_ms=retrieval_reranker,
        )

    # Validate orchestrator cascade
    if orchestrator_retrieval >= orchestrator_total:
        errors.append(
            f"Orchestrator cascade violation: orchestrator_retrieval ({orchestrator_retrieval}ms) "
            f">= orchestrator_total ({orchestrator_total}ms)"
        )
        logger.error(
            "orchestrator_cascade_violation",
            orchestrator_retrieval_ms=orchestrator_retrieval,
            orchestrator_total_ms=orchestrator_total,
        )

    # Validate cross-service cascade (retrieval_total < orchestrator_retrieval)
    if retrieval_total >= orchestrator_retrieval:
        errors.append(
            f"Cross-service cascade violation: retrieval_total ({retrieval_total}ms) "
            f">= orchestrator_retrieval ({orchestrator_retrieval}ms)"
        )
        logger.error(
            "cross_service_cascade_violation",
            retrieval_total_ms=retrieval_total,
            orchestrator_retrieval_ms=orchestrator_retrieval,
        )

    # Validate ingestion cascade
    max_ingestion_inner = max(
        ingestion_parsing,
        ingestion_embedding,
        ingestion_qdrant_upsert,
        ingestion_opensearch_index,
    )
    if max_ingestion_inner >= ingestion_document:
        errors.append(
            f"Ingestion cascade violation: max inner timeout ({max_ingestion_inner}ms) "
            f">= ingestion_document ({ingestion_document}ms). "
            f"Inner timeouts: parsing={ingestion_parsing}ms, embedding={ingestion_embedding}ms, "
            f"qdrant_upsert={ingestion_qdrant_upsert}ms, opensearch_index={ingestion_opensearch_index}ms"
        )
        logger.error(
            "ingestion_cascade_violation",
            max_inner_timeout_ms=max_ingestion_inner,
            ingestion_document_ms=ingestion_document,
            parsing_ms=ingestion_parsing,
            embedding_ms=ingestion_embedding,
            qdrant_upsert_ms=ingestion_qdrant_upsert,
            opensearch_index_ms=ingestion_opensearch_index,
        )

    if not errors:
        logger.info(
            "timeout_cascade_validation_passed",
            retrieval_max_inner_ms=max_retrieval_inner,
            retrieval_total_ms=retrieval_total,
            orchestrator_retrieval_ms=orchestrator_retrieval,
            orchestrator_total_ms=orchestrator_total,
            ingestion_max_inner_ms=max_ingestion_inner,
            ingestion_document_ms=ingestion_document,
        )

    return errors


def validate_on_startup(fail_fast: bool = True) -> list[str]:
    """
    Run all configuration validations at service startup.

    Args:
        fail_fast: If True, raise ConfigurationError on validation failures.
                   If False, return errors without raising.

    Returns:
        List of validation error messages (empty if all validations pass)

    Raises:
        ConfigurationError: If fail_fast=True and validation errors are found
    """
    logger.info("running_startup_configuration_validation")

    all_errors: list[str] = []

    # Run timeout cascade validation
    cascade_errors = validate_timeout_cascade()
    all_errors.extend(cascade_errors)

    if all_errors:
        logger.error(
            "startup_configuration_validation_failed",
            error_count=len(all_errors),
            errors=all_errors,
        )
        if fail_fast:
            raise ConfigurationError(all_errors)
    else:
        logger.info("startup_configuration_validation_passed")

    return all_errors
