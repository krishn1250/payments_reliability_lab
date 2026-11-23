"""OpenTelemetry tracing setup.

Every request becomes a trace: the FastAPI span, a child span per SQL
statement (psycopg instrumentation), and our own spans/events for the parts
that matter in an incident: idempotent replays, webhook outcomes and DB
retries. Traces go to the OTel Collector, which tail-samples and forwards to
Tempo (see docs/adr/0005-tracing-and-tail-sampling.md).

Tracing is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set, so unit tests and
local runs need no collector.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace

log = logging.getLogger("payments.telemetry")
tracer = trace.get_tracer("payments-api")


def setup_tracing(app, version: str) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        log.info("tracing disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    # OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES (pod name, namespace) are
    # merged in automatically by Resource.create().
    resource = Resource.create({"service.name": "payments-api", "service.version": version})

    # Head sampling keeps everything (ratio 1.0 by default); the Collector does
    # the real sampling once it has seen the whole trace (errors, slow ones).
    ratio = float(os.getenv("OTEL_TRACES_SAMPLER_RATIO", "1.0"))
    provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(ratio)))
    # Batching keeps exporting off the request path; if the collector is down
    # spans are dropped, never requests.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)

    PsycopgInstrumentor().instrument(enable_commenter=True)  # adds traceparent as a SQL comment
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics", tracer_provider=provider)
    log.info("tracing enabled -> %s (head sample ratio %.2f)", endpoint, ratio)


def current_trace_id() -> str:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else ""
