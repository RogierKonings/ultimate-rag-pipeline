"""
Observability Validation Module.

Provides utilities for validating the observability stack:
- Trace-log correlation verification
- OTLP exporter validation
- Loki ingestion verification
- End-to-end smoke tests

Usage:
    from shared.observability.validation import (
        TraceLogValidator,
        OTLPValidator,
        LokiValidator,
        run_smoke_tests,
    )

    # Validate trace-log correlation
    validator = TraceLogValidator()
    result = await validator.validate_correlation(trace_id)
"""

from .trace_log import TraceLogValidator, CorrelationResult
from .otlp import OTLPValidator
from .loki import LokiValidator
from .smoke_tests import run_smoke_tests, SmokeTestResult

__all__ = [
    "TraceLogValidator",
    "CorrelationResult",
    "OTLPValidator",
    "LokiValidator",
    "run_smoke_tests",
    "SmokeTestResult",
]
