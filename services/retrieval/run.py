"""Entry point for the Retrieval Service."""

import uvicorn

from config import RetrievalConfig
from shared.observability.otel.tracer import setup_auto_instrumentation, setup_tracing


def main():
    """Start the Retrieval Service."""
    config = RetrievalConfig()

    # Initialize OpenTelemetry tracing and auto-instrumentation
    setup_tracing(service_name="retrieval")
    setup_auto_instrumentation()

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=config.service_port,
        reload=config.debug,
        log_level="debug" if config.debug else "info",
    )


if __name__ == "__main__":
    main()
