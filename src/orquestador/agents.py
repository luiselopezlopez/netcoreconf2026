import asyncio
import json
import os
from datetime import datetime

import httpx
from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from mcp.types import CallToolResult


async def organize(near: str, people: int, max_per_head: float, when: str) -> dict:
    results: list[dict] = []
    weekday = ("monday", "tuesday", "wednesday", "thursday", "friday",
               "saturday", "sunday")[datetime.fromisoformat(when).weekday()]

    def record(result: CallToolResult) -> str:
        if result.isError:
            raise RuntimeError("La herramienta MCP devolvio un error.")
        text = "\n".join(c.text for c in result.content if c.type == "text")
        results.append(json.loads(text))
        return text

    async with (
        DefaultAzureCredential() as credential,
        httpx.AsyncClient(headers={"x-functions-key": os.environ["RESTAURANTES_MCP_KEY"]},
                          timeout=20) as http,
        MCPStreamableHTTPTool(
            name="Restaurantes", url=os.environ["RESTAURANTES_MCP_URL"],
            http_client=http, load_prompts=False, allowed_tools=["search", "book"],
            request_timeout=20, parse_tool_results=record,
        ) as mcp,
        AzureAIAgentClient(
            credential=credential,
            project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            model_deployment_name=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            function_invocation_configuration={"max_iterations": 5, "max_function_calls": 5},
        ) as client,
    ):
        search = next((tool for tool in mcp.functions if tool.name == "search"), None)
        if search is None:
            raise RuntimeError("El servidor MCP no expone search.")
        await search.invoke(arguments={"near": near, "people": people, "max_per_head": max_per_head})
        if not any(weekday in r["days"] for r in results[-1]["restaurants"]):
            return {"mode": "mcp", "status": "unavailable",
                    "result": "No hay restaurantes disponibles para esa zona, fecha y condiciones.",
                    "booking": None}
        thread = await client.agents_client.threads.create()
        try:
            agent = Agent(
                client=client, name="Cena", tools=[mcp],
                instructions=(
                    "Organiza una cena ficticia. Usa search antes de book; nunca inventes resultados. "
                    "Copia near, people y max_per_head exactamente en search, aunque la zona no sea conocida. "
                    "El limite de esta demo MCP es SOLO del menu, bebida aparte. "
                    "Descarta restaurantes sin disponibilidad el dia solicitado: days contiene dias en ingles. "
                    "Entre los disponibles elige el primero de search; reserva una sola vez "
                    "con los valores exactos recibidos. No uses Agenda ni Presupuesto. "
                    "Si ninguna opcion sirve, explica el motivo y no reserves."
                ),
            )
            async with asyncio.timeout(50):
                response = await agent.run(
                    json.dumps({"near": near, "people": people, "max_per_head": max_per_head,
                                "when": when, "weekday": weekday}),
                    options={"conversation_id": thread.id, "max_tokens": 600,
                             "allow_multiple_tool_calls": False},
                )
            bookings = [r for r in results if "booking_id" in r]
            candidates = [r for result in results for r in result.get("restaurants", [])]
            if len(bookings) != 1:
                raise RuntimeError("El agente no produjo exactamente una reserva MCP verificable.")
            booking = bookings[0]
            if (booking["people"] != people or booking["menu_per_head"] > max_per_head
                    or datetime.fromisoformat(booking["when"]) != datetime.fromisoformat(when)
                    or booking["restaurant_id"] not in {r["id"] for r in candidates}):
                raise RuntimeError("La reserva no cumple la peticion.")
            return {"mode": "mcp", "result": response.text, "booking": booking}
        finally:
            await client.agents_client.threads.delete(thread.id)
