import json
import os
from uuid import uuid4
from decimal import Decimal

import httpx
from a2a.client import A2AClient
from a2a.types import (
    AgentCard, DataPart, JSONRPCErrorResponse, Message, MessageSendParams, Part,
    Role, SendMessageRequest, Task, TaskState, TextPart,
)
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field


class BudgetDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    restaurant_id: str
    approved: bool
    per_head: float = Field(ge=0)
    total: float = Field(ge=0)
    max_per_head: float = Field(gt=0)
    includes_drinks: bool
    balance: float = Field(ge=0)
    currency: str = Field(pattern="^EUR$")
    simulated: bool
    explanation: str


async def consult_budget(proposal: dict, includes_drinks: bool, exchanges: list[dict]) -> dict:
    url = os.environ["PRESUPUESTO_A2A_URL"].rstrip("/")
    async with httpx.AsyncClient(headers={"x-functions-key": os.environ["PRESUPUESTO_A2A_KEY"]},
                                 timeout=65) as http:
        with trace.get_tracer("cena.a2a").start_as_current_span("a2a discover Presupuesto"):
            response = await http.get(url.removesuffix("/a2a") + "/.well-known/agent-card.json")
            response.raise_for_status()
            card = AgentCard.model_validate(response.json())
            if card.url != url or not {"aprobar_gasto", "consultar_saldo"} <= {s.id for s in card.skills}:
                raise RuntimeError("Agent Card de Presupuesto no coincide con el endpoint y skills esperados.")
        client = A2AClient(http, agent_card=card)

        async def send(payload, previous=None):
            with trace.get_tracer("cena.a2a").start_as_current_span("a2a message/send Presupuesto") as span:
                message = Message(role=Role.user, message_id=str(uuid4()),
                                  task_id=previous.id if previous else None,
                                  context_id=previous.context_id if previous else None,
                                  parts=[Part(root=TextPart(text=json.dumps(payload)))])
                result = await client.send_message(SendMessageRequest(
                    id=str(uuid4()), params=MessageSendParams(message=message)))
                if isinstance(result.root, JSONRPCErrorResponse) or not isinstance(result.root.result, Task):
                    raise RuntimeError("Presupuesto devolvio un error JSON-RPC o una respuesta sin tarea.")
                task = result.root.result
                exchange = {"task_id": task.id, "context_id": task.context_id,
                            "state": task.status.state.value, "states": (task.metadata or {}).get("states", []),
                            "request": payload, "response": task.model_dump(mode="json", by_alias=True, exclude_none=True)}
                exchanges.append(exchange)
                span.set_attribute("gen_ai.tool.call.arguments", json.dumps(payload))
                span.set_attribute("gen_ai.tool.call.result", json.dumps(exchange))
                return task

        task = await send(proposal)
        if task.status.state != TaskState.input_required:
            raise RuntimeError("Presupuesto no solicito aclarar si el limite incluye bebida.")
        resumed = await send({"includes_drinks": includes_drinks}, task)
        if resumed.id != task.id or resumed.context_id != task.context_id or resumed.status.state != TaskState.completed:
            raise RuntimeError("Presupuesto no completo la misma tarea tras la aclaracion.")
        artifacts = [p.root.data for a in resumed.artifacts or [] for p in a.parts if isinstance(p.root, DataPart)]
        if len(artifacts) != 1:
            raise RuntimeError("Presupuesto no devolvio exactamente un artefacto de decision.")
        decision = BudgetDecision.model_validate(artifacts[0])
        expected = Decimal(str(proposal["menu_per_head"]))
        if includes_drinks:
            expected += Decimal(str(proposal["drink_per_head"]))
        if (decision.restaurant_id != proposal["restaurant_id"] or decision.includes_drinks != includes_drinks
                or decision.max_per_head != proposal["max_per_head"] or not decision.simulated
                or Decimal(str(decision.per_head)) != expected
                or Decimal(str(decision.total)) != expected * proposal["people"]
                or (decision.approved and (expected > Decimal(str(proposal["max_per_head"]))
                                           or expected * proposal["people"] > Decimal(str(decision.balance))))):
            raise RuntimeError("La decision de Presupuesto no corresponde a la propuesta.")
        return decision.model_dump()
