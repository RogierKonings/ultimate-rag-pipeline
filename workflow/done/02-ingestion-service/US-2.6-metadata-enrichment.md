# US-2.6: Metadata Enrichment

> **Story ID:** US-2.6  
> **Epic:** Ingestion Service  
> **Priority:** High  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-2.2 (Document Parsers)

## User Story

**As a** data engineer  
**I want** automatic metadata extraction  
**So that** documents have rich, filterable metadata

## Context

Documents need to be enriched with metadata for filtering, access control, and context. This includes extracting document properties (title, author, dates), detecting language, identifying PII for compliance, and injecting tenant/ACL information. The architecture specifies Microsoft Presidio for PII detection.

## Technical Requirements

### Directory Structure

```
ingestion-service/
└── processors/
    ├── enrichment.py         # Main enrichment pipeline
    ├── pii_detector.py       # PII detection with Presidio
    ├── language_detector.py  # Language detection
    └── __init__.py
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum

class PIIType(str, Enum):
    EMAIL = "EMAIL_ADDRESS"
    PHONE = "PHONE_NUMBER"
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    CREDIT_CARD = "CREDIT_CARD"
    SSN = "US_SSN"
    IP_ADDRESS = "IP_ADDRESS"
    DATE_TIME = "DATE_TIME"
    NRP = "NRP"  # Nationality, Religion, Political group
    MEDICAL = "MEDICAL_LICENSE"
    ORGANIZATION = "ORGANIZATION"

class PIIEntity(BaseModel):
    entity_type: PIIType
    text: str
    start: int
    end: int
    score: float  # Confidence score 0-1

class PIIResult(BaseModel):
    entities: list[PIIEntity]
    entity_counts: dict[str, int]
    has_pii: bool
    high_sensitivity: bool  # True if SSN, credit card, etc.

class LanguageResult(BaseModel):
    language_code: str  # ISO 639-1 (e.g., "en", "es", "de")
    language_name: str
    confidence: float

class DocumentMetadataEnriched(BaseModel):
    # Extracted from document
    title: Optional[str] = None
    author: Optional[str] = None
    created_date: Optional[datetime] = None
    modified_date: Optional[datetime] = None
    
    # Detected
    language: Optional[LanguageResult] = None
    pii: Optional[PIIResult] = None
    
    # Injected (from request/config)
    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = []
    allowed_users: list[str] = []
    
    # Custom fields
    custom: dict[str, Any] = {}
    
    # Processing info
    enriched_at: datetime = Field(default_factory=datetime.utcnow)
```

### Enrichment Pipeline

```python
from typing import Optional
from dataclasses import dataclass

@dataclass
class EnrichmentContext:
    """Context passed through enrichment pipeline."""
    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = None
    allowed_users: list[str] = None
    custom_metadata: dict = None
    
    def __post_init__(self):
        self.allowed_groups = self.allowed_groups or []
        self.allowed_users = self.allowed_users or []
        self.custom_metadata = self.custom_metadata or {}

class EnrichmentConfig(BaseModel):
    enable_language_detection: bool = True
    enable_pii_detection: bool = True
    pii_languages: list[str] = ["en"]  # Languages for PII detection
    pii_score_threshold: float = 0.7
    high_sensitivity_types: list[PIIType] = [
        PIIType.SSN,
        PIIType.CREDIT_CARD,
        PIIType.MEDICAL
    ]

class EnrichmentPipeline:
    """
    Pipeline for enriching documents with metadata.
    
    Stages:
    1. Extract document properties (from parser output)
    2. Detect language
    3. Detect PII
    4. Inject ACL metadata
    """
    
    def __init__(self, config: EnrichmentConfig = EnrichmentConfig()):
        self.config = config
        self._language_detector = LanguageDetector()
        self._pii_detector = PIIDetector(config) if config.enable_pii_detection else None
    
    async def enrich(
        self,
        parsed_doc: "ParsedDocument",
        context: EnrichmentContext
    ) -> DocumentMetadataEnriched:
        """
        Enrich a parsed document with metadata.
        
        Args:
            parsed_doc: Output from document parser
            context: Enrichment context with tenant/ACL info
        
        Returns:
            Enriched metadata
        """
        # Extract document properties
        title = parsed_doc.title
        author = parsed_doc.author
        created_date = self._parse_date(parsed_doc.created_date)
        modified_date = self._parse_date(parsed_doc.modified_date)
        
        # Detect language
        language = None
        if self.config.enable_language_detection and parsed_doc.text:
            language = await self._language_detector.detect(parsed_doc.text)
        
        # Detect PII
        pii = None
        if self._pii_detector and parsed_doc.text:
            pii = await self._pii_detector.detect(parsed_doc.text)
        
        return DocumentMetadataEnriched(
            title=title,
            author=author,
            created_date=created_date,
            modified_date=modified_date,
            language=language,
            pii=pii,
            tenant_id=context.tenant_id,
            visibility=context.visibility,
            allowed_groups=context.allowed_groups,
            allowed_users=context.allowed_users,
            custom=context.custom_metadata
        )
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None
        
        from dateutil import parser
        try:
            return parser.parse(date_str)
        except Exception:
            return None
```

### Language Detector

```python
from langdetect import detect, detect_langs
from langdetect.lang_detect_exception import LangDetectException

class LanguageDetector:
    """
    Detect document language using langdetect.
    """
    
    # ISO 639-1 code to language name mapping
    LANGUAGE_NAMES = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "ru": "Russian",
        "zh-cn": "Chinese (Simplified)",
        "zh-tw": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "ar": "Arabic",
        # Add more as needed
    }
    
    async def detect(self, text: str) -> Optional[LanguageResult]:
        """
        Detect the primary language of the text.
        
        Args:
            text: Text to analyze (should be at least 50 characters)
        
        Returns:
            LanguageResult with code, name, and confidence
        """
        if len(text) < 50:
            return None
        
        try:
            # Get top language with probabilities
            results = detect_langs(text)
            if not results:
                return None
            
            top = results[0]
            return LanguageResult(
                language_code=top.lang,
                language_name=self.LANGUAGE_NAMES.get(top.lang, "Unknown"),
                confidence=top.prob
            )
        except LangDetectException:
            return None
    
    async def detect_multiple(self, text: str) -> list[LanguageResult]:
        """
        Detect all languages in text with probabilities.
        
        Useful for multilingual documents.
        """
        try:
            results = detect_langs(text)
            return [
                LanguageResult(
                    language_code=r.lang,
                    language_name=self.LANGUAGE_NAMES.get(r.lang, "Unknown"),
                    confidence=r.prob
                )
                for r in results
            ]
        except LangDetectException:
            return []
```

### PII Detector with Presidio

```python
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from typing import Optional

class PIIDetectorConfig(BaseModel):
    languages: list[str] = ["en"]
    score_threshold: float = 0.7
    entities_to_detect: list[str] = [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PERSON",
        "LOCATION",
        "CREDIT_CARD",
        "US_SSN",
        "IP_ADDRESS",
        "ORGANIZATION"
    ]
    high_sensitivity_entities: list[str] = [
        "US_SSN",
        "CREDIT_CARD",
        "MEDICAL_LICENSE"
    ]

class PIIDetector:
    """
    Detect PII in text using Microsoft Presidio.
    
    Presidio is an open-source data protection SDK that:
    - Uses NLP for named entity recognition
    - Supports pattern matching for structured data (SSN, credit cards)
    - Is extensible with custom recognizers
    """
    
    def __init__(self, config: PIIDetectorConfig = PIIDetectorConfig()):
        self.config = config
        self._analyzer = self._create_analyzer()
    
    def _create_analyzer(self) -> AnalyzerEngine:
        """Initialize Presidio analyzer with spaCy NLP backend."""
        # Configure NLP engine
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": lang, "model_name": f"{lang}_core_web_sm"}
                for lang in self.config.languages
            ]
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
        # Run analysis
        results = self._analyzer.analyze(
            text=text,
            language=self.config.languages[0],  # Primary language
            entities=self.config.entities_to_detect,
            score_threshold=self.config.score_threshold
        )
        
        # Convert to our model
        entities = []
        entity_counts = {}
        has_high_sensitivity = False
        
        for result in results:
            entity = PIIEntity(
                entity_type=PIIType(result.entity_type),
                text=text[result.start:result.end],
                start=result.start,
                end=result.end,
                score=result.score
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
            high_sensitivity=has_high_sensitivity
        )
    
    async def redact(self, text: str) -> str:
        """
        Redact PII from text.
        
        Replaces PII with placeholder like [EMAIL_ADDRESS].
        """
        result = await self.detect(text)
        
        if not result.entities:
            return text
        
        # Sort by position (descending) to replace from end
        sorted_entities = sorted(result.entities, key=lambda e: e.start, reverse=True)
        
        redacted = text
        for entity in sorted_entities:
            placeholder = f"[{entity.entity_type.value}]"
            redacted = redacted[:entity.start] + placeholder + redacted[entity.end:]
        
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
        from presidio_anonymizer import AnonymizerEngine
        self._anonymizer = AnonymizerEngine()
    
    async def anonymize(
        self,
        text: str,
        entities: list[PIIEntity],
        strategy: str = "replace"
    ) -> str:
        """
        Anonymize detected PII entities.
        
        Args:
            text: Original text
            entities: PII entities detected by PIIDetector
            strategy: Anonymization strategy (replace, hash, mask)
        """
        from presidio_anonymizer.entities import RecognizerResult, OperatorConfig
        
        # Convert to Presidio format
        recognizer_results = [
            RecognizerResult(
                entity_type=e.entity_type.value,
                start=e.start,
                end=e.end,
                score=e.score
            )
            for e in entities
        ]
        
        # Configure operators
        operators = {}
        if strategy == "replace":
            operators = {"DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"})}
        elif strategy == "hash":
            operators = {"DEFAULT": OperatorConfig("hash")}
        elif strategy == "mask":
            operators = {"DEFAULT": OperatorConfig("mask", {"chars_to_mask": 4, "masking_char": "*"})}
        
        result = self._anonymizer.anonymize(
            text=text,
            analyzer_results=recognizer_results,
            operators=operators
        )
        
        return result.text
```

### Metadata Extraction Utilities

```python
from datetime import datetime
from typing import Optional, Any
import re

class MetadataExtractor:
    """
    Extract structured metadata from document content.
    """
    
    @staticmethod
    def extract_title_from_text(text: str, max_length: int = 200) -> Optional[str]:
        """
        Extract title from text if not provided by parser.
        
        Heuristics:
        - First non-empty line if it looks like a title
        - First heading marker (# in markdown)
        """
        lines = text.strip().split("\n")
        
        for line in lines[:5]:  # Check first 5 lines
            line = line.strip()
            if not line:
                continue
            
            # Markdown heading
            if line.startswith("# "):
                return line[2:].strip()[:max_length]
            
            # Short line that looks like a title (no period at end)
            if len(line) < max_length and not line.endswith("."):
                return line
        
        return None
    
    @staticmethod
    def extract_dates_from_text(text: str) -> list[datetime]:
        """
        Extract dates mentioned in text.
        
        Useful for documents without proper metadata.
        """
        from dateutil import parser
        from dateutil.parser import ParserError
        
        # Common date patterns
        date_patterns = [
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
            r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        ]
        
        dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    parsed = parser.parse(match, fuzzy=False)
                    dates.append(parsed)
                except (ParserError, ValueError):
                    continue
        
        return list(set(dates))  # Deduplicate
    
    @staticmethod
    def merge_metadata(
        base: dict[str, Any],
        override: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Merge metadata dictionaries.
        
        Override values take precedence, but None values don't overwrite.
        """
        result = base.copy()
        for key, value in override.items():
            if value is not None:
                result[key] = value
        return result
```

## Acceptance Criteria

- [ ] `EnrichmentPipeline` orchestrates all enrichment stages
- [ ] Document properties (title, author, dates) extracted from parser output
- [ ] `LanguageDetector` correctly identifies document language
- [ ] `PIIDetector` identifies all configured PII types using Presidio
- [ ] PII detection returns confidence scores
- [ ] High-sensitivity PII (SSN, credit cards) flagged separately
- [ ] Tenant/ACL metadata injected from context
- [ ] Custom metadata fields supported
- [ ] `PIIAnonymizer` can redact or mask PII
- [ ] Metadata extraction utilities work for edge cases

## Testing Requirements

```python
import pytest

@pytest.fixture
def enrichment_pipeline():
    return EnrichmentPipeline()

@pytest.fixture
def pii_detector():
    return PIIDetector()

@pytest.mark.asyncio
async def test_language_detection():
    detector = LanguageDetector()
    
    english_text = "The quick brown fox jumps over the lazy dog. This is a sample English text for testing."
    result = await detector.detect(english_text)
    
    assert result is not None
    assert result.language_code == "en"
    assert result.confidence > 0.9

@pytest.mark.asyncio
async def test_pii_detection_email(pii_detector):
    text = "Contact me at john.doe@example.com for more information."
    result = await pii_detector.detect(text)
    
    assert result.has_pii
    assert "EMAIL_ADDRESS" in result.entity_counts
    assert result.entities[0].text == "john.doe@example.com"

@pytest.mark.asyncio
async def test_pii_detection_phone(pii_detector):
    text = "Call me at (555) 123-4567 to discuss the project."
    result = await pii_detector.detect(text)
    
    assert result.has_pii
    assert "PHONE_NUMBER" in result.entity_counts

@pytest.mark.asyncio
async def test_pii_detection_ssn_high_sensitivity(pii_detector):
    text = "My SSN is 123-45-6789."
    result = await pii_detector.detect(text)
    
    assert result.has_pii
    assert result.high_sensitivity
    assert "US_SSN" in result.entity_counts

@pytest.mark.asyncio
async def test_enrichment_pipeline(enrichment_pipeline):
    from processors.parsers.base import ParsedDocument
    
    parsed_doc = ParsedDocument(
        text="Hello, I am John Doe and my email is john@example.com. This document was written in English.",
        blocks=[],
        tables=[],
        title="Test Document",
        author="Jane Smith"
    )
    
    context = EnrichmentContext(
        tenant_id="tenant-123",
        visibility="group",
        allowed_groups=["engineering", "product"]
    )
    
    result = await enrichment_pipeline.enrich(parsed_doc, context)
    
    assert result.title == "Test Document"
    assert result.author == "Jane Smith"
    assert result.tenant_id == "tenant-123"
    assert result.visibility == "group"
    assert "engineering" in result.allowed_groups
    assert result.language.language_code == "en"
    assert result.pii.has_pii

@pytest.mark.asyncio
async def test_pii_redaction(pii_detector):
    text = "Contact john.doe@example.com or call 555-123-4567"
    result = await pii_detector.detect(text)
    
    anonymizer = PIIAnonymizer()
    redacted = await anonymizer.anonymize(text, result.entities)
    
    assert "john.doe@example.com" not in redacted
    assert "555-123-4567" not in redacted
    assert "[REDACTED]" in redacted
```

## Dependencies

- `presidio-analyzer>=2.2.0`
- `presidio-anonymizer>=2.2.0`
- `langdetect>=1.0.9`
- `python-dateutil>=2.8.0`
- `spacy>=3.7.0`
- `pydantic>=2.0.0`

Also requires spaCy model:
```bash
python -m spacy download en_core_web_sm
```

## Definition of Done

- [ ] Enrichment pipeline fully functional
- [ ] Language detection accurate for major languages
- [ ] PII detection catches all configured entity types
- [ ] Presidio integrated correctly
- [ ] ACL metadata properly injected
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
- [ ] Performance acceptable (< 1s for typical document)
