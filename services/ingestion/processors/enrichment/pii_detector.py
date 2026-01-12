"""PII detection and anonymization using Microsoft Presidio."""

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig, RecognizerResult
from pydantic import BaseModel, Field

from .models import PIIEntity, PIIResult, PIIType


class PIIDetectorConfig(BaseModel):
    """Configuration for PII detection."""

    languages: list[str] = Field(default_factory=lambda: ["en"])
    score_threshold: float = 0.7
    entities_to_detect: list[str] = Field(
        default_factory=lambda: [
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "PERSON",
            "LOCATION",
            "CREDIT_CARD",
            "US_SSN",
            "IP_ADDRESS",
            "ORGANIZATION",
        ],
    )
    high_sensitivity_entities: list[str] = Field(
        default_factory=lambda: [
            "US_SSN",
            "CREDIT_CARD",
            "MEDICAL_LICENSE",
        ],
    )


class PIIDetector:
    """
    Detect PII in text using Microsoft Presidio.

    Presidio is an open-source data protection SDK that:
    - Uses NLP for named entity recognition
    - Supports pattern matching for structured data (SSN, credit cards)
    - Is extensible with custom recognizers
    """

    def __init__(self, config: PIIDetectorConfig | None = None):
        """
        Initialize the PII detector.

        Args:
            config: Configuration for PII detection. If None, uses defaults.
        """
        self.config = config or PIIDetectorConfig()
        self._analyzer: AnalyzerEngine | None = None

    def _get_analyzer(self) -> AnalyzerEngine:
        """
        Lazily initialize the Presidio analyzer.

        This is done lazily because spaCy model loading is expensive.
        """
        if self._analyzer is None:
            self._analyzer = self._create_analyzer()
        return self._analyzer

    def _create_analyzer(self) -> AnalyzerEngine:
        """Initialize Presidio analyzer with spaCy NLP backend."""
        # Configure NLP engine with spaCy models for each language
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": lang, "model_name": f"{lang}_core_web_sm"}
                for lang in self.config.languages
            ],
        }

        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()

        return AnalyzerEngine(nlp_engine=nlp_engine)

    async def detect(self, text: str) -> PIIResult:
        """
        Detect PII entities in text.

        Args:
            text: Text to scan for PII

        Returns:
            PIIResult with entities and counts
        """
        analyzer = self._get_analyzer()

        # Run analysis
        results = analyzer.analyze(
            text=text,
            language=self.config.languages[0],  # Primary language
            entities=self.config.entities_to_detect,
            score_threshold=self.config.score_threshold,
        )

        # Convert to our model
        entities: list[PIIEntity] = []
        entity_counts: dict[str, int] = {}
        has_high_sensitivity = False

        for result in results:
            # Map entity type to our enum, skip unknown types
            try:
                pii_type = PIIType(result.entity_type)
            except ValueError:
                # Unknown entity type, skip
                continue

            entity = PIIEntity(
                entity_type=pii_type,
                text=text[result.start : result.end],
                start=result.start,
                end=result.end,
                score=result.score,
            )
            entities.append(entity)

            # Count by type
            entity_counts[result.entity_type] = entity_counts.get(result.entity_type, 0) + 1

            # Check high sensitivity
            if result.entity_type in self.config.high_sensitivity_entities:
                has_high_sensitivity = True

        return PIIResult(
            entities=entities,
            entity_counts=entity_counts,
            has_pii=len(entities) > 0,
            high_sensitivity=has_high_sensitivity,
        )

    async def redact(self, text: str) -> str:
        """
        Redact PII from text.

        Replaces PII with placeholder like [EMAIL_ADDRESS].

        Args:
            text: Text containing PII

        Returns:
            Text with PII replaced by placeholders
        """
        result = await self.detect(text)

        if not result.entities:
            return text

        # Sort by position (descending) to replace from end
        sorted_entities = sorted(
            result.entities,
            key=lambda e: e.start,
            reverse=True,
        )

        redacted = text
        for entity in sorted_entities:
            placeholder = f"[{entity.entity_type.value}]"
            redacted = redacted[: entity.start] + placeholder + redacted[entity.end :]

        return redacted


class PIIAnonymizer:
    """
    Anonymize PII in text using Presidio Anonymizer.

    Supports various anonymization strategies:
    - Replace: Replace with placeholder
    - Hash: Replace with hash of value
    - Mask: Partially mask value
    - Encrypt: Encrypt value (reversible)
    """

    def __init__(self):
        """Initialize the anonymizer engine."""
        self._anonymizer = AnonymizerEngine()

    async def anonymize(
        self,
        text: str,
        entities: list[PIIEntity],
        strategy: str = "replace",
    ) -> str:
        """
        Anonymize detected PII entities.

        Args:
            text: Original text
            entities: PII entities detected by PIIDetector
            strategy: Anonymization strategy (replace, hash, mask)

        Returns:
            Anonymized text
        """
        if not entities:
            return text

        # Convert to Presidio format
        recognizer_results = [
            RecognizerResult(
                entity_type=e.entity_type.value,
                start=e.start,
                end=e.end,
                score=e.score,
            )
            for e in entities
        ]

        # Configure operators based on strategy
        operators: dict[str, OperatorConfig] = {}
        if strategy == "replace":
            operators = {
                "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            }
        elif strategy == "hash":
            operators = {"DEFAULT": OperatorConfig("hash")}
        elif strategy == "mask":
            operators = {
                "DEFAULT": OperatorConfig(
                    "mask",
                    {"chars_to_mask": 4, "masking_char": "*"},
                ),
            }

        result = self._anonymizer.anonymize(
            text=text,
            analyzer_results=recognizer_results,
            operators=operators,
        )

        return result.text
