"use strict";

const $ = (id) => document.getElementById(id);
const form = $("dinner-form");
const spans = new Map();
let token = "";
let running = false;
let log = [];
let timer;
let started;

function status(text, state = "") {
  $("status").textContent = text;
  $("status").dataset.state = state;
}

function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
}

function elapsed(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function setBusy(busy) {
  running = busy;
  for (const control of form.elements) control.disabled = busy;
  $("run").textContent = busy ? "Ejecutando…" : "Organizar cena ↗";
  for (const id of ["preset-book", "preset-empty", "clear"]) $(id).disabled = busy;
  $("download").disabled = busy || !log.length;
}

function clearView() {
  spans.clear();
  log = [];
  $("events").replaceChildren();
  $("empty-state").hidden = false;
  $("result").hidden = true;
  $("notice").hidden = true;
  $("elapsed").textContent = "00:00";
  $("download").disabled = true;
  for (const node of document.querySelectorAll(".active")) node.classList.remove("active");
  status("Lista para conectar");
}

function updateNodes() {
  const active = [...spans.values()].filter((span) => !span.ended).map((span) => span.name);
  $("node-request").classList.toggle("active", running);
  $("node-agent").classList.toggle("active", active.some((name) => name.startsWith("invoke_agent")));
  $("node-mcp").classList.toggle("active", active.some((name) => name.startsWith("execute_tool")));
  $("node-model").classList.toggle("active", active.some((name) => /^(chat|text_completion|generate_content) /.test(name)));
}

function titleFor(name) {
  if (name === "execute_tool search") return "MCP → search";
  if (name === "execute_tool book") return "MCP → book";
  if (name.startsWith("invoke_agent")) return "Agente Cena";
  if (/^(chat|text_completion|generate_content) /.test(name)) return "Cena ⇄ modelo de Foundry";
  return name;
}

function spanEvent(event) {
  let span = spans.get(event.id);
  if (!span) {
    const li = document.createElement("li");
    li.className = "event running";
    const number = document.createElement("span");
    number.className = "event-number";
    number.textContent = String(spans.size + 1).padStart(2, "0");
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const title = document.createElement("span");
    title.className = "event-title";
    const meta = document.createElement("span");
    meta.className = "event-meta";
    meta.textContent = "En curso";
    summary.append(title, meta);
    const raw = document.createElement("pre");
    raw.textContent = "Esperando el cierre de la llamada…";
    details.append(summary, raw);
    li.append(number, details);
    $("events").append(li);
    span = { li, title, meta, raw, name: event.name, ended: false };
    spans.set(event.id, span);
  }
  span.title.textContent = titleFor(event.name);
  if (event.type === "span_end") {
    span.ended = true;
    span.li.classList.remove("running");
    span.li.classList.toggle("failed", event.failed);
    span.meta.textContent = `${event.failed ? "Error · " : ""}${(event.duration_ms / 1000).toFixed(2)} s`;
    span.raw.textContent = JSON.stringify({ span: event.name, ...event.details }, null, 2);
  } else {
    status(titleFor(event.name), "running");
  }
  updateNodes();
}

function paragraph(className, text) {
  const element = document.createElement("p");
  element.className = className;
  element.textContent = text;
  return element;
}

function showResult(event) {
  const data = event.data;
  $("result").hidden = false;
  $("booking-summary").replaceChildren();
  $("answer").textContent = data.result;
  $("result-json").textContent = JSON.stringify(data, null, 2);
  $("elapsed").textContent = elapsed(event.duration_ms);
  const booking = data.booking;
  if (!booking) {
    $("result-title").textContent = "Esta vez no hay mesa.";
    $("booking-summary").append(paragraph("muted", "La comprobación MCP no encontró candidatos. No se ha llamado al modelo ni realizado una reserva."));
    status("Sin disponibilidad", "done");
    return;
  }
  $("result-title").textContent = "Reserva ficticia confirmada.";
  $("booking-summary").append(paragraph("booking-name", booking.restaurant_name || booking.restaurant_id));
  const facts = document.createElement("div");
  facts.className = "booking-facts";
  const currency = (value) => new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(value);
  for (const [label, value] of [
    ["comensales", booking.people], ["menú / persona", currency(booking.menu_per_head)],
    ["bebida / persona", currency(booking.drink_per_head)],
    ["total / persona", currency(booking.menu_per_head + booking.drink_per_head)],
  ]) {
    const fact = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = value;
    fact.append(strong, document.createTextNode(label));
    facts.append(fact);
  }
  $("booking-summary").append(facts, paragraph("booking-id", `${booking.when} · ${booking.booking_id} · SIMULADA`));
  status("Reserva verificada", "done");
}

function receive(event) {
  if (event.type === "heartbeat") return;
  log.push(event);
  if (event.type === "span_start" || event.type === "span_end") spanEvent(event);
  if (event.type === "started") status("Conectando con MCP", "running");
  if (event.type === "result") showResult(event);
  if (event.type === "error") {
    notice(event.message);
    status("Ejecución fallida", "error");
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (running || !form.reportValidity()) return;
  const near = $("near").value.trim();
  if (!near) { $("near").focus(); notice("Indica una zona, no solo espacios."); return; }
  clearView();
  $("empty-state").hidden = true;
  const request = { near, people: Number($("people").value), max_per_head: Number($("price").value),
    when: $("when").value + ":00" + $("offset").value };
  log.push({ type: "request", data: request, at: new Date().toISOString() });
  setBusy(true);
  started = performance.now();
  timer = setInterval(() => { $("elapsed").textContent = elapsed(performance.now() - started); }, 250);
  status("Iniciando", "running");
  updateNodes();
  try {
    const response = await fetch("/api/run", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Demo-Token": token }, body: JSON.stringify(request) });
    if (!response.ok) throw new Error((await response.json()).error || `Error HTTP ${response.status}`);
    if (!response.headers.get("Content-Type")?.includes("application/x-ndjson")) {
      throw new Error("La sesión web ha caducado. Recarga la página para iniciar sesión de nuevo.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        if (line) receive(JSON.parse(line));
      }
      if (done) break;
    }
    if (buffer.trim() || !log.some((event) => event.type === "result" || event.type === "error")) {
      throw new Error("La conexión terminó sin un resultado completo. La ejecución puede seguir en el servidor.");
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Error de conexión.";
    log.push({ type: "connection_error", message });
    notice(message);
    status("No se pudo completar", "error");
  } finally {
    clearInterval(timer);
    for (const span of spans.values()) {
      if (!span.ended) { span.ended = true; span.li.classList.remove("running"); span.meta.textContent = "Sin cierre recibido"; }
    }
    setBusy(false);
    updateNodes();
  }
});

function preset(empty) {
  $("near").value = empty ? "zona-sin-restaurantes" : "zona-demo";
  $("people").value = "12";
  $("price").value = "50";
  $("when").value = "2026-10-23T20:30";
  $("offset").value = "+02:00";
  for (const [id, selected] of [["preset-book", !empty], ["preset-empty", empty]]) {
    $(id).classList.toggle("selected", selected);
    $(id).setAttribute("aria-pressed", String(selected));
  }
}
$("preset-book").addEventListener("click", () => preset(false));
$("preset-empty").addEventListener("click", () => preset(true));
$("clear").addEventListener("click", clearView);
$("download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(log, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `poliamor-${new Date().toISOString().replaceAll(":", "-")}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

fetch("/api/config").then(async (response) => {
  if (!response.ok) throw new Error("No se pudo iniciar la sesión web.");
  const config = await response.json();
  token = config.token;
  const cloud = config.hosting === "azure";
  $("hosting-label").textContent = cloud ? "AZURE · ENTRA · MCP REAL" : "LOCAL → AZURE REAL";
  $("hosting-note").textContent = cloud
    ? "Cena se ejecuta en Azure App Service con identidad administrada. Acceso protegido por Microsoft Entra. El modelo y el MCP también están en Azure."
    : "Cena se ejecuta en este equipo con Azure CLI. El modelo y Restaurantes están en Azure. No usa la Function HTTP de Cena.";
  setBusy(false);
  status("Lista para conectar");
}).catch((error) => { notice(error.message); status("Servidor no disponible", "error"); });
