#!/usr/bin/env python
"""Run the ingestion service."""

import uvicorn

from config import get_settings
from shared.observability.otel.tracer import setup_auto_instrumentation, setup_tracing

if __name__ == "__main__":
    settings = get_settings()

    # Initialize OpenTelemetry tracing and auto-instrumentation
    setup_tracing(service_name="ingestion")
    setup_auto_instrumentation()

    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )
