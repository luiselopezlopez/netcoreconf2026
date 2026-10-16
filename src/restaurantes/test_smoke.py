import json
import unittest

import azure.functions as func

from function_app import app, book, health, search


class SmokeTest(unittest.TestCase):
    def test_health(self):
        functions = app.get_functions()
        self.assertEqual(len(functions), 3)
        trigger = functions[0].get_trigger()
        assert trigger is not None
        self.assertEqual(trigger.get_dict_repr()["authLevel"], func.AuthLevel.FUNCTION)
        request = func.HttpRequest(method="GET", url="/api/health", body=b"")
        response = health(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.get_body()),
            {"status": "ok", "service": "restaurantes", "phase": 1},
        )
        found = json.loads(search(json.dumps({"arguments": {
            "near": "zona-demo", "people": 12, "max_per_head": 45,
        }})))
        self.assertEqual([r["id"] for r in found["restaurants"]], ["puerto", "plaza", "patio"])
        booking = json.loads(book(json.dumps({"arguments": {
            "restaurant_id": "plaza", "when": "2026-10-23T20:30:00+02:00", "people": 12,
        }})))
        self.assertEqual(booking["restaurant_id"], "plaza")
        self.assertTrue(booking["simulated"])
        with self.assertRaises(ValueError):
            book(json.dumps({"arguments": {
                "restaurant_id": "puerto", "when": "2026-10-23T20:30:00", "people": 12,
            }}))
