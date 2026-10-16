import asyncio
import json
import logging
import os
from decimal import Decimal
from typing import Literal

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Part, TaskState
from a2a.utils import new_agent_text_message, new_task
from agent_framework import Agent, tool
from agent_framework_foundry import FoundryChatClient
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel, ConfigDict, Field


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    skill: Literal["aprobar_gasto"]
    restaurant_id: str = Field(min_length=1, max_length=100)
    people: int = Field(ge=1, le=20)
    menu_per_head: float = Field(ge=0, le=1000)
    drink_per_head: float = Field(ge=0, le=1000)
    max_per_head: float = Field(gt=0, le=1000)
    includes_drinks: bool | None = None


class BalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill: Literal["consultar_saldo"]


async def evaluate(proposal: Proposal | BalanceRequest) -> dict:
    decisions = []
    balances = []
    balance = {"balance": 600, "currency": "EUR", "simulated": True}

    @tool
    def consultar_saldo() -> str:
        """Devuelve el saldo ficticio disponible en EUR, sin efectuar cargos."""
        balances.append(balance)
        return json.dumps(balance)

    @tool
    def aprobar_gasto() -> str:
        """Evalua la propuesta recibida con la politica de menu, bebida y saldo."""
        if not isinstance(proposal, Proposal):
            raise ValueError("Se requiere una propuesta de gasto.")
        total = Decimal(str(proposal.menu_per_head))
        if proposal.includes_drinks:
            total += Decimal(str(proposal.drink_per_head))
        approved = total <= Decimal(str(proposal.max_per_head)) and total * proposal.people <= balance["balance"]
        result = {"restaurant_id": proposal.restaurant_id, "approved": approved,
                  "per_head": float(total), "total": float(total * proposal.people),
                  "max_per_head": proposal.max_per_head, "includes_drinks": proposal.includes_drinks,
                  **balance}
        decisions.append(result)
        return json.dumps(result)

    async with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"], credential=credential,
    ) as project:
        client = FoundryChatClient(project_client=project, model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"])
        agent = Agent(client=client, name="Presupuesto",
                      tools=[aprobar_gasto] if isinstance(proposal, Proposal) else [consultar_saldo],
                      instructions="Ejecuta la herramienta del skill recibido exactamente una vez. "
                      "aprobar_gasto ya consulta el saldo y aplica la politica. No inventes importes ni aprobaciones. "
                      "Explica brevemente la decision; no reserves ni cargues dinero.")
        async with asyncio.timeout(45):
            response = await agent.run(proposal.model_dump_json(), options={"max_tokens": 300})
    if isinstance(proposal, BalanceRequest):
        if len(balances) != 1:
            raise RuntimeError("Presupuesto no consulto exactamente una vez el saldo.")
        return {**balances[0], "explanation": response.text}
    if len(decisions) != 1:
        raise RuntimeError("Presupuesto no produjo una decision verificable.")
    return {**decisions[0], "explanation": response.text}


class BudgetExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise ValueError("La tarea requiere un mensaje A2A.")
        task = context.current_task or new_task(context.message)
        states = list((task.metadata or {}).get("states", ["submitted"]))
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        async def status(state, text, **metadata):
            states.append(state.value)
            await updater.update_status(state, new_agent_text_message(text, task.context_id, task.id),
                                        final=state == TaskState.input_required,
                                        metadata={"states": list(states), **metadata})

        await status(TaskState.working, "Presupuesto esta evaluando la peticion.")
        try:
            incoming = json.loads(context.get_user_input())
            if context.current_task:
                if context.current_task.status.state != TaskState.input_required:
                    raise ValueError("La tarea no espera una aclaracion.")
                if set(incoming) != {"includes_drinks"} or type(incoming["includes_drinks"]) is not bool:
                    raise ValueError("La aclaracion requiere includes_drinks booleano.")
                if not task.metadata or "proposal" not in task.metadata:
                    raise ValueError("La tarea no conserva una propuesta para aclarar.")
                incoming = {**task.metadata["proposal"], **incoming}
            proposal = (BalanceRequest.model_validate(incoming) if isinstance(incoming, dict)
                        and incoming.get("skill") == "consultar_saldo" else Proposal.model_validate(incoming))
            if isinstance(proposal, Proposal) and proposal.includes_drinks is None:
                await status(TaskState.input_required, "El limite por persona incluye bebida?",
                             proposal=proposal.model_dump())
                return
            decision = await evaluate(proposal)
            await updater.add_artifact([Part(root=DataPart(data=decision))], name=proposal.skill)
            await status(TaskState.completed, "Consulta completada; revisa el artefacto de decision.")
        except (ValueError, RuntimeError, TimeoutError):
            logging.exception("Fallo de validacion o ejecucion de Presupuesto.")
            await status(TaskState.failed, "No se pudo evaluar la propuesta. Revisa los logs de Presupuesto.")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            raise ValueError("No existe la tarea que se quiere cancelar.")
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(TaskState.canceled, final=True)
