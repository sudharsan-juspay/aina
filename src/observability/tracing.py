"""
Distributed Tracing Configuration

Sets up and configures OpenTelemetry for distributed tracing.
"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from loguru import logger

from src.core.constants import APP_NAME, APP_VERSION

def setup_tracing():
    """Initializes the OpenTelemetry tracer."""
    
    # Create a resource to identify our application
    resource = Resource(attributes={
        "service.name": APP_NAME,
        "service.version": APP_VERSION,
    })

    # Set up a tracer provider
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # For development, we can use a console exporter.
    # For production, this would be configured to point to a real collector like Jaeger or Datadog.
    # Example using OTLP (OpenTelemetry Protocol) Exporter:
    exporter = OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")
    
    processor = BatchSpanProcessor(exporter)
    trace.get_tracer_provider().add_span_processor(processor)

    logger.info("OpenTelemetry tracing initialized.")

def get_tracer(name: str):
    """Gets a tracer instance for a specific module."""
    return trace.get_tracer(name)
