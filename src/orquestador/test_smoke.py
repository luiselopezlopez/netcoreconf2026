import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import azure.functions as func

from function_app import app, cena, health


class SmokeTest(unittest.TestCase):
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
        with patch("function_app.organize", new_callable=AsyncMock) as organize:
            organize.return_value = {"mode": "mcp", "booking": {"simulated": True}}
            response = asyncio.run(cena(func.HttpRequest(
                method="POST", url="/api/cena", body=json.dumps(body).encode(),
            )))
            self.assertEqual(response.status_code, 200)
            organize.assert_awaited_once()
        with patch("function_app.organize", new_callable=AsyncMock) as organize:
            organize.return_value = {"mode": "mcp", "status": "unavailable", "booking": None}
            response = asyncio.run(cena(func.HttpRequest(
                method="POST", url="/api/cena", body=json.dumps(body).encode(),
            )))
            self.assertEqual(response.status_code, 409)
            self.assertIsNone(json.loads(response.get_body())["booking"])
        for bad in ({}, {**body, "mode": "a2a"}, {**body, "people": True},
                    {**body, "when": "2026-10-23"}, {**body, "near": " "}):
            response = asyncio.run(cena(func.HttpRequest(
                method="POST", url="/api/cena", body=json.dumps(bad).encode(),
            )))
            self.assertEqual(response.status_code, 400)
