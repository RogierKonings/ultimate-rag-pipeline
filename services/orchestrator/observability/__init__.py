"""Observability module for the Orchestrator Service.

This module provides metrics, tracing, and logging utilities.
"""

from observability.llm_metrics import (
    llm_model_fallbacks,
    llm_request_duration,
    llm_requests_by_model,
    record_llm_duration,
    record_llm_request,
    record_model_fallback,
)

__all__ = [
    "llm_requests_by_model",
    "llm_request_duration",
    "llm_model_fallbacks",
    "record_llm_request",
    "record_llm_duration",
    "record_model_fallback",
]
