import json
import logging
import os

import azure.functions as func
from a2a.server.request_handlers.jsonrpc_handler import JSONRPCHandler
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    A2ARequest, AgentCapabilities, AgentCard, AgentSkill, APIKeySecurityScheme,
    CancelTaskRequest, GetTaskRequest, In, SecurityScheme, SendMessageRequest,
)
from pydantic import ValidationError

from agent import BudgetExecutor

base = "https://" + os.environ["WEBSITE_HOSTNAME"] if os.getenv("WEBSITE_HOSTNAME") else "http://localhost:7073"
card = AgentCard(
    name="Presupuesto", description="Agente remoto para aprobar gastos ficticios de la cena.",
    url=base + "/a2a", version="1.0.0", protocol_version="0.3.0",
    capabilities=AgentCapabilities(streaming=False), default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
    skills=[AgentSkill(id=name, name=name, description=description, tags=["presupuesto"])
            for name, description in [
                ("aprobar_gasto", "Aclara si incluye bebida y aprueba o rechaza una propuesta."),
                ("consultar_saldo", "Consulta el saldo ficticio de 600 EUR.")]],
    security_schemes={"function_key": SecurityScheme(root=APIKeySecurityScheme(
        type="apiKey", name="x-functions-key", in_=In.header))},
    security=[{"function_key": []}],
)
store = InMemoryTaskStore()
handler = JSONRPCHandler(card, DefaultRequestHandler(BudgetExecutor(), store))
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="api/health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ok", "service": "presupuesto", "phase": 1}),
        mimetype="application/json",
    )


@app.route(route=".well-known/agent-card.json", methods=["GET"])
def agent_card(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(card.model_dump_json(by_alias=True, exclude_none=True),
                             mimetype="application/json")


@app.route(route=".well-known/agent.json", methods=["GET"])
def legacy_agent_card(req: func.HttpRequest) -> func.HttpResponse:
    return agent_card(req)


@app.route(route="a2a", methods=["POST"])
async def a2a(req: func.HttpRequest) -> func.HttpResponse:
    request_id = None
    try:
        if len(req.get_body()) > 8192:
            raise ValueError("Peticion demasiado grande.")
        body = req.get_json()
        request_id = body.get("id") if isinstance(body, dict) else None
        message = A2ARequest.model_validate(body).root
        # Solo se conservan las ultimas 128 tareas; no hay persistencia de negocio.
        if len(store.tasks) >= 128 and isinstance(message, SendMessageRequest) and not message.params.message.task_id:
            await store.delete(next(iter(store.tasks)))
        if isinstance(message, SendMessageRequest):
            result = await handler.on_message_send(message)
        elif isinstance(message, GetTaskRequest):
            result = await handler.on_get_task(message)
        elif isinstance(message, CancelTaskRequest):
            result = await handler.on_cancel_task(message)
        else:
            return func.HttpResponse(json.dumps({"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Metodo no soportado."}}), mimetype="application/json")
        return func.HttpResponse(result.model_dump_json(by_alias=True, exclude_none=True),
                                 mimetype="application/json")
    except (ValueError, ValidationError):
        logging.warning("Peticion A2A invalida.")
        return func.HttpResponse(json.dumps({"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32600, "message": "Peticion JSON-RPC A2A invalida."}}),
            mimetype="application/json")
