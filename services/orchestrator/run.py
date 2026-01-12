#!/usr/bin/env python3
"""Entry point for the Orchestrator Service."""

import uvicorn
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from config import get_config


def setup_telemetry(config) -> None:
    """Configure OpenTelemetry tracing."""
    if not config.enable_tracing:
        return

    resource = Resource.create({"service.name": config.service_name})
    provider = TracerProvider(resource=resource)

    # OTLP exporter (for Jaeger/Tempo)
    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=config.otel_exporter_endpoint,
            insecure=True,
        )
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    except Exception as e:
        print(f"Warning: Could not configure OTLP exporter: {e}")

    trace.set_tracer_provider(provider)


def main() -> None:
    """Run the Orchestrator Service."""
    config = get_config()

    # Setup telemetry
    setup_telemetry(config)

    # Import app here to avoid circular imports
    from api.app import create_app

    app = create_app()

    # Run server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.service_port,
        log_level="debug" if config.debug else "info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
