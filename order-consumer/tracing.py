import os

_enabled = False


def setup_tracing():
    global _enabled
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp_endpoint:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource

    service_name = os.getenv("OTEL_SERVICE_NAME", "order-consumer")
    resource = Resource.create({"service.name": service_name})
    sampler = _build_sampler()
    provider = TracerProvider(resource=resource, sampler=sampler)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()
    except Exception:
        pass

    _enabled = True


def _build_sampler():
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased
    strategy = os.getenv("SAMPLING_STRATEGY", "always_on").lower()
    if strategy == "head":
        rate = float(os.getenv("SAMPLING_HEAD_RATE", "0.1"))
        return TraceIdRatioBased(rate)
    return ALWAYS_ON
