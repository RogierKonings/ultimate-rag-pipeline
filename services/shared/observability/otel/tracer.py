"""
OpenTelemetry Tracer Configuration.

Provides configuration and setup for distributed tracing with:
- Environment-based configuration
- OTLP export to collector
- Configurable sampling (head-based and tail-based via collector)
- BatchSpanProcessor for efficient export
"""

import logging
import os
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Tracer, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)
from opentelemetry.semconv.resource import ResourceAttributes

logger = logging.getLogger(__name__)

# Global state
_tracer_provider: TracerProvider | None = None
_tracer: Tracer | None = None
_initialized: bool = False


@dataclass
class OTELConfig:
    """
    OpenTelemetry configuration.

    Attributes:
        service_name: Name of the service for traces
        service_version: Version of the service
        otlp_endpoint: OTLP collector endpoint (gRPC)
        environment: Deployment environment
        sample_rate: Sampling rate (0.0 to 1.0)
        enable_console_export: Also export spans to console (for debugging)
        batch_export_delay_ms: Delay between batch exports
        max_export_batch_size: Maximum spans per export batch
        max_queue_size: Maximum spans queued for export
    """

    service_name: str
    service_version: str = "1.0.0"
    otlp_endpoint: str = field(
        default_factory=lambda: os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
    )
    environment: str = field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "development"),
    )
    sample_rate: float = field(
        default_factory=lambda: float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")),
    )
    enable_console_export: bool = field(
        default_factory=lambda: os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() == "true",
    )
    batch_export_delay_ms: int = 5000
    max_export_batch_size: int = 512
    max_queue_size: int = 2048

    @classmethod
    def from_env(cls, service_name: str, service_version: str = "1.0.0") -> "OTELConfig":
        """
        Create configuration from environment variables.

        Environment variables:
            OTEL_EXPORTER_OTLP_ENDPOINT: Collector endpoint
            OTEL_SERVICE_NAME: Service name (overrides parameter)
            OTEL_TRACES_SAMPLER_ARG: Sample rate
            ENVIRONMENT: Deployment environment
            OTEL_CONSOLE_EXPORT: Enable console export

        Args:
            service_name: Default service name
            service_version: Service version

        Returns:
            OTELConfig instance
        """
        return cls(
            service_name=os.getenv("OTEL_SERVICE_NAME", service_name),
            service_version=service_version,
        )

    def get_sampler(self) -> Sampler:
        """
        Get the appropriate sampler based on configuration.

        Returns:
            Configured sampler
        """
        if self.environment == "production":
            # In production, use configured sample rate (default 10%)
            rate = self.sample_rate if self.sample_rate < 1.0 else 0.1
            return ParentBased(root=TraceIdRatioBased(rate))
        if self.environment == "staging":
            # In staging, sample 50%
            return ParentBased(root=TraceIdRatioBased(0.5))
        # In development, sample everything
        return ALWAYS_ON


def setup_tracing(
    service_name: str,
    service_version: str = "1.0.0",
    otlp_endpoint: str | None = None,
    environment: str = "development",
    config: OTELConfig | None = None,
) -> TracerProvider:
    """
    Initialize OpenTelemetry tracing.

    This should be called once at application startup. Subsequent calls
    will return the existing provider.

    Args:
        service_name: Name of the service
        service_version: Version of the service
        otlp_endpoint: OTLP collector endpoint (overrides env/config)
        environment: Deployment environment
        config: Optional pre-built configuration

    Returns:
        Configured TracerProvider
    """
    global _tracer_provider, _tracer, _initialized

    if _initialized and _tracer_provider is not None:
        logger.debug("Tracing already initialized, returning existing provider")
        return _tracer_provider

    # Build configuration
    if config is None:
        config = OTELConfig.from_env(service_name, service_version)
        config.environment = environment
        if otlp_endpoint:
            config.otlp_endpoint = otlp_endpoint

    logger.info(
        f"Setting up tracing for {config.service_name} "
        f"(env={config.environment}, endpoint={config.otlp_endpoint})",
    )

    # Create resource with service attributes
    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: config.service_name,
            ResourceAttributes.SERVICE_VERSION: config.service_version,
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: config.environment,
            "service.namespace": "rag-pipeline",
        },
    )

    # Create provider with sampler
    sampler = config.get_sampler()
    _tracer_provider = TracerProvider(resource=resource, sampler=sampler)

    # Add OTLP exporter
    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=config.otlp_endpoint,
            insecure=True,  # Use TLS in production via env var
        )
        span_processor = BatchSpanProcessor(
            otlp_exporter,
            schedule_delay_millis=config.batch_export_delay_ms,
            max_export_batch_size=config.max_export_batch_size,
            max_queue_size=config.max_queue_size,
        )
        _tracer_provider.add_span_processor(span_processor)
        logger.info(f"OTLP exporter configured for {config.otlp_endpoint}")
    except Exception as e:
        logger.warning(f"Failed to setup OTLP exporter: {e}")

    # Add console exporter for debugging
    if config.enable_console_export:
        console_processor = BatchSpanProcessor(ConsoleSpanExporter())
        _tracer_provider.add_span_processor(console_processor)
        logger.info("Console span exporter enabled")

    # Set as global provider
    trace.set_tracer_provider(_tracer_provider)
    _tracer = trace.get_tracer(config.service_name, config.service_version)
    _initialized = True

    logger.info(
        f"Tracing initialized: service={config.service_name}, "
        f"sampler={type(sampler).__name__}",
    )

    return _tracer_provider


def get_tracer(
    name: str | None = None,
    version: str | None = None,
) -> Tracer:
    """
    Get a tracer instance.

    If tracing has not been initialized, returns a no-op tracer.

    Args:
        name: Optional tracer name (defaults to service name)
        version: Optional tracer version

    Returns:
        OpenTelemetry Tracer
    """
    global _tracer

    if _tracer is not None and name is None:
        return _tracer

    # Return tracer from provider if available
    provider = trace.get_tracer_provider()
    return provider.get_tracer(
        name or "rag-pipeline",
        version or "1.0.0",
    )


def get_tracer_provider() -> TracerProvider | None:
    """
    Get the current TracerProvider.

    Returns:
        TracerProvider or None if not initialized
    """
    return _tracer_provider


def shutdown_tracing() -> None:
    """
    Shutdown tracing and flush pending spans.

    Call this during application shutdown to ensure all spans are exported.
    """
    global _tracer_provider, _tracer, _initialized

    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
            logger.info("Tracing shutdown complete")
        except Exception as e:
            logger.warning(f"Error during tracing shutdown: {e}")

    _tracer_provider = None
    _tracer = None
    _initialized = False
