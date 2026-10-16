import asyncio
import json
import logging
import os
import queue
import secrets
import sys
import threading
from contextvars import ContextVar
from pathlib import Path
from time import monotonic

from agent_framework.observability import enable_instrumentation
from flask import Flask, Response, jsonify, request, stream_with_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parent / "src" / "orquestador"))
from src.orquestador.function_app import Dinner, organize  # noqa: E402
from telemetry import add_monitor  # noqa: E402

EVENTS: ContextVar[queue.Queue | None] = ContextVar("demo_events", default=None)
LOGGER = logging.getLogger("demo_web")
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}
TOOL_ATTRIBUTES = ("gen_ai.tool.call.arguments", "gen_ai.tool.call.result")
SAFE_ATTRIBUTES = ("gen_ai.operation.name", "gen_ai.tool.name", "gen_ai.agent.name",
                   "gen_ai.request.model", "gen_ai.usage.input_tokens",
                   "gen_ai.usage.output_tokens", "error.type")


class LiveSpans(SpanProcessor):
    def __init__(self):
        self.pending: dict[int, queue.Queue] = {}
        self.lock = threading.Lock()

    def on_start(self, span: Span, parent_context=None):
        events = EVENTS.get()
        if events is None:
            return
        span_id = span.get_span_context().span_id
        with self.lock:
            self.pending[span_id] = events
        events.put({"type": "span_start", "id": str(span_id), "name": span.name,
                    "parent": str(span.parent.span_id) if span.parent else None,
                    "trace_id": format(span.get_span_context().trace_id, "032x")})

    def on_end(self, span: ReadableSpan):
        context = span.get_span_context()
        if context is None:
            LOGGER.error("Span sin contexto; no se puede asociar a la ejecucion.")
            return
        with self.lock:
            events = self.pending.pop(context.span_id, None)
        if events is None:
            return
        attributes = span.attributes or {}
        details = {key: attributes[key] for key in SAFE_ATTRIBUTES if key in attributes}
        for key in TOOL_ATTRIBUTES:
            if key in attributes:
                text = str(attributes[key])
                try:
                    details[key] = json.loads(text)
                except json.JSONDecodeError:
                    details[key] = text
        events.put({"type": "span_end", "id": str(context.span_id),
                    "name": span.name, "details": details,
                    "failed": span.status.status_code == trace.StatusCode.ERROR
                    or "error.type" in attributes,
                    "duration_ms": round(((span.end_time or 0) - (span.start_time or 0)) / 1e6)})


class Demo:
    def __init__(self, runner):
        self.runner = runner
        self.run_lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)

    def execute(self, dinner: Dinner, events: queue.Queue):
        token = EVENTS.set(events)
        started = monotonic()
        events.put({"type": "started"})
        try:
            with trace.get_tracer("cena").start_as_current_span("cena.request") as span:
                result = asyncio.run(self.runner(
                    near=dinner.near, people=dinner.people,
                    max_per_head=dinner.max_per_head, when=dinner.when, mode=dinner.mode,
                    **({"includes_drinks": dinner.includes_drinks} if dinner.mode == "a2a" else {})))
                result["trace_id"] = format(span.get_span_context().trace_id, "032x")
            events.put({"type": "result", "data": result,
                        "duration_ms": round((monotonic() - started) * 1000)})
        except Exception:
            LOGGER.exception("Fallo de ejecucion de la demo.")
            events.put({"type": "error", "message": "La ejecucion ha fallado. Revisa el terminal "
                        "del servidor, la sesion de Azure CLI y los permisos de Foundry/MCP."})
        finally:
            EVENTS.reset(token)
            self.run_lock.release()
            events.put(None)


def configure_tracing():
    provider = TracerProvider(resource=Resource.create({"service.name": "demo-web"}))
    provider.add_span_processor(LiveSpans())
    add_monitor(provider)
    trace.set_tracer_provider(provider)
    enable_instrumentation(enable_sensitive_data=True)
    return provider


def create_app(runner=organize, *, port=8080, cloud_host=None, allowed_user=None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    demo = Demo(runner)
    app.extensions["demo"] = demo
    hosts = {cloud_host} if cloud_host else {f"127.0.0.1:{port}", f"localhost:{port}"}
    scheme = "https" if cloud_host else "http"
    if cloud_host and not allowed_user:
        raise ValueError("Falta el usuario autorizado para el hosting Azure.")

    @app.before_request
    def protect():
        if request.path == "/health":
            return None
        if request.host not in hosts:
            return jsonify(error="Host no permitido."), 403
        if cloud_host and request.headers.get("X-MS-CLIENT-PRINCIPAL-ID") != allowed_user:
            return jsonify(error="Inicia sesion con el usuario autorizado."), 403
        if request.method == "POST" and (
            request.headers.get("Origin", f"{scheme}://{request.host}") != f"{scheme}://{request.host}"
            or not secrets.compare_digest(request.headers.get("X-Demo-Token", ""), demo.token)
        ):
            return jsonify(error="Origen o token de sesion no permitido."), 403
        return None

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; img-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="demo-web")

    @app.get("/api/config")
    def config():
        return jsonify(token=demo.token, mode="mcp", modes=["mcp", "tools", "a2a"],
                       hosting="azure" if cloud_host else "local")

    @app.get("/")
    @app.get("/app.js")
    @app.get("/style.css")
    def static():
        name, mime = STATIC[request.path]
        return Response((ROOT / "static" / name).read_bytes(), content_type=mime + "; charset=utf-8")

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Ruta no encontrada."), 404

    @app.errorhandler(RequestEntityTooLarge)
    @app.errorhandler(BadRequest)
    def bad_request(_error):
        LOGGER.warning("Cuerpo de peticion invalido o demasiado grande.")
        return jsonify(error="El cuerpo de la peticion no es valido."), 400

    @app.post("/api/run")
    def run():
        try:
            if request.mimetype != "application/json":
                raise ValueError("Se requiere JSON.")
            dinner = Dinner.model_validate_json(request.get_data())
            if dinner.mode not in ("mcp", "tools", "a2a"):
                raise ValueError("Solo se admite MCP, tools o a2a.")
        except (ValueError, ValidationError):
            LOGGER.warning("Peticion de demo invalida.")
            return jsonify(error="Revisa zona, comensales (1-20), precio y fecha con hora."), 400
        if not demo.run_lock.acquire(blocking=False):
            return jsonify(error="Ya hay una demo en curso. Espera a que termine."), 409
        events = queue.Queue()
        threading.Thread(target=demo.execute, args=(dinner, events), daemon=False).start()

        def stream():
            try:
                while True:
                    try:
                        event = events.get(timeout=2)
                    except queue.Empty:
                        event = {"type": "heartbeat"}
                    if event is None:
                        break
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except GeneratorExit:
                LOGGER.warning("Navegador desconectado; la ejecucion continua su limpieza.")
                raise
        return Response(stream_with_context(stream()), content_type="application/x-ndjson; charset=utf-8",
                        headers={"X-Accel-Buffering": "no"})
    return app


def check_configuration():
    required = ("RESTAURANTES_MCP_KEY", "RESTAURANTES_MCP_URL",
                "AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if any(not os.environ.get(name) for name in required):
        raise SystemExit("Falta configuracion. Inicia la web con scripts\\start-demo-web.ps1.")


def main():
    logging.basicConfig(level=logging.WARNING)
    check_configuration()
    provider = configure_tracing()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        create_app(port=port).run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
    finally:
        provider.shutdown()


if __name__ == "__main__":
    main()
