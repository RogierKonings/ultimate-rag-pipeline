# US-7.6: PII Detection & Handling

> **Epic:** Security & Compliance  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** Epic 2 (Ingestion Service)

## User Story

**As a** compliance officer  
**I want** PII detected during document ingestion  
**So that** sensitive data is handled appropriately according to privacy regulations

## Objective

Integrate Microsoft Presidio for PII detection during document ingestion, supporting detection of names, emails, SSN, phone numbers, and other sensitive data types. Implement configurable handling strategies (redact, flag, reject) and ensure PII metadata is tracked for compliance.

## Architecture Reference

- **Detection Engine:** Microsoft Presidio
- **Integration Point:** Ingestion pipeline (post-chunking)
- **Handling Modes:** Redact, Flag, Reject, Encrypt
- **Languages:** English (extensible to other languages)
- **Custom Recognizers:** Support for domain-specific PII

## Implementation Tasks

### 1. Configure PII Detection Settings

`services/shared/security/pii/config.py`:

```python
from pydantic_settings import BaseSettings
from typing import List, Optional, Dict
from enum import Enum
from functools import lru_cache


class PIIHandlingMode(str, Enum):
    REDACT = "redact"       # Replace PII with placeholder
    MASK = "mask"           # Partial masking (e.g., john***@email.com)
    FLAG = "flag"           # Mark document but keep PII
    REJECT = "reject"       # Reject document with PII
    ENCRYPT = "encrypt"     # Encrypt PII in place
    PASSTHROUGH = "passthrough"  # Allow PII (for non-sensitive use cases)


class PIISettings(BaseSettings):
    # Detection settings
    pii_detection_enabled: bool = True
    pii_confidence_threshold: float = 0.8  # Minimum confidence for detection
    pii_languages: List[str] = ["en"]
    
    # Handling mode
    pii_handling_mode: PIIHandlingMode = PIIHandlingMode.REDACT
    
    # Entity types to detect
    pii_entities: List[str] = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
        "US_PASSPORT",
        "US_DRIVER_LICENSE",
        "IP_ADDRESS",
        "IBAN_CODE",
        "MEDICAL_LICENSE",
        "DATE_TIME",
        "LOCATION",
        "NRP",  # Nationality, Religious, Political groups
    ]
    
    # Entity-specific handling overrides
    pii_entity_overrides: Dict[str, PIIHandlingMode] = {}
    
    # Redaction settings
    redaction_placeholder: str = "[REDACTED]"
    redaction_with_type: bool = True  # e.g., [REDACTED:EMAIL]
    
    # Custom recognizers
    custom_recognizers_path: Optional[str] = None
    
    # Audit settings
    log_pii_detections: bool = True
    store_pii_locations: bool = True  # Store character offsets
    
    class Config:
        env_prefix = ""


@lru_cache()
def get_pii_settings() -> PIISettings:
    return PIISettings()
```

### 2. Create PII Detector with Presidio

`services/shared/security/pii/detector.py`:

```python
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from presidio_analyzer import AnalyzerEngine, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import structlog

from .config import PIISettings, PIIHandlingMode, get_pii_settings

logger = structlog.get_logger(__name__)


@dataclass
class PIIDetection:
    """Represents a detected PII entity."""
    entity_type: str
    text: str
    start: int
    end: int
    score: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "score": self.score,
        }


@dataclass
class PIIAnalysisResult:
    """Result of PII analysis on text."""
    original_text: str
    processed_text: str
    detections: List[PIIDetection]
    handling_mode: PIIHandlingMode
    has_pii: bool
    pii_count: int
    entity_counts: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_pii": self.has_pii,
            "pii_count": self.pii_count,
            "entity_counts": self.entity_counts,
            "handling_mode": self.handling_mode.value,
            "detections": [d.to_dict() for d in self.detections] if self.detections else [],
        }


class PIIDetector:
    """PII detection and handling using Microsoft Presidio."""
    
    def __init__(self, settings: Optional[PIISettings] = None):
        self.settings = settings or get_pii_settings()
        
        if not self.settings.pii_detection_enabled:
            self._analyzer = None
            self._anonymizer = None
            return
        
        # Initialize NLP engine
        nlp_config = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": lang, "model_name": f"{lang}_core_web_lg"}
                for lang in self.settings.pii_languages
            ],
        }
        
        provider = NlpEngineProvider(nlp_configuration=nlp_config)
        nlp_engine = provider.create_engine()
        
        # Initialize analyzer
        self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        
        # Load custom recognizers if configured
        if self.settings.custom_recognizers_path:
            self._load_custom_recognizers()
        
        # Initialize anonymizer
        self._anonymizer = AnonymizerEngine()
        
        logger.info(
            "pii_detector_initialized",
            entities=self.settings.pii_entities,
            languages=self.settings.pii_languages,
            handling_mode=self.settings.pii_handling_mode.value,
        )
    
    def _load_custom_recognizers(self):
        """Load custom recognizers from configuration."""
        import yaml
        from presidio_analyzer import PatternRecognizer, Pattern
        
        with open(self.settings.custom_recognizers_path) as f:
            custom_config = yaml.safe_load(f)
        
        for recognizer_config in custom_config.get("recognizers", []):
            patterns = [
                Pattern(
                    name=p["name"],
                    regex=p["regex"],
                    score=p.get("score", 0.5),
                )
                for p in recognizer_config.get("patterns", [])
            ]
            
            recognizer = PatternRecognizer(
                supported_entity=recognizer_config["entity_type"],
                patterns=patterns,
                supported_language=recognizer_config.get("language", "en"),
            )
            
            self._analyzer.registry.add_recognizer(recognizer)
            logger.info("custom_recognizer_loaded", entity=recognizer_config["entity_type"])
    
    def analyze(self, text: str, language: str = "en") -> PIIAnalysisResult:
        """Analyze text for PII and return processed result."""
        if not self.settings.pii_detection_enabled or not self._analyzer:
            return PIIAnalysisResult(
                original_text=text,
                processed_text=text,
                detections=[],
                handling_mode=PIIHandlingMode.PASSTHROUGH,
                has_pii=False,
                pii_count=0,
                entity_counts={},
            )
        
        # Run PII detection
        results = self._analyzer.analyze(
            text=text,
            entities=self.settings.pii_entities,
            language=language,
        )
        
        # Filter by confidence threshold
        filtered_results = [
            r for r in results
            if r.score >= self.settings.pii_confidence_threshold
        ]
        
        # Convert to detection objects
        detections = [
            PIIDetection(
                entity_type=r.entity_type,
                text=text[r.start:r.end],
                start=r.start,
                end=r.end,
                score=r.score,
            )
            for r in filtered_results
        ]
        
        # Count by entity type
        entity_counts = {}
        for d in detections:
            entity_counts[d.entity_type] = entity_counts.get(d.entity_type, 0) + 1
        
        # Process text based on handling mode
        processed_text = self._process_text(text, filtered_results)
        
        result = PIIAnalysisResult(
            original_text=text,
            processed_text=processed_text,
            detections=detections if self.settings.store_pii_locations else [],
            handling_mode=self.settings.pii_handling_mode,
            has_pii=len(detections) > 0,
            pii_count=len(detections),
            entity_counts=entity_counts,
        )
        
        if self.settings.log_pii_detections and result.has_pii:
            logger.info(
                "pii_detected",
                pii_count=result.pii_count,
                entity_counts=entity_counts,
                handling_mode=self.settings.pii_handling_mode.value,
            )
        
        return result
    
    def _process_text(
        self,
        text: str,
        results: List[RecognizerResult],
    ) -> str:
        """Process text based on handling mode."""
        if not results:
            return text
        
        mode = self.settings.pii_handling_mode
        
        if mode == PIIHandlingMode.PASSTHROUGH:
            return text
        
        if mode == PIIHandlingMode.REJECT:
            # Return original - rejection handled at pipeline level
            return text
        
        if mode == PIIHandlingMode.FLAG:
            # Return original - flagging handled at metadata level
            return text
        
        if mode == PIIHandlingMode.REDACT:
            return self._redact_text(text, results)
        
        if mode == PIIHandlingMode.MASK:
            return self._mask_text(text, results)
        
        if mode == PIIHandlingMode.ENCRYPT:
            # Encryption handled separately
            return text
        
        return text
    
    def _redact_text(
        self,
        text: str,
        results: List[RecognizerResult],
    ) -> str:
        """Redact PII from text."""
        operators = {}
        
        for result in results:
            # Check for entity-specific override
            entity_mode = self.settings.pii_entity_overrides.get(
                result.entity_type,
                self.settings.pii_handling_mode,
            )
            
            if entity_mode == PIIHandlingMode.PASSTHROUGH:
                continue
            
            if self.settings.redaction_with_type:
                placeholder = f"[REDACTED:{result.entity_type}]"
            else:
                placeholder = self.settings.redaction_placeholder
            
            operators[result.entity_type] = OperatorConfig(
                "replace",
                {"new_value": placeholder}
            )
        
        if not operators:
            return text
        
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
        )
        
        return anonymized.text
    
    def _mask_text(
        self,
        text: str,
        results: List[RecognizerResult],
    ) -> str:
        """Partially mask PII in text."""
        operators = {}
        
        for result in results:
            # Mask middle portion
            operators[result.entity_type] = OperatorConfig(
                "mask",
                {
                    "type": "mask",
                    "masking_char": "*",
                    "chars_to_mask": max(1, (result.end - result.start) - 4),
                    "from_end": False,
                }
            )
        
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
        )
        
        return anonymized.text
    
    def detect_only(self, text: str, language: str = "en") -> List[PIIDetection]:
        """Detect PII without processing."""
        result = self.analyze(text, language)
        return result.detections


# Singleton instance
_pii_detector: Optional[PIIDetector] = None


def get_pii_detector() -> PIIDetector:
    global _pii_detector
    if _pii_detector is None:
        _pii_detector = PIIDetector()
    return _pii_detector
```

### 3. Create Custom Recognizers Configuration

`services/shared/security/pii/custom_recognizers.yaml`:

```yaml
recognizers:
  # Internal employee ID pattern
  - entity_type: EMPLOYEE_ID
    language: en
    patterns:
      - name: employee_id_pattern
        regex: "EMP-\\d{6}"
        score: 0.9
  
  # Internal project codes
  - entity_type: PROJECT_CODE
    language: en
    patterns:
      - name: project_code_pattern
        regex: "PROJ-[A-Z]{3}-\\d{4}"
        score: 0.85
  
  # API Keys (generic pattern)
  - entity_type: API_KEY
    language: en
    patterns:
      - name: api_key_pattern
        regex: "(?:api[_-]?key|apikey)[\\s:=]+['\"]?([a-zA-Z0-9]{32,})['\"]?"
        score: 0.9
  
  # AWS Access Keys
  - entity_type: AWS_ACCESS_KEY
    language: en
    patterns:
      - name: aws_access_key
        regex: "AKIA[0-9A-Z]{16}"
        score: 0.95
  
  # Private Keys
  - entity_type: PRIVATE_KEY
    language: en
    patterns:
      - name: private_key_header
        regex: "-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"
        score: 0.99
```

### 4. Integrate PII Detection in Ingestion Pipeline

`services/ingestion/processors/pii_processor.py`:

```python
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import structlog

from shared.security.pii.detector import (
    PIIDetector,
    PIIAnalysisResult,
    get_pii_detector,
)
from shared.security.pii.config import PIIHandlingMode, get_pii_settings

logger = structlog.get_logger(__name__)


@dataclass
class ChunkPIIResult:
    """PII processing result for a chunk."""
    chunk_id: str
    original_content: str
    processed_content: str
    has_pii: bool
    pii_count: int
    entity_counts: Dict[str, int]
    should_reject: bool
    pii_metadata: Dict[str, Any]


class PIIProcessor:
    """Process chunks for PII during ingestion."""
    
    def __init__(self, detector: Optional[PIIDetector] = None):
        self.detector = detector or get_pii_detector()
        self.settings = get_pii_settings()
    
    def process_chunk(
        self,
        chunk_id: str,
        content: str,
        language: str = "en",
    ) -> ChunkPIIResult:
        """Process a single chunk for PII."""
        result = self.detector.analyze(content, language)
        
        pii_metadata = {
            "pii_detected": result.has_pii,
            "pii_count": result.pii_count,
            "entity_counts": result.entity_counts,
            "handling_mode": result.handling_mode.value,
        }
        
        if result.has_pii and self.settings.store_pii_locations:
            # Store detection locations (without actual PII text)
            pii_metadata["detection_locations"] = [
                {
                    "entity_type": d.entity_type,
                    "start": d.start,
                    "end": d.end,
                    "score": d.score,
                }
                for d in result.detections
            ]
        
        return ChunkPIIResult(
            chunk_id=chunk_id,
            original_content=content,
            processed_content=result.processed_text,
            has_pii=result.has_pii,
            pii_count=result.pii_count,
            entity_counts=result.entity_counts,
            should_reject=result.handling_mode == PIIHandlingMode.REJECT and result.has_pii,
            pii_metadata=pii_metadata,
        )
    
    def process_chunks(
        self,
        chunks: List[Dict[str, Any]],
        language: str = "en",
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Process multiple chunks and return processed chunks + document-level PII summary.
        
        Returns:
            Tuple of (processed_chunks, document_pii_summary)
        """
        processed_chunks = []
        document_pii_count = 0
        document_entity_counts: Dict[str, int] = {}
        chunks_with_pii = 0
        rejected_chunks = []
        
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", str(len(processed_chunks)))
            content = chunk.get("content", "")
            
            result = self.process_chunk(chunk_id, content, language)
            
            if result.should_reject:
                rejected_chunks.append(chunk_id)
                logger.warning(
                    "chunk_rejected_pii",
                    chunk_id=chunk_id,
                    pii_count=result.pii_count,
                    entities=list(result.entity_counts.keys()),
                )
                continue
            
            # Update document-level stats
            if result.has_pii:
                chunks_with_pii += 1
                document_pii_count += result.pii_count
                for entity, count in result.entity_counts.items():
                    document_entity_counts[entity] = document_entity_counts.get(entity, 0) + count
            
            # Create processed chunk
            processed_chunk = {
                **chunk,
                "content": result.processed_content,
                "pii_metadata": result.pii_metadata,
            }
            processed_chunks.append(processed_chunk)
        
        document_summary = {
            "total_chunks": len(chunks),
            "processed_chunks": len(processed_chunks),
            "rejected_chunks": len(rejected_chunks),
            "rejected_chunk_ids": rejected_chunks,
            "chunks_with_pii": chunks_with_pii,
            "total_pii_detections": document_pii_count,
            "entity_counts": document_entity_counts,
            "handling_mode": self.settings.pii_handling_mode.value,
        }
        
        logger.info(
            "document_pii_processed",
            total_chunks=len(chunks),
            processed=len(processed_chunks),
            rejected=len(rejected_chunks),
            pii_count=document_pii_count,
        )
        
        return processed_chunks, document_summary
    
    def should_reject_document(self, document_summary: Dict[str, Any]) -> bool:
        """Determine if entire document should be rejected based on PII."""
        if self.settings.pii_handling_mode != PIIHandlingMode.REJECT:
            return False
        
        # Reject if any chunks were rejected
        return document_summary.get("rejected_chunks", 0) > 0


class PIIPipelineStep:
    """Pipeline step for PII processing in ingestion workflow."""
    
    def __init__(self):
        self.processor = PIIProcessor()
    
    async def process(
        self,
        document_id: str,
        chunks: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute PII processing step."""
        language = metadata.get("language", "en")
        
        processed_chunks, pii_summary = self.processor.process_chunks(
            chunks=chunks,
            language=language,
        )
        
        # Update document metadata
        updated_metadata = {
            **metadata,
            "pii_analysis": pii_summary,
        }
        
        # Check for document rejection
        if self.processor.should_reject_document(pii_summary):
            raise PIIRejectionError(
                f"Document {document_id} rejected due to PII content",
                document_id=document_id,
                pii_summary=pii_summary,
            )
        
        return processed_chunks, updated_metadata


class PIIRejectionError(Exception):
    """Raised when document is rejected due to PII."""
    
    def __init__(self, message: str, document_id: str, pii_summary: Dict[str, Any]):
        super().__init__(message)
        self.document_id = document_id
        self.pii_summary = pii_summary
```

### 5. Create PII Filtering for Query Responses

`services/shared/security/pii/response_filter.py`:

```python
from typing import List, Dict, Any, Optional
import structlog

from .detector import PIIDetector, get_pii_detector
from .config import PIIHandlingMode, get_pii_settings

logger = structlog.get_logger(__name__)


class PIIResponseFilter:
    """Filter PII from query responses."""
    
    def __init__(self, detector: Optional[PIIDetector] = None):
        self.detector = detector or get_pii_detector()
        self.settings = get_pii_settings()
    
    def filter_response(
        self,
        response_text: str,
        language: str = "en",
    ) -> str:
        """Filter PII from LLM response text."""
        if not self.settings.pii_detection_enabled:
            return response_text
        
        result = self.detector.analyze(response_text, language)
        
        if result.has_pii:
            logger.info(
                "pii_filtered_from_response",
                pii_count=result.pii_count,
                entities=list(result.entity_counts.keys()),
            )
        
        return result.processed_text
    
    def filter_search_results(
        self,
        results: List[Dict[str, Any]],
        language: str = "en",
    ) -> List[Dict[str, Any]]:
        """Filter PII from search result snippets."""
        filtered_results = []
        
        for result in results:
            content = result.get("content", "")
            filtered_content = self.filter_response(content, language)
            
            filtered_result = {
                **result,
                "content": filtered_content,
            }
            filtered_results.append(filtered_result)
        
        return filtered_results
```

### 6. Create PII API Endpoints

`services/api-gateway/routers/pii.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

from shared.security.jwt.models import TokenClaims
from shared.security.jwt.middleware import get_current_user
from shared.security.rbac.middleware import require_permission
from shared.security.rbac.permissions import Permission
from shared.security.pii.detector import get_pii_detector, PIIDetector
from shared.security.pii.config import get_pii_settings, PIIHandlingMode

router = APIRouter(prefix="/pii", tags=["pii"])


class PIIAnalyzeRequest(BaseModel):
    text: str
    language: str = "en"


class PIIAnalyzeResponse(BaseModel):
    has_pii: bool
    pii_count: int
    entity_counts: Dict[str, int]
    processed_text: str
    detections: List[Dict[str, Any]]


@router.post("/analyze", response_model=PIIAnalyzeResponse)
async def analyze_text(
    request: PIIAnalyzeRequest,
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_READ)),
    detector: PIIDetector = Depends(get_pii_detector),
):
    """Analyze text for PII (for testing/validation)."""
    result = detector.analyze(request.text, request.language)
    
    return PIIAnalyzeResponse(
        has_pii=result.has_pii,
        pii_count=result.pii_count,
        entity_counts=result.entity_counts,
        processed_text=result.processed_text,
        detections=[d.to_dict() for d in result.detections],
    )


@router.get("/config")
async def get_pii_config(
    user: TokenClaims = Depends(require_permission(Permission.TENANT_READ)),
):
    """Get current PII detection configuration."""
    settings = get_pii_settings()
    
    return {
        "enabled": settings.pii_detection_enabled,
        "handling_mode": settings.pii_handling_mode.value,
        "confidence_threshold": settings.pii_confidence_threshold,
        "entities": settings.pii_entities,
        "languages": settings.pii_languages,
    }


@router.get("/entities")
async def list_supported_entities(
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_READ)),
    detector: PIIDetector = Depends(get_pii_detector),
):
    """List all supported PII entity types."""
    if not detector._analyzer:
        return {"entities": []}
    
    entities = detector._analyzer.get_supported_entities()
    return {"entities": entities}
```

### 7. Create Tests

`tests/security/test_pii_detection.py`:

```python
import pytest
from shared.security.pii.detector import PIIDetector, PIIAnalysisResult
from shared.security.pii.config import PIISettings, PIIHandlingMode


@pytest.fixture
def pii_settings():
    return PIISettings(
        pii_detection_enabled=True,
        pii_confidence_threshold=0.5,
        pii_handling_mode=PIIHandlingMode.REDACT,
        pii_entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN"],
        pii_languages=["en"],
    )


@pytest.fixture
def pii_detector(pii_settings):
    return PIIDetector(settings=pii_settings)


class TestPIIDetector:
    def test_detect_email(self, pii_detector):
        text = "Contact me at john.doe@example.com for more info."
        result = pii_detector.analyze(text)
        
        assert result.has_pii is True
        assert result.pii_count >= 1
        assert "EMAIL_ADDRESS" in result.entity_counts
    
    def test_detect_person_name(self, pii_detector):
        text = "John Smith works at the company."
        result = pii_detector.analyze(text)
        
        assert result.has_pii is True
        assert "PERSON" in result.entity_counts
    
    def test_detect_phone_number(self, pii_detector):
        text = "Call me at 555-123-4567."
        result = pii_detector.analyze(text)
        
        assert result.has_pii is True
        assert "PHONE_NUMBER" in result.entity_counts
    
    def test_detect_ssn(self, pii_detector):
        text = "My SSN is 123-45-6789."
        result = pii_detector.analyze(text)
        
        assert result.has_pii is True
        assert "US_SSN" in result.entity_counts
    
    def test_redaction(self, pii_detector):
        text = "Email john@example.com"
        result = pii_detector.analyze(text)
        
        assert "[REDACTED:EMAIL_ADDRESS]" in result.processed_text
        assert "john@example.com" not in result.processed_text
    
    def test_no_pii(self, pii_detector):
        text = "This is a generic technical document about software."
        result = pii_detector.analyze(text)
        
        assert result.has_pii is False
        assert result.pii_count == 0
    
    def test_multiple_pii_types(self, pii_detector):
        text = "John Doe (john@example.com, 555-123-4567) applied."
        result = pii_detector.analyze(text)
        
        assert result.has_pii is True
        assert result.pii_count >= 3
        assert "PERSON" in result.entity_counts
        assert "EMAIL_ADDRESS" in result.entity_counts
        assert "PHONE_NUMBER" in result.entity_counts
    
    def test_confidence_threshold(self):
        high_threshold_settings = PIISettings(
            pii_detection_enabled=True,
            pii_confidence_threshold=0.99,  # Very high
            pii_handling_mode=PIIHandlingMode.REDACT,
        )
        detector = PIIDetector(settings=high_threshold_settings)
        
        text = "Maybe john@example.com"
        result = detector.analyze(text)
        
        # With very high threshold, fewer detections expected
        # (depends on actual model confidence)
    
    def test_passthrough_mode(self):
        settings = PIISettings(
            pii_detection_enabled=True,
            pii_handling_mode=PIIHandlingMode.PASSTHROUGH,
        )
        detector = PIIDetector(settings=settings)
        
        text = "john@example.com"
        result = detector.analyze(text)
        
        assert result.processed_text == text  # Unchanged
        assert result.has_pii is True  # Still detected
    
    def test_disabled_detection(self):
        settings = PIISettings(pii_detection_enabled=False)
        detector = PIIDetector(settings=settings)
        
        text = "john@example.com"
        result = detector.analyze(text)
        
        assert result.has_pii is False
        assert result.processed_text == text


class TestPIIProcessor:
    def test_process_chunks(self, pii_detector):
        from shared.security.pii.detector import PIIProcessor
        
        processor = PIIProcessor(detector=pii_detector)
        
        chunks = [
            {"chunk_id": "1", "content": "Contact john@example.com"},
            {"chunk_id": "2", "content": "Generic technical content"},
            {"chunk_id": "3", "content": "Call 555-123-4567"},
        ]
        
        processed, summary = processor.process_chunks(chunks)
        
        assert len(processed) == 3
        assert summary["chunks_with_pii"] == 2
        assert summary["total_pii_detections"] >= 2
```

## Acceptance Criteria

- [ ] Presidio integration working for PII detection
- [ ] Detection of names, emails, SSN, phone numbers, etc.
- [ ] Configurable handling modes (redact, flag, reject)
- [ ] PII metadata stored with chunks
- [ ] PII filtering in query responses
- [ ] Custom recognizers support
- [ ] PII analysis API endpoint
- [ ] Unit tests for detection passing
- [ ] Integration with ingestion pipeline

## Verification Commands

```bash
# Install Presidio dependencies
pip install presidio-analyzer presidio-anonymizer
python -m spacy download en_core_web_lg

# Run PII tests
pytest tests/security/test_pii_detection.py -v

# Test PII detection API
curl -X POST "http://localhost:8000/pii/analyze" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Contact john@example.com or call 555-123-4567"}'

# Check PII config
curl -X GET "http://localhost:8000/pii/config" \
  -H "Authorization: Bearer $TOKEN"
```

## Environment Variables

```bash
# PII Detection
PII_DETECTION_ENABLED=true
PII_CONFIDENCE_THRESHOLD=0.8
PII_HANDLING_MODE=redact
PII_LANGUAGES=en

# Redaction
REDACTION_PLACEHOLDER=[REDACTED]
REDACTION_WITH_TYPE=true

# Custom recognizers
CUSTOM_RECOGNIZERS_PATH=/config/custom_recognizers.yaml
```

## Files to Create

1. `services/shared/security/pii/__init__.py`
2. `services/shared/security/pii/config.py`
3. `services/shared/security/pii/detector.py`
4. `services/shared/security/pii/custom_recognizers.yaml`
5. `services/shared/security/pii/response_filter.py`
6. `services/ingestion/processors/pii_processor.py`
7. `services/api-gateway/routers/pii.py`
8. `tests/security/test_pii_detection.py`

## Security Considerations

- **Never log PII** - Only log detection counts, not actual values
- **Secure training data** - If using custom models, protect training data
- **False positives** - Balance sensitivity vs. over-detection
- **Performance** - PII detection adds processing overhead
- **Audit trail** - Track who accessed documents with PII flags
- **Data residency** - Consider where PII analysis occurs
