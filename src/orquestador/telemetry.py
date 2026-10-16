import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from agent_framework.observability import enable_instrumentation
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult


class MetadataExporter(AzureMonitorTraceExporter):
    def export(self, spans: Sequence[ReadableSpan], **_kwargs: Any) -> SpanExportResult:
        safe = ("gen_ai.operation.name", "gen_ai.tool.name", "gen_ai.agent.name",
                "gen_ai.request.model", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "error.type")
        return super().export([ReadableSpan(
            name=s.name, context=s.context, parent=s.parent, resource=s.resource,
            attributes={k: v for k, v in (s.attributes or {}).items() if k in safe},
            events=(), status=trace.Status(s.status.status_code), kind=s.kind,
            start_time=s.start_time, end_time=s.end_time, instrumentation_scope=s.instrumentation_scope,
        ) for s in spans])


def add_monitor(provider: TracerProvider):
    if connection := os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        provider.add_span_processor(BatchSpanProcessor(MetadataExporter(
            connection_string=connection, credential=DefaultAzureCredential(), disable_offline_storage=True)))


@lru_cache(maxsize=1)
def configure_tracing():
    provider = TracerProvider(resource=Resource.create({"service.name": "orquestador"}))
    add_monitor(provider)
    trace.set_tracer_provider(provider)
    enable_instrumentation(enable_sensitive_data=False)
    return provider
