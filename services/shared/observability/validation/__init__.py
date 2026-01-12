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

from .loki import LokiValidator
from .otlp import OTLPValidator
from .smoke_tests import SmokeTestResult, run_smoke_tests
from .trace_log import CorrelationResult, TraceLogValidator

__all__ = [
    "TraceLogValidator",
    "CorrelationResult",
    "OTLPValidator",
    "LokiValidator",
    "run_smoke_tests",
    "SmokeTestResult",
]
