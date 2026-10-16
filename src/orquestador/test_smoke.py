import json
import unittest

import azure.functions as func

from function_app import app, health


class SmokeTest(unittest.TestCase):
    def test_health(self):
        functions = app.get_functions()
        self.assertEqual(len(functions), 1)
        self.assertEqual(functions[0].get_bindings()[0].auth_level, func.AuthLevel.FUNCTION)
        request = func.HttpRequest(method="GET", url="/api/health", body=b"")
        response = health(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.get_body()),
            {"status": "ok", "service": "orquestador", "phase": 1},
        )
