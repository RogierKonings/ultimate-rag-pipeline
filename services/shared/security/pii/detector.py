"""
PII detection using Microsoft Presidio.

This module provides PII detection and processing capabilities
using the Presidio analyzer and anonymizer engines.
"""

import logging
import time
from pathlib import Path

import yaml

from .config import (
    PIIHandlingMode,
    PIISettings,
)
from .models import (
    PIIChunkResult,
    PIIEntity,
    PIIProcessedText,
    PIIResult,
)

logger = logging.getLogger(__name__)


class PIIDetectionError(Exception):
    """Raised when PII detection fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PIIDetector:
    """
    Detect and process PII in text using Microsoft Presidio.

    Presidio provides:
    - NLP-based named entity recognition (spaCy)
    - Pattern matching for structured data (SSN, credit cards, etc.)
    - Extensible with custom recognizers

    Example:
        ```python
        from services.shared.security.pii import PIIDetector, PIISettings

        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.REDACT,
            confidence_threshold=0.7,
        )
        detector = PIIDetector(settings)

        # Detect PII
        result = await detector.detect("Contact john@example.com")

        # Redact PII
        redacted = await detector.redact("Contact john@example.com")
        # -> "Contact [EMAIL_ADDRESS]"

        # Process with configured handling
        processed = await detector.process(
            "SSN: 123-45-6789",
            handling_mode=PIIHandlingMode.MASK,
        )
        ```
    """

    def __init__(self, settings: PIISettings | None = None):
        """
        Initialize PII detector.

        Args:
            settings: PII detection settings. If None, uses defaults.
        """
        self.settings = settings or PIISettings()
        self._analyzer = None
        self._anonymizer = None
        self._custom_recognizers_loaded = False

    def _get_analyzer(self):
        """
        Lazily initialize Presidio analyzer.

        Loading spaCy models is expensive, so we do it lazily.
        """
        if self._analyzer is None:
            self._analyzer = self._create_analyzer()
        return self._analyzer

    def _create_analyzer(self):
        """Initialize Presidio analyzer with spaCy NLP backend."""
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
        except ImportError as e:
            raise PIIDetectionError(
                "Presidio not installed. Install with: pip install presidio-analyzer",
                {"error": str(e)},
            ) from e

        # Configure NLP engine with spaCy models
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": lang, "model_name": f"{lang}_core_web_sm"}
                for lang in self.settings.languages
            ],
        }

        try:
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()
            analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        except OSError as e:
            # spaCy model not installed
            raise PIIDetectionError(
                "spaCy model not installed. Run: python -m spacy download en_core_web_sm",
                {"error": str(e)},
            ) from e

        # Load custom recognizers if configured
        if self.settings.custom_recognizers_path:
            self._load_custom_recognizers(analyzer)

        return analyzer

    def _load_custom_recognizers(self, analyzer) -> None:
        """Load custom recognizers from YAML configuration."""
        if self._custom_recognizers_loaded:
            return

        path = Path(self.settings.custom_recognizers_path)
        if not path.exists():
            logger.warning(f"Custom recognizers file not found: {path}")
            return

        try:
            from presidio_analyzer import Pattern, PatternRecognizer

            with open(path) as f:
                config = yaml.safe_load(f)

            for recognizer_config in config.get("recognizers", []):
                name = recognizer_config["name"]
                entity = recognizer_config["entity"]
                patterns = []

                for pattern_config in recognizer_config.get("patterns", []):
                    patterns.append(
                        Pattern(
                            name=pattern_config["name"],
                            regex=pattern_config["regex"],
                            score=pattern_config.get("score", 0.8),
                        ),
                    )

                if patterns:
                    recognizer = PatternRecognizer(
                        supported_entity=entity,
                        name=name,
                        patterns=patterns,
                        context=recognizer_config.get("context"),
                    )
                    analyzer.registry.add_recognizer(recognizer)
                    logger.info(f"Loaded custom recognizer: {name}")

            self._custom_recognizers_loaded = True

        except Exception as e:
            logger.error(f"Failed to load custom recognizers: {e}")

    def _get_anonymizer(self):
        """Lazily initialize Presidio anonymizer."""
        if self._anonymizer is None:
            try:
                from presidio_anonymizer import AnonymizerEngine

                self._anonymizer = AnonymizerEngine()
            except ImportError as e:
                raise PIIDetectionError(
                    "Presidio anonymizer not installed. Install with: pip install presidio-anonymizer",
                    {"error": str(e)},
                ) from e
        return self._anonymizer

    async def detect(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str | None = None,
        score_threshold: float | None = None,
    ) -> PIIResult:
        """
        Detect PII entities in text.

        Args:
            text: Text to analyze for PII.
            entities: Entity types to detect (None = use settings).
            language: Language of text (None = use first from settings).
            score_threshold: Minimum confidence (None = use settings).

        Returns:
            PIIResult with detected entities and statistics.
        """
        if not self.settings.enabled:
            return PIIResult(processed_length=len(text))

        start_time = time.perf_counter()

        analyzer = self._get_analyzer()

        # Determine parameters
        detect_entities = entities or self.settings.entities_to_detect
        lang = language or self.settings.languages[0]
        threshold = score_threshold or self.settings.confidence_threshold

        # Run analysis
        try:
            results = analyzer.analyze(
                text=text,
                language=lang,
                entities=detect_entities,
                score_threshold=threshold,
            )
        except Exception as e:
            raise PIIDetectionError(
                f"PII detection failed: {str(e)}",
                {"text_length": len(text), "language": lang},
            ) from e

        # Convert to our models
        detected_entities: list[PIIEntity] = []
        entity_counts: dict[str, int] = {}
        has_high_sensitivity = False

        for result in results:
            entity_type = result.entity_type

            # Check if entity is enabled
            if not self.settings.is_entity_enabled(entity_type):
                continue

            # Check entity-specific threshold
            min_score = self.settings.get_min_score(entity_type)
            if result.score < min_score:
                continue

            # Get sensitivity
            sensitivity = self.settings.get_sensitivity(entity_type)

            entity = PIIEntity(
                entity_type=entity_type,
                text=text[result.start : result.end],
                start=result.start,
                end=result.end,
                score=result.score,
                sensitivity=sensitivity,
            )
            detected_entities.append(entity)

            # Count by type
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

            # Check for high sensitivity
            if entity_type in self.settings.high_sensitivity_entities:
                has_high_sensitivity = True

        processing_time = (time.perf_counter() - start_time) * 1000

        result = PIIResult(
            entities=detected_entities,
            entity_counts=entity_counts,
            has_pii=len(detected_entities) > 0,
            has_high_sensitivity=has_high_sensitivity,
            processed_length=len(text),
            processing_time_ms=processing_time,
        )

        if self.settings.log_detections and result.has_pii:
            logger.info(
                "PII detected",
                extra={
                    "pii_stats": result.to_safe_dict(),
                },
            )

        return result

    async def redact(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str | None = None,
    ) -> str:
        """
        Redact PII from text with placeholder tags.

        Replaces PII with [ENTITY_TYPE] placeholders.

        Args:
            text: Text containing PII.
            entities: Entity types to redact (None = use settings).
            language: Text language (None = use settings).

        Returns:
            Text with PII replaced by placeholders.
        """
        result = await self.detect(text, entities, language)

        if not result.entities:
            return text

        # Sort by position (descending) to replace from end
        sorted_entities = sorted(result.entities, key=lambda e: e.start, reverse=True)

        redacted = text
        for entity in sorted_entities:
            placeholder = f"[{entity.entity_type}]"
            redacted = redacted[: entity.start] + placeholder + redacted[entity.end :]

        return redacted

    async def mask(
        self,
        text: str,
        entities: list[str] | None = None,
        language: str | None = None,
        mask_char: str = "*",
        chars_to_keep: int = 4,
    ) -> str:
        """
        Mask PII in text with partial visibility.

        Keeps some characters visible for context.

        Args:
            text: Text containing PII.
            entities: Entity types to mask.
            language: Text language.
            mask_char: Character to use for masking.
            chars_to_keep: Number of characters to keep visible.

        Returns:
            Text with PII partially masked.
        """
        result = await self.detect(text, entities, language)

        if not result.entities:
            return text

        sorted_entities = sorted(result.entities, key=lambda e: e.start, reverse=True)

        masked = text
        for entity in sorted_entities:
            pii_text = entity.text
            pii_len = len(pii_text)

            if pii_len <= chars_to_keep:
                # Too short to mask meaningfully
                masked_value = mask_char * pii_len
            else:
                # Keep first few characters, mask the rest
                visible = pii_text[:chars_to_keep]
                masked_part = mask_char * (pii_len - chars_to_keep)
                masked_value = visible + masked_part

            masked = masked[: entity.start] + masked_value + masked[entity.end :]

        return masked

    async def process(
        self,
        text: str,
        handling_mode: PIIHandlingMode | None = None,
        entities: list[str] | None = None,
        language: str | None = None,
    ) -> PIIProcessedText:
        """
        Process text according to configured handling mode.

        Args:
            text: Text to process.
            handling_mode: How to handle PII (None = use default).
            entities: Entity types to process.
            language: Text language.

        Returns:
            PIIProcessedText with processed text and transformation details.
        """
        mode = handling_mode or self.settings.default_handling_mode

        if mode == PIIHandlingMode.PASSTHROUGH:
            return PIIProcessedText(
                original_length=len(text),
                processed_text=text,
                handling_mode=mode,
            )

        result = await self.detect(text, entities, language)

        if not result.entities:
            return PIIProcessedText(
                original_length=len(text),
                processed_text=text,
                handling_mode=mode,
            )

        transformations = []

        if mode == PIIHandlingMode.REDACT:
            processed_text = await self.redact(text, entities, language)
            for entity in result.entities:
                transformations.append(
                    {
                        "type": "redact",
                        "entity_type": entity.entity_type,
                        "start": entity.start,
                        "end": entity.end,
                        "replacement": f"[{entity.entity_type}]",
                    },
                )

        elif mode == PIIHandlingMode.MASK:
            processed_text = await self.mask(text, entities, language)
            for entity in result.entities:
                transformations.append(
                    {
                        "type": "mask",
                        "entity_type": entity.entity_type,
                        "start": entity.start,
                        "end": entity.end,
                    },
                )

        elif mode == PIIHandlingMode.FLAG:
            # Keep original text but record transformations
            processed_text = text
            for entity in result.entities:
                transformations.append(
                    {
                        "type": "flag",
                        "entity_type": entity.entity_type,
                        "start": entity.start,
                        "end": entity.end,
                        "score": entity.score,
                    },
                )

        elif mode == PIIHandlingMode.ENCRYPT:
            # For encryption, we need the encryption module
            # This is handled at a higher level, so just flag here
            processed_text = text
            for entity in result.entities:
                transformations.append(
                    {
                        "type": "encrypt_pending",
                        "entity_type": entity.entity_type,
                        "start": entity.start,
                        "end": entity.end,
                    },
                )

        else:
            processed_text = text

        return PIIProcessedText(
            original_length=len(text),
            processed_text=processed_text,
            handling_mode=mode,
            entities_processed=len(result.entities),
            transformations=transformations,
        )

    async def process_chunk(
        self,
        chunk_id: str,
        text: str,
        handling_mode: PIIHandlingMode | None = None,
    ) -> PIIChunkResult:
        """
        Process a document chunk for PII.

        Handles rejection logic for high-sensitivity PII.

        Args:
            chunk_id: ID of the chunk.
            text: Chunk text content.
            handling_mode: How to handle PII.

        Returns:
            PIIChunkResult with detection and processing results.
        """
        result = await self.detect(text)

        # Check for rejection
        rejected = False
        rejection_reason = None

        if self.settings.reject_on_high_sensitivity and result.has_high_sensitivity:
            rejected = True
            rejection_reason = f"High-sensitivity PII detected: {list(result.entity_counts.keys())}"

        # Process if not rejected and handling mode requires it
        processed = None
        mode = handling_mode or self.settings.default_handling_mode

        if not rejected and mode not in (
            PIIHandlingMode.PASSTHROUGH,
            PIIHandlingMode.FLAG,
        ):
            processed = await self.process(text, mode)

        return PIIChunkResult(
            chunk_id=chunk_id,
            detection_result=result,
            processed=processed,
            rejected=rejected,
            rejection_reason=rejection_reason,
        )

    def get_supported_entities(self) -> list[str]:
        """Get list of supported entity types."""
        analyzer = self._get_analyzer()
        return analyzer.get_supported_entities()


# Module-level convenience functions
_default_detector: PIIDetector | None = None


def get_detector(settings: PIISettings | None = None) -> PIIDetector:
    """
    Get or create default PII detector.

    Args:
        settings: Settings for new detector. If None and no default
                  exists, creates with default settings.

    Returns:
        PIIDetector instance.
    """
    global _default_detector

    if settings is not None:
        return PIIDetector(settings)

    if _default_detector is None:
        _default_detector = PIIDetector()

    return _default_detector


async def detect_pii(text: str) -> PIIResult:
    """Convenience function to detect PII with default settings."""
    detector = get_detector()
    return await detector.detect(text)


async def redact_pii(text: str) -> str:
    """Convenience function to redact PII with default settings."""
    detector = get_detector()
    return await detector.redact(text)
