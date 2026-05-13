"""OpenTelemetry distributed tracing bootstrap.

Call setup_tracing() early (before engines/clients are created).
Call instrument_app(app) after the FastAPI app is created.
Silently no-ops when OTEL_EXPORTER_OTLP_ENDPOINT is not set.
"""

import os
import threading
from collections import deque

_enabled = False

# Shared duration window for adaptive sampling (replaced in AdaptiveSampler.__init__)
_adaptive_lock = threading.Lock()
_adaptive_durations: deque = deque(maxlen=20)


class AdaptiveSampler:
    """Uses a low base rate but boosts to a higher rate when recent P95 exceeds threshold.

    Reads span durations recorded by LatencyTrackingProcessor (SERVER spans, nanoseconds).
    Delegates actual sampling decisions to TraceIdRatioBased for determinism.
    """

    def __init__(self):
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        self._base_rate = float(os.getenv("SAMPLING_ADAPTIVE_BASE_RATE", "0.05"))
        self._boost_rate = float(os.getenv("SAMPLING_ADAPTIVE_BOOST_RATE", "0.5"))
        self._threshold_ns = int(os.getenv("SAMPLING_ADAPTIVE_THRESHOLD_MS", "800")) * 1_000_000
        window = int(os.getenv("SAMPLING_ADAPTIVE_WINDOW", "20"))
        self._base_sampler = TraceIdRatioBased(self._base_rate)
        self._boost_sampler = TraceIdRatioBased(self._boost_rate)
        global _adaptive_durations
        _adaptive_durations = deque(maxlen=window)

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None):
        with _adaptive_lock:
            durations = list(_adaptive_durations)

        # Need at least 5 data points before adapting; until then use base rate
        if len(durations) >= 5:
            p95 = sorted(durations)[int(len(durations) * 0.95)]
            if p95 > self._threshold_ns:
                return self._boost_sampler.should_sample(
                    parent_context, trace_id, name, kind, attributes, links, trace_state
                )

        return self._base_sampler.should_sample(
            parent_context, trace_id, name, kind, attributes, links, trace_state
        )

    def get_description(self) -> str:
        return (
            f"AdaptiveSampler{{base={self._base_rate},"
            f"boost={self._boost_rate},"
            f"threshold={self._threshold_ns // 1_000_000}ms}}"
        )


class LatencyTrackingProcessor:
    """Records SERVER span durations (ns) into the adaptive sampler's sliding window."""

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        from opentelemetry.trace import SpanKind
        if span.kind == SpanKind.SERVER:
            with _adaptive_lock:
                _adaptive_durations.append(span.end_time - span.start_time)

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


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

    if os.getenv("SAMPLING_STRATEGY", "always_on").lower() == "adaptive":
        provider.add_span_processor(LatencyTrackingProcessor())

    trace.set_tracer_provider(provider)

    for _try in (_instr_httpx, _instr_sqlalchemy, _instr_psycopg2, _instr_requests):
        _try()

    _enabled = True


def instrument_app(app):
    """Instrument a FastAPI application (call after app creation)."""
    if not _enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)


def _build_sampler():
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased
    strategy = os.getenv("SAMPLING_STRATEGY", "always_on").lower()
    if strategy == "head":
        rate = float(os.getenv("SAMPLING_HEAD_RATE", "0.1"))
        return TraceIdRatioBased(rate)
    if strategy == "adaptive":
        return AdaptiveSampler()
    # "tail" and "always_on": send all spans to the collector;
    # tail sampling decisions are made by the OTel Collector, not the SDK.
    return ALWAYS_ON


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

