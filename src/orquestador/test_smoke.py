import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import azure.functions as func

from function_app import app, cena, health
from agent_framework import tool
from mcp.types import CallToolResult, TextContent
from agents import organize


class SmokeTest(unittest.TestCase):
    def test_a2a_booking_guards(self):
        candidates = [{"id": "plaza", "menu": 42, "drink": 6, "days": ["friday"]},
                      {"id": "patio", "menu": 38, "drink": 5, "days": ["friday"]}]
        bookings = []
        scenario = "happy"

        class MCP:
            def __init__(self, **kwargs):
                def record(value):
                    return kwargs["parse_tool_results"](CallToolResult(
                        content=[TextContent(type="text", text=json.dumps(value))]))
                @tool
                async def search(near: str, people: int, max_per_head: float) -> str:
                    """Busca candidatos de prueba."""
                    return record({"restaurants": candidates})
                @tool
                async def book(restaurant_id: str, when: str, people: int) -> str:
                    """Registra una reserva de prueba."""
                    bookings.append(restaurant_id)
                    return record({"booking_id": "smoke", "restaurant_id": restaurant_id,
                                   "when": when, "people": people, "menu_per_head": 38})
                self.functions = [search, book]
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                pass

        class Agent:
            def __init__(self, *, name, tools, **_kwargs):
                self.name, self.tools = name, {t.name: t for t in tools}
            def as_tool(self, **_kwargs):
                @tool
                async def consultar_agenda(request: str) -> str:
                    """Invoca la herramienta de Agenda en el smoke test."""
                    return await self.tools["free_slots"].invoke(arguments={"day": "2026-10-23", "people": 12})
                return consultar_agenda
            async def run(self, *_args, **_kwargs):
                if set(self.tools) != {"negociar_cena"}:
                    raise AssertionError("Cena no debe poder saltarse la negociacion ni elegir propuestas fuera de orden.")
                await self.tools["negociar_cena"].invoke(arguments={})
                if scenario == "repeat":
                    await self.tools["negociar_cena"].invoke(arguments={})
                return SimpleNamespace(text="Resultado de prueba.")

        async def budget(proposal, _includes, _exchanges):
            return {"restaurant_id": proposal["restaurant_id"],
                    "approved": scenario != "rejected" and proposal["restaurant_id"] == "patio"}

        async def run():
            nonlocal scenario
            with patch.dict("os.environ", RESTAURANTES_MCP_KEY="smoke", RESTAURANTES_MCP_URL="https://mcp.example",
                            AZURE_AI_PROJECT_ENDPOINT="https://project.example", AZURE_AI_MODEL_DEPLOYMENT_NAME="model"), \
                    patch("agents.MCPStreamableHTTPTool", MCP), patch("agents.Agent", Agent), \
                    patch("agents.AIProjectClient"), patch("agents.FoundryChatClient"), \
                    patch("agents.consult_budget", side_effect=budget):
                for scenario in ("happy", "repeat", "rejected"):
                    bookings.clear()
                    if scenario == "repeat":
                        with self.assertRaises(ValueError):
                            await organize("zona-demo", 12, 45, "2026-10-23T20:30:00+02:00", "a2a")
                        self.assertEqual(bookings, ["patio"])
                    else:
                        result = await organize("zona-demo", 12, 45, "2026-10-23T20:30:00+02:00", "a2a")
                        self.assertEqual(bookings, ["patio"] if scenario == "happy" else [])
                        self.assertEqual(result.get("status"), None if scenario == "happy" else "unavailable")
        asyncio.run(run())

    def test_health(self):
        functions = app.get_functions()
        self.assertEqual(len(functions), 2)
        trigger = functions[0].get_trigger()
        assert trigger is not None
        self.assertEqual(trigger.get_dict_repr()["authLevel"], func.AuthLevel.FUNCTION)
        request = func.HttpRequest(method="GET", url="/api/health", body=b"")
        response = health(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.get_body()),
            {"status": "ok", "service": "orquestador", "phase": 1},
        )
        body = {"mode": "mcp", "near": "zona-demo", "people": 12,
                "max_per_head": 45, "when": "2026-10-23T20:30:00+02:00"}
        for mode in ("mcp", "tools"):
            with patch("function_app.organize", new_callable=AsyncMock) as organize:
                organize.return_value = {"mode": mode, "booking": {"simulated": True}}
                response = asyncio.run(cena(func.HttpRequest(
                    method="POST", url="/api/cena", body=json.dumps({**body, "mode": mode}).encode(),
                )))
                self.assertEqual(response.status_code, 200)
                organize.assert_awaited_once_with("zona-demo", 12, 45, body["when"], mode)
                self.assertEqual(len(json.loads(response.get_body())["trace_id"]), 32)
        with patch("function_app.organize", new_callable=AsyncMock) as organize:
            organize.return_value = {"mode": "a2a", "booking": {"simulated": True}}
            response = asyncio.run(cena(func.HttpRequest(method="POST", url="/api/cena",
                body=json.dumps({**body, "mode": "a2a", "includes_drinks": False}).encode())))
            self.assertEqual(response.status_code, 200)
            organize.assert_awaited_once_with("zona-demo", 12, 45, body["when"], "a2a", includes_drinks=False)
        with patch("function_app.organize", new_callable=AsyncMock) as organize:
            organize.return_value = {"mode": "mcp", "status": "unavailable", "booking": None}
            response = asyncio.run(cena(func.HttpRequest(
                method="POST", url="/api/cena", body=json.dumps(body).encode(),
            )))
            self.assertEqual(response.status_code, 409)
            self.assertIsNone(json.loads(response.get_body())["booking"])
        for bad in ({}, {**body, "mode": "unknown"}, {**body, "people": True},
                    {**body, "when": "2026-10-23"}, {**body, "near": " "}):
            response = asyncio.run(cena(func.HttpRequest(
                method="POST", url="/api/cena", body=json.dumps(bad).encode(),
            )))
            self.assertEqual(response.status_code, 400)
