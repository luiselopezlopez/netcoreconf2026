import asyncio
import json
import os
from contextlib import AsyncExitStack
from datetime import datetime

import httpx
from agent_framework import Agent, ChatOptions, MCPStreamableHTTPTool, tool
from agent_framework_foundry import FoundryChatClient
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from mcp.types import CallToolResult

from data import FREE_SLOTS
from budget_peer import consult_budget


async def organize(near: str, people: int, max_per_head: float, when: str, mode: str = "mcp",
                   includes_drinks: bool = True) -> dict:
    if mode not in ("mcp", "tools", "a2a"):
        raise ValueError("Solo se admite mode=mcp, tools o a2a.")
    results: list[dict] = []
    agenda_results: list[dict] = []
    budget_results: list[dict] = []
    exchanges: list[dict] = []
    requested_time = datetime.fromisoformat(when).time().replace(tzinfo=None).isoformat()
    weekday = ("monday", "tuesday", "wednesday", "thursday", "friday",
               "saturday", "sunday")[datetime.fromisoformat(when).weekday()]

    def record(result: CallToolResult) -> str:
        if result.isError:
            raise RuntimeError("La herramienta MCP devolvio un error.")
        text = "\n".join(c.text for c in result.content if c.type == "text")
        results.append(json.loads(text))
        return text

    async with AsyncExitStack() as stack:
        credential = await stack.enter_async_context(DefaultAzureCredential())
        http = await stack.enter_async_context(httpx.AsyncClient(
            headers={"x-functions-key": os.environ["RESTAURANTES_MCP_KEY"]}, timeout=20))
        mcp = await stack.enter_async_context(MCPStreamableHTTPTool(
            name="Restaurantes", url=os.environ["RESTAURANTES_MCP_URL"],
            http_client=http, load_prompts=False, allowed_tools=["search", "book"],
            request_timeout=20, parse_tool_results=record,
        ))

        def create_chat_client():
            return FoundryChatClient(
                project_client=project,
                model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
                function_invocation_configuration={
                    "max_iterations": 6,
                    "max_function_calls": 6,
                    "include_detailed_errors": True,
                },
            )

        search = next((tool for tool in mcp.functions if tool.name == "search"), None)
        if search is None:
            raise RuntimeError("El servidor MCP no expone search.")
        await search.invoke(arguments={"near": near, "people": people, "max_per_head": max_per_head})
        available = [r for r in results[-1]["restaurants"] if weekday in r["days"]]
        if not available:
            return {"mode": mode, "status": "unavailable",
                    "result": "No hay restaurantes disponibles para esa zona, fecha y condiciones.",
                    "booking": None}
        project = await stack.enter_async_context(AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"], credential=credential))
        tools = [mcp]
        instructions = "No uses Agenda ni Presupuesto. "
        if mode in ("tools", "a2a"):
            @tool
            def free_slots(day: str, people: int) -> str:
                """Consulta las franjas libres ficticias de los ponentes para una fecha ISO y un grupo."""
                if day != when[:10] or people != requested_people:
                    raise ValueError("Agenda debe consultar la fecha y el grupo de la peticion.")
                slots = FREE_SLOTS.get(weekday, []) if people <= 12 else []
                result = {"day": day, "people": people, "slots": slots}
                agenda_results.append(result)
                return json.dumps(result)

            requested_people = people
            agenda = Agent(client=create_chat_client(), name="Agenda", tools=[free_slots],
                           instructions="Consulta free_slots exactamente una vez con day y people recibidos. "
                           "Devuelve sus franjas sin inventar disponibilidad. No reserves ni consultes restaurantes.")
            book = next(t for t in mcp.functions if t.name == "book")

            @tool
            async def book_after_agenda(restaurant_id: str) -> str:
                """Reserva por MCP, solo despues de comprobar Agenda. Conserva fecha, hora y comensales."""
                if (not agenda_results or requested_time
                        not in [slot + ":00" for slot in agenda_results[-1]["slots"]]
                        or any("booking_id" in r for r in results)
                        or restaurant_id not in {r["id"] for r in results[0]["restaurants"]
                                                 if weekday in r["days"]}):
                    raise ValueError("Reserva no autorizada por Agenda o por los candidatos MCP.")
                if mode == "a2a" and not any(r["restaurant_id"] == restaurant_id and r["approved"]
                                              for r in budget_results):
                    raise ValueError("No se puede reservar sin aprobacion remota de Presupuesto.")
                await book.invoke(arguments={"restaurant_id": restaurant_id, "when": when, "people": people})
                return json.dumps(results[-1])

            agenda_tool = agenda.as_tool(name="consultar_agenda", arg_name="request",
                     arg_description="Una cadena de texto con la fecha ISO y el numero de ponentes.",
                     description="Delega una peticion de disponibilidad en el agente Agenda.")
            tools = [search, agenda_tool, book_after_agenda]
            instructions = ("Antes de reservar, llama consultar_agenda pasando request como una CADENA "
                            "con la fecha ISO y el numero exacto de ponentes. "
                            "Agenda es otro agente con su herramienta free_slots. "
                            "Despues usa search y book_after_agenda con el primer restaurante disponible. "
                            "Solo reserva si la HORA exacta recibida figura en slots; no cambies la hora. "
                            "Sin franja libre, explica el motivo y no reserves. No uses Presupuesto. ")
            if mode == "a2a":
                @tool
                async def consultar_presupuesto(restaurant_id: str) -> str:
                    """Negocia por A2A con Presupuesto; puede pedir aclaracion y rechazar la propuesta."""
                    if not agenda_results or requested_time not in [s + ":00" for s in agenda_results[-1]["slots"]]:
                        raise ValueError("Consulta Agenda antes de negociar.")
                    if len(budget_results) >= len(available) or any(r["approved"] for r in budget_results):
                        raise ValueError("No quedan propuestas pendientes de evaluar.")
                    candidate = available[len(budget_results)]
                    if restaurant_id != candidate["id"]:
                        raise ValueError("Propone los restaurantes en el orden de search, sin saltarte ninguno.")
                    proposal = {"skill": "aprobar_gasto", "restaurant_id": restaurant_id,
                                "people": people, "menu_per_head": candidate["menu"],
                                "drink_per_head": candidate["drink"], "max_per_head": max_per_head}
                    decision = await consult_budget(proposal, includes_drinks, exchanges)
                    budget_results.append(decision)
                    return json.dumps(decision)

                @tool
                async def negociar_cena() -> str:
                    """Delega en Agenda y Presupuesto A2A en orden; reserva solo una propuesta aprobada."""
                    if agenda_results:
                        raise ValueError("La negociacion ya se inicio; no se puede repetir.")
                    await agenda_tool.invoke(arguments={"request": f"Fecha {when[:10]}, {people} ponentes."})
                    if not agenda_results:
                        raise RuntimeError("Agenda no produjo disponibilidad verificable.")
                    if requested_time not in [s + ":00" for s in agenda_results[-1]["slots"]]:
                        return json.dumps({"status": "unavailable", "reason": "Agenda no permite esa hora."})
                    for candidate in available:
                        await consultar_presupuesto.invoke(arguments={"restaurant_id": candidate["id"]})
                        if budget_results[-1]["approved"]:
                            await book_after_agenda.invoke(arguments={"restaurant_id": candidate["id"]})
                            return json.dumps(results[-1])
                    return json.dumps({"status": "unavailable", "reason": "Presupuesto rechazo todas las propuestas."})

                tools = [negociar_cena]
                instructions = ("Ejecuta negociar_cena exactamente una vez y explica su resultado. "
                                "Esta herramienta delega en Agenda y Presupuesto remoto A2A y comprueba "
                                "las aprobaciones antes de reservar. No sustituyas la delegacion por "
                                "calculos propios aunque parezca que ningun restaurante cumple el limite. ")
        agent = Agent(
            client=create_chat_client(), name="Cena", tools=tools,
            instructions=(
                    "Organiza una cena ficticia. Nunca inventes resultados. "
                    + ("search ya se ejecuto en el preflight. Usa los restaurants recibidos, no repitas search. "
                       if mode == "a2a" else "Usa search antes de book. ") +
                    "Copia near, people y max_per_head exactamente en search, aunque la zona no sea conocida. "
                    "El filtro de search es SOLO del menu, bebida aparte. "
                    "Descarta restaurantes sin disponibilidad el dia solicitado: days contiene dias en ingles. "
                    "Entre los disponibles sigue el orden de search; reserva una sola vez "
                    "con los valores exactos recibidos. " + instructions +
                    "Si ninguna opcion sirve, explica el motivo y no reserves."
            ),
        )
        options: ChatOptions = {"max_tokens": 600, "allow_multiple_tool_calls": False}
        if mode == "a2a":
            options["tool_choice"] = {"mode": "required", "required_function_name": "negociar_cena"}
        async with asyncio.timeout(180 if mode == "a2a" else 90):
            response = await agent.run(
                json.dumps({"near": near, "people": people, "max_per_head": max_per_head,
                            "when": when, "weekday": weekday,
                            **({"restaurants": available} if mode == "a2a" else {})}),
                options=options,
            )
        bookings = [r for r in results if "booking_id" in r]
        if mode in ("tools", "a2a") and not agenda_results:
            raise RuntimeError("Cena no delego una consulta verificable en Agenda.")
        if (not bookings and agenda_results
                and requested_time not in [slot + ":00" for slot in agenda_results[-1]["slots"]]):
            return {"mode": mode, "status": "unavailable", "result": response.text,
                    "booking": None, "agenda": agenda_results[-1]}
        candidates = [r for result in results for r in result.get("restaurants", [])]
        if (mode == "a2a" and not bookings and len(budget_results) == len(available)
                and not any(r["approved"] for r in budget_results)):
            return {"mode": mode, "status": "unavailable", "result": response.text, "booking": None,
                    "agenda": agenda_results[-1], "budget": budget_results, "a2a": exchanges}
        if len(bookings) != 1:
            raise RuntimeError("El agente no produjo exactamente una reserva MCP verificable.")
        booking = bookings[0]
        if (booking["people"] != people or booking["menu_per_head"] > max_per_head
                or datetime.fromisoformat(booking["when"]) != datetime.fromisoformat(when)
                or booking["restaurant_id"] not in {r["id"] for r in candidates}):
            raise RuntimeError("La reserva no cumple la peticion.")
        result = {"mode": mode, "result": response.text, "booking": booking}
        if agenda_results:
            result["agenda"] = agenda_results[-1]
        if mode == "a2a":
            result.update(budget=budget_results, a2a=exchanges)
        return result
