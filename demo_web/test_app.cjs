const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const source = readFileSync(join(__dirname, "static", "app.js"), "utf8");

async function browser(respond) {
  const nodes = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      value: "", textContent: "", hidden: false, disabled: false, dataset: {}, elements: [],
      listeners: {}, classList: { remove() {}, toggle() {} },
      addEventListener(event, handler) { this.listeners[event] = handler; },
      replaceChildren() {}, setAttribute() {}, reportValidity() { return true; },
    });
    return nodes.get(id);
  }
  node("dinner-form").elements = ["run", "near", "mode", "people", "price", "when", "offset",
    "includes-drinks"].map(node);
  const calls = [];
  const context = vm.createContext({
    document: { getElementById: node, querySelectorAll: () => [] },
    fetch: async (url, options) => {
      calls.push({ url, options });
      return respond(url, options, calls);
    },
    JSON, SyntaxError, Error, TextDecoder, performance, setInterval, clearInterval,
  });
  vm.runInContext(source, context);
  await new Promise(setImmediate);
  return { node, context, calls };
}

function config(token = "fresh-token") {
  return new Response(JSON.stringify({ token, hosting: "azure" }), {
    headers: { "Content-Type": "application/json" },
  });
}

async function submit(ui) {
  for (const [id, value] of Object.entries({
    near: "zona-demo", mode: "mcp", people: "12", price: "50",
    when: "2026-10-23T20:30", offset: "+02:00",
  })) ui.node(id).value = value;
  await ui.node("dinner-form").listeners.submit({ preventDefault() {} });
}

for (const [name, response, expected] of [
  ["empty 403", () => new Response(null, { status: 403 }), /Acceso rechazado.*HTTP 403/],
  ["empty 503", () => new Response(null, { status: 503 }), /HTTP 503.*vacía/],
  ["HTML 502", () => new Response("<html>proxy details</html>", { status: 502 }),
    /HTTP 502.*no reconocida/],
  ["JSON 409", () => new Response('{"error":"Ya hay una demo en curso."}', {
    status: 409, headers: { "Content-Type": "application/json" },
  }), /Ya hay una demo en curso.*HTTP 409/],
  ["invalid JSON", () => new Response("", {
    status: 500, headers: { "Content-Type": "application/json" },
  }), /JSON incompleto.*HTTP 500/],
  ["expired session", () => new Response(null, { status: 401 }), /sesión web ha caducado/],
  ["login redirect", () => ({ ok: false, type: "opaqueredirect", status: 0 }),
    /sesión web ha caducado/],
]) {
  test(`submission reports ${name} without a JSON parser error`, async () => {
    const ui = await browser((url) => url === "/api/config" ? config() : response());
    await submit(ui);
    assert.match(ui.node("notice").textContent, expected);
    assert.doesNotMatch(ui.node("notice").textContent, /Unexpected end|proxy details/);
    assert.equal(ui.node("status").dataset.state, "error");
    assert.equal(ui.node("run").disabled, false);
    assert.equal(ui.calls.at(-1).options.redirect, "manual");
    assert.equal(ui.calls.at(-1).options.headers["X-Demo-Token"], "fresh-token");
  });
}

test("refreshes a token changed by a server restart before submitting once", async () => {
  let configs = 0;
  const ui = await browser((url) => url === "/api/config" ? config(`token-${++configs}`) :
    new Response('{"type":"error","message":"Test execution failure"}\n', {
      headers: { "Content-Type": "application/x-ndjson" },
    }));
  await submit(ui);
  assert.equal(ui.calls.filter((call) => call.url === "/api/run").length, 1);
  assert.equal(ui.calls.at(-1).options.headers["X-Demo-Token"], "token-2");
  assert.equal(ui.node("notice").textContent, "Test execution failure");
});

test("empty configuration leaves execution disabled with a readable error", async () => {
  const ui = await browser(() => new Response("", {
    headers: { "Content-Type": "application/json" },
  }));
  assert.match(ui.node("notice").textContent, /configuración de sesión está vacía.*HTTP 200/);
  assert.equal(ui.node("run").disabled, true);
});

test("expired session at refresh never submits a booking", async () => {
  let configs = 0;
  const ui = await browser(() => ++configs === 1 ? config() : new Response(null, { status: 401 }));
  await submit(ui);
  assert.match(ui.node("notice").textContent, /sesión web ha caducado/);
  assert.equal(ui.calls.filter((call) => call.url === "/api/run").length, 0);
});
