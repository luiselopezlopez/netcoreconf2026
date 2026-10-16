import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import azure.functions as func

from function_app import a2a, agent_card, app, health, store
from agent import BalanceRequest, Proposal, evaluate


class SmokeTest(unittest.TestCase):
    def test_health(self):
        functions = app.get_functions()
        self.assertEqual(len(functions), 4)
        self.assertEqual(functions[0].get_bindings()[0].auth_level, func.AuthLevel.FUNCTION)
        request = func.HttpRequest(method="GET", url="/api/health", body=b"")
        response = health(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.get_body()),
            {"status": "ok", "service": "presupuesto", "phase": 1},
        )

    def test_a2a_negotiation(self):
        async def run():
            async def send(payload, task_id=None, context_id=None):
                message = {"role": "user", "messageId": "smoke-message",
                           "parts": [{"kind": "text", "text": json.dumps(payload)}]}
                if task_id:
                    message.update(taskId=task_id, contextId=context_id)
                response = await a2a(func.HttpRequest(method="POST", url="/a2a", body=json.dumps({
                    "jsonrpc": "2.0", "id": "smoke", "method": "message/send",
                    "params": {"message": message},
                }).encode()))
                result = json.loads(response.get_body())
                self.assertNotIn("error", result, result)
                return result["result"]

            store.tasks.clear()
            proposal = {"skill": "aprobar_gasto", "restaurant_id": "plaza", "people": 12,
                        "menu_per_head": 42, "drink_per_head": 6, "max_per_head": 45}
            with patch("agent.evaluate", new_callable=AsyncMock) as evaluate:
                initial = await send(proposal)
                self.assertEqual(initial["status"]["state"], "input-required")
                self.assertEqual(initial["metadata"]["states"], ["submitted", "working", "input-required"])
                evaluate.assert_not_awaited()
                evaluate.return_value = {"approved": False, "per_head": 48}
                completed = await send({"includes_drinks": True}, initial["id"], initial["contextId"])
                self.assertEqual(completed["id"], initial["id"])
                self.assertEqual(completed["metadata"]["states"],
                                 ["submitted", "working", "input-required", "working", "completed"])
                self.assertFalse(completed["artifacts"][0]["parts"][0]["data"]["approved"])
                self.assertTrue(evaluate.call_args.args[0].includes_drinks)
                query = await a2a(func.HttpRequest(method="POST", url="/a2a", body=json.dumps({
                    "jsonrpc": "2.0", "id": 2, "method": "tasks/get", "params": {"id": initial["id"]},
                }).encode()))
                self.assertEqual(json.loads(query.get_body())["result"]["status"]["state"], "completed")
                invalid = await send({"includes_drinks": "yes"}, (await send(proposal))["id"])
                self.assertEqual(invalid["status"]["state"], "failed")
            metadata = json.loads(agent_card(func.HttpRequest(method="GET", url="/.well-known/agent-card.json", body=b"")).get_body())
            self.assertEqual({s["id"] for s in metadata["skills"]}, {"aprobar_gasto", "consultar_saldo"})
            self.assertFalse(metadata["capabilities"]["streaming"])

        asyncio.run(run())

    def test_budget_policy(self):
        async def run():
            with patch.dict("os.environ", AZURE_AI_PROJECT_ENDPOINT="https://project.example",
                            AZURE_AI_MODEL_DEPLOYMENT_NAME="model"), \
                    patch("agent.DefaultAzureCredential"), patch("agent.AIProjectClient"), \
                    patch("agent.FoundryChatClient"), patch("agent.Agent") as agent_class:
                async def use_tools(*_args, **_kwargs):
                    for function in agent_class.call_args.kwargs["tools"]:
                        await function.invoke(arguments={})
                    agent_class.return_value.run.return_value.text = "Decision basada en las herramientas."
                    return agent_class.return_value.run.return_value
                agent_class.return_value.run.side_effect = use_tools
                for menu, drink, includes, people, expected in [
                    (42, 6, True, 12, False), (38, 5, True, 12, True),
                    (42, 6, False, 12, True), (38, 5, True, 16, False),
                ]:
                    result = await evaluate(Proposal(skill="aprobar_gasto", restaurant_id="demo", people=people,
                        menu_per_head=menu, drink_per_head=drink, max_per_head=45, includes_drinks=includes))
                    self.assertEqual(result["approved"], expected)
                    self.assertEqual(result["total"], (menu + (drink if includes else 0)) * people)
                saldo = await evaluate(BalanceRequest(skill="consultar_saldo"))
                self.assertEqual(saldo["balance"], 600)
        asyncio.run(run())
