"""OpenTelemetry distributed tracing bootstrap.

Call setup_tracing() early (before engines/clients are created).
Call instrument_app(app) after the FastAPI app is created.
Silently no-ops when OTEL_EXPORTER_OTLP_ENDPOINT is not set.
"""

import os

_enabled = False


def setup_tracing():
    """Set up the global TracerProvider and instrument DB/HTTP client libs."""
    global _enabled
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp_endpoint:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource

    service_name = os.getenv(
        "OTEL_SERVICE_NAME", os.getenv("SERVICE_NAME", "unknown")
    )
    resource = Resource.create({"service.name": service_name})
    sampler = _build_sampler()
    provider = TracerProvider(resource=resource, sampler=sampler)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Instrument client libraries (each is optional)
    for _try in (_instr_httpx, _instr_sqlalchemy, _instr_psycopg2, _instr_requests):
        _try()

    _enabled = True


def instrument_app(app):
    """Instrument a FastAPI application (call after app creation)."""
    if not _enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)


# --------------- sampler factory ---------------

def _build_sampler():
    """Return a sampler based on SAMPLING_STRATEGY env var."""
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased
    strategy = os.getenv("SAMPLING_STRATEGY", "always_on").lower()
    if strategy == "head":
        rate = float(os.getenv("SAMPLING_HEAD_RATE", "0.1"))
        return TraceIdRatioBased(rate)
    # "tail" and "always_on": send all spans to the collector;
    # tail sampling decisions are made by the OTel Collector, not the SDK.
    return ALWAYS_ON


# --------------- optional instrumentors ---------------

def _instr_httpx():
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass


def _instr_sqlalchemy():
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
    except Exception:
        pass


def _instr_psycopg2():
    try:
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
        Psycopg2Instrumentor().instrument()
    except Exception:
        pass


def _instr_requests():
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()
    except Exception:
        pass
