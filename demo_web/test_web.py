import json
import unittest
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

from demo_web.server import LiveSpans, create_app
from telemetry import MetadataExporter

BODY = {"near": "zona-demo", "people": 12, "max_per_head": 50,
        "when": "2026-10-23T20:30:00+02:00"}


async def fake_runner(**kwargs):
    with trace.get_tracer("demo-test").start_as_current_span(
        "execute_tool search", attributes={"gen_ai.tool.call.arguments": json.dumps(kwargs),
                                           "http.request.header.x-functions-key": "never-publish"}):
        pass
    return {"mode": "mcp", "status": "unavailable", "booking": None}


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = TracerProvider()
        cls.provider.add_span_processor(LiveSpans())
        trace.set_tracer_provider(cls.provider)

    @classmethod
    def tearDownClass(cls):
        cls.provider.shutdown()

    def setUp(self):
        self.app = create_app(fake_runner)
        self.client = self.app.test_client()
        self.demo = self.app.extensions["demo"]

    def request(self, method, path, body=None, headers=None):
        response = self.client.open(path, method=method, data=body, headers=headers or {},
                                    base_url="http://127.0.0.1:8080")
        return response.status_code, response.data, response.headers

    def post(self, body=BODY, headers=None):
        return self.request("POST", "/api/run", json.dumps(body), headers or {
            "Content-Type": "application/json", "X-Demo-Token": self.demo.token})

    def test_static_allowlist(self):
        for path in ("/", "/app.js", "/style.css"):
            code, body, headers = self.request("GET", path)
            self.assertEqual(code, 200)
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Referrer-Policy"], "same-origin")
        for path in ("/.env", "/../README.md", "/server.py"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_session(self):
        code, body, _ = self.request("GET", "/api/config")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"token": self.demo.token, "mode": "mcp",
                                          "modes": ["mcp", "tools", "a2a"], "hosting": "local"})

    def test_host_and_origin(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.post(headers={"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.post(headers={"Content-Type": "application/json",
            "X-Demo-Token": self.demo.token, "Origin": "https://attacker.invalid"})[0], 403)

    def test_validation(self):
        for body in ({}, {**BODY, "mode": "unknown"}, {**BODY, "people": True},
                     {**BODY, "mode": "a2a", "includes_drinks": "yes"},
                     {**BODY, "near": " "}, {**BODY, "when": "2026-10-23"},
                     {**BODY, "max_per_head": float("inf")}, {**BODY, "unknown": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body)[0], 400)
        self.assertEqual(self.request("POST", "/api/run", "x" * 4097, {
            "Content-Type": "application/json", "X-Demo-Token": self.demo.token})[0], 400)

    def test_stream_real_spans_and_result(self):
        code, body, headers = self.post()
        self.assertEqual(code, 200)
        self.assertIn("application/x-ndjson", headers["Content-Type"])
        events = [json.loads(line) for line in body.splitlines()]
        self.assertEqual([event["type"] for event in events],
                         ["started", "span_start", "span_start", "span_end", "span_end", "result"])
        self.assertEqual(events[2]["id"], events[3]["id"])
        self.assertEqual(events[2]["parent"], events[1]["id"])
        self.assertEqual(events[3]["details"]["gen_ai.tool.call.arguments"]["people"], 12)
        self.assertEqual(events[-1]["data"]["trace_id"], events[1]["trace_id"])
        self.assertNotIn(b"never-publish", body)
        self.assertIsNone(events[-1]["data"]["booking"])
        self.assertFalse(self.demo.run_lock.locked())
        code, body, _ = self.post({**BODY, "mode": "tools"})
        self.assertEqual(code, 200)
        tool = next(json.loads(line) for line in body.splitlines()
                    if b'gen_ai.tool.call.arguments' in line)
        self.assertEqual(tool["details"]["gen_ai.tool.call.arguments"]["mode"], "tools")
        code, body, _ = self.post({**BODY, "mode": "a2a", "includes_drinks": False})
        self.assertEqual(code, 200)
        tool = next(json.loads(line) for line in body.splitlines()
                    if b'gen_ai.tool.call.arguments' in line)
        self.assertEqual(tool["details"]["gen_ai.tool.call.arguments"]["mode"], "a2a")
        self.assertFalse(tool["details"]["gen_ai.tool.call.arguments"]["includes_drinks"])
        source = ReadableSpan("chat", attributes={"gen_ai.usage.input_tokens": 12,
                              "gen_ai.tool.call.arguments": "private", "http.url": "private"})
        with patch("telemetry.AzureMonitorTraceExporter.export") as export:
            MetadataExporter.export(object.__new__(MetadataExporter), [source])
        sanitized = export.call_args.args[0][0]
        self.assertEqual(dict(sanitized.attributes), {"gen_ai.usage.input_tokens": 12})
        self.assertEqual(sanitized.events, ())

    def test_concurrency(self):
        with self.demo.run_lock:
            self.assertEqual(self.post()[0], 409)

    def test_execution_error(self):
        async def fail(**_kwargs):
            raise RuntimeError("private-error-detail")
        self.demo.runner = fail
        with self.assertLogs("demo_web", level="ERROR"):
            code, body, _ = self.post()
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body.splitlines()[-1])["type"], "error")
        self.assertNotIn(b"private-error-detail", body)
        self.assertFalse(self.demo.run_lock.locked())

    def test_cloud_requires_identity(self):
        with self.assertRaises(ValueError):
            create_app(fake_runner, cloud_host="demo.azurewebsites.net")
        cloud = create_app(fake_runner, cloud_host="demo.azurewebsites.net", allowed_user="owner-id")
        client = cloud.test_client()
        self.assertEqual(client.get("/", base_url="https://demo.azurewebsites.net").status_code, 403)
        self.assertEqual(client.get("/", base_url="https://demo.azurewebsites.net",
            headers={"X-MS-CLIENT-PRINCIPAL-ID": "another-user"}).status_code, 403)
        response = client.get("/api/config", base_url="https://demo.azurewebsites.net",
                              headers={"X-MS-CLIENT-PRINCIPAL-ID": "owner-id"})
        self.assertEqual(response.status_code, 200)
        assert response.json is not None
        self.assertEqual(response.json["hosting"], "azure")
        headers = {"X-MS-CLIENT-PRINCIPAL-ID": "owner-id",
                   "X-Demo-Token": response.json["token"],
                   "Origin": "https://demo.azurewebsites.net"}
        response = client.post("/api/run", base_url="https://demo.azurewebsites.net",
                               headers=headers, json=BODY)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.assertEqual(json.loads(response.data.splitlines()[-1])["type"], "result")
        for changed in ({"Origin": "https://attacker.invalid"},
                        {"X-Demo-Token": "stale-token"},
                        {"X-MS-CLIENT-PRINCIPAL-ID": "another-user"}):
            response = client.post("/api/run", base_url="https://demo.azurewebsites.net",
                                   headers={**headers, **changed}, json=BODY)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
