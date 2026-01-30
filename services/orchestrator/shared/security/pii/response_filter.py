"""
PII filtering for query responses.

This module provides filtering capabilities to remove or mask PII
from search results and LLM responses before returning to users.
"""

import logging
from typing import Any

from .config import PIIHandlingMode, PIISettings
from .detector import PIIDetector
from .models import PIIResult

logger = logging.getLogger(__name__)


class PIIResponseFilter:
    """
    Filter PII from query responses.

    Applies PII detection and handling to search results
    and LLM-generated responses before returning to users.

    Example:
        ```python
        from shared.security.pii import PIIResponseFilter, PIISettings

        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.REDACT,
        )
        filter = PIIResponseFilter(settings)

        # Filter a single response
        filtered = await filter.filter_text("Contact john@example.com for info")

        # Filter search results
        results = [
            {"id": "1", "content": "Email: test@test.com", "score": 0.9},
            {"id": "2", "content": "Call 555-123-4567", "score": 0.8},
        ]
        filtered_results = await filter.filter_search_results(results)
        ```
    """

    def __init__(
        self,
        settings: PIISettings | None = None,
        detector: PIIDetector | None = None,
    ):
        """
        Initialize response filter.

        Args:
            settings: PII settings. If None, uses defaults.
            detector: PIIDetector to use. If None, creates one from settings.
        """
        self.settings = settings or PIISettings()
        self._detector = detector or PIIDetector(self.settings)

    async def filter_text(
        self,
        text: str,
        handling_mode: PIIHandlingMode | None = None,
    ) -> str:
        """
        Filter PII from text.

        Args:
            text: Text to filter.
            handling_mode: How to handle PII (None = use default).

        Returns:
            Filtered text.
        """
        if not self.settings.enabled:
            return text

        mode = handling_mode or self.settings.default_handling_mode

        if mode == PIIHandlingMode.PASSTHROUGH:
            return text

        if mode == PIIHandlingMode.REDACT:
            return await self._detector.redact(text)
        if mode == PIIHandlingMode.MASK:
            return await self._detector.mask(text)
        if mode == PIIHandlingMode.FLAG:
            # For FLAG mode, we don't modify the text
            return text
        return await self._detector.redact(text)

    async def filter_search_results(
        self,
        results: list[dict[str, Any]],
        content_field: str = "content",
        handling_mode: PIIHandlingMode | None = None,
        include_pii_metadata: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Filter PII from search results.

        Args:
            results: List of search result dicts.
            content_field: Field name containing text content.
            handling_mode: How to handle PII.
            include_pii_metadata: Whether to add PII detection metadata.

        Returns:
            Filtered search results.
        """
        if not self.settings.enabled:
            return results

        filtered_results = []

        for result in results:
            filtered = result.copy()

            if content_field in filtered and filtered[content_field]:
                content = filtered[content_field]

                if include_pii_metadata:
                    # Detect and get metadata
                    pii_result = await self._detector.detect(content)
                    filtered["pii_detected"] = pii_result.has_pii
                    filtered["pii_counts"] = pii_result.entity_counts
                    filtered["has_high_sensitivity"] = pii_result.has_high_sensitivity

                # Filter content
                filtered[content_field] = await self.filter_text(
                    content,
                    handling_mode,
                )

            filtered_results.append(filtered)

        return filtered_results

    async def filter_chunks(
        self,
        chunks: list[dict[str, Any]],
        text_field: str = "text",
        handling_mode: PIIHandlingMode | None = None,
    ) -> list[dict[str, Any]]:
        """
        Filter PII from document chunks.

        Args:
            chunks: List of chunk dicts.
            text_field: Field name containing chunk text.
            handling_mode: How to handle PII.

        Returns:
            Filtered chunks.
        """
        return await self.filter_search_results(
            results=chunks,
            content_field=text_field,
            handling_mode=handling_mode,
        )

    async def filter_llm_response(
        self,
        response: str,
        handling_mode: PIIHandlingMode | None = None,
    ) -> tuple[str, PIIResult]:
        """
        Filter PII from LLM response.

        Returns both filtered text and detection results
        for logging/auditing purposes.

        Args:
            response: LLM-generated response text.
            handling_mode: How to handle PII.

        Returns:
            Tuple of (filtered_text, pii_result).
        """
        if not self.settings.enabled:
            return response, PIIResult(processed_length=len(response))

        # First detect
        pii_result = await self._detector.detect(response)

        if not pii_result.has_pii:
            return response, pii_result

        # Log detection (without actual PII)
        logger.info(
            "PII detected in LLM response",
            extra={"pii_stats": pii_result.to_safe_dict()},
        )

        # Filter
        filtered = await self.filter_text(response, handling_mode)

        return filtered, pii_result

    async def should_block_response(
        self,
        text: str,
        block_on_high_sensitivity: bool = True,
    ) -> tuple[bool, str | None]:
        """
        Check if response should be blocked due to PII.

        Args:
            text: Text to check.
            block_on_high_sensitivity: Block if high-sensitivity PII found.

        Returns:
            Tuple of (should_block, reason).
        """
        if not self.settings.enabled:
            return False, None

        result = await self._detector.detect(text)

        if not result.has_pii:
            return False, None

        if block_on_high_sensitivity and result.has_high_sensitivity:
            sensitive_types = [
                e.entity_type
                for e in result.entities
                if e.entity_type in self.settings.high_sensitivity_entities
            ]
            return True, f"High-sensitivity PII detected: {sensitive_types}"

        if self.settings.reject_on_high_sensitivity and result.has_high_sensitivity:
            return True, "Response contains high-sensitivity PII"

        return False, None


class PIIQueryFilter:
    """
    Filter PII from user queries before processing.

    Prevents sensitive data from being logged or sent to external services.

    Example:
        ```python
        query_filter = PIIQueryFilter(settings)

        # Filter query before sending to embedding service
        safe_query = await query_filter.filter_query(
            "Find documents about john@example.com"
        )
        # -> "Find documents about [EMAIL_ADDRESS]"
        ```
    """

    def __init__(
        self,
        settings: PIISettings | None = None,
        detector: PIIDetector | None = None,
    ):
        """
        Initialize query filter.

        Args:
            settings: PII settings.
            detector: PIIDetector to use.
        """
        self.settings = settings or PIISettings()
        self._detector = detector or PIIDetector(self.settings)

    async def filter_query(
        self,
        query: str,
        handling_mode: PIIHandlingMode = PIIHandlingMode.REDACT,
    ) -> str:
        """
        Filter PII from user query.

        Args:
            query: User's search query.
            handling_mode: How to handle detected PII.

        Returns:
            Filtered query text.
        """
        if not self.settings.enabled:
            return query

        if handling_mode == PIIHandlingMode.PASSTHROUGH:
            return query

        if handling_mode == PIIHandlingMode.REDACT:
            return await self._detector.redact(query)
        if handling_mode == PIIHandlingMode.MASK:
            return await self._detector.mask(query)
        return await self._detector.redact(query)

    async def extract_query_pii(self, query: str) -> PIIResult:
        """
        Extract PII from query for logging/auditing.

        Args:
            query: User's search query.

        Returns:
            PIIResult with detected entities.
        """
        return await self._detector.detect(query)

    async def get_safe_query_for_logging(self, query: str) -> str:
        """
        Get query safe for logging (PII redacted).

        Args:
            query: Original query.

        Returns:
            Query with PII redacted for safe logging.
        """
        return await self._detector.redact(query)
