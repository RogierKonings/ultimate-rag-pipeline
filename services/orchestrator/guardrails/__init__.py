"""Guardrails module for input and output validation.

This module provides guardrails for:
- Input validation (length, prompt injection, PII detection)
- Output validation (length, harmful content filtering)
"""

from .detection import (
    DetectionMatch,
    detect_harmful_content,
    detect_injection,
    detect_pii,
)
from .input import InputGuardrail
from .models import (
    GuardrailConfig,
    GuardrailResult,
    PIIType,
    Violation,
    ViolationType,
)
from .output import OutputGuardrail
from .pipeline import GuardrailPipeline

__all__ = [
    # Models
    "ViolationType",
    "PIIType",
    "Violation",
    "GuardrailResult",
    "GuardrailConfig",
    # Detection utilities
    "DetectionMatch",
    "detect_pii",
    "detect_injection",
    "detect_harmful_content",
    # Guardrails
    "InputGuardrail",
    "OutputGuardrail",
    "GuardrailPipeline",
]
