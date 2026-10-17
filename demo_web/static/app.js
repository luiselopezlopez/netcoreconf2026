"use strict";

const $ = (id) => document.getElementById(id);
const form = $("dinner-form");
const spans = new Map();
let token = "";
let running = false;
let log = [];
let timer;
let started;

async function responseError(response) {
  const http = `HTTP ${response.status}`;
  if (response.type === "opaqueredirect" || response.redirected || response.status === 401) {
    return new Error("La sesión web ha caducado. Recarga la página para iniciar sesión de nuevo.");
  }
  const text = await response.text();
  if (response.headers.get("Content-Type")?.includes("application/json")) {
    try {
      const data = JSON.parse(text);
      if (typeof data?.error === "string" && data.error) return new Error(`${data.error} (${http})`);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      return new Error(`El servidor devolvió JSON incompleto o inválido (${http}). No se ha recibido un resultado.`);
    }
  }
  if (response.status === 403) {
    return new Error(`Acceso rechazado (${http}). Recarga la página para renovar la sesión. Si persiste, revisa la autorización y la protección de origen de App Service.`);
  }
  return new Error(`No se pudo iniciar la ejecución (${http}). El servidor devolvió una respuesta ${text ? "no reconocida" : "vacía"}.`);
}

async function loadConfig() {
  const response = await fetch("/api/config", { redirect: "manual" });
  if (!response.ok) throw await responseError(response);
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error("No se pudo iniciar la sesión web. Recarga la página para iniciar sesión de nuevo.");
  }
  let config;
  try {
    config = await response.json();
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    throw new Error(`La configuración de sesión está vacía o incompleta (HTTP ${response.status}). Recarga la página.`);
  }
  if (typeof config?.token !== "string" || !config.token) throw new Error("La sesión web no contiene un token válido.");
  token = config.token;
  return config;
}

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
  for (const id of ["preset-book", "preset-empty", "clear", "chapter-mcp", "chapter-tools", "chapter-a2a"]) $(id).disabled = busy;
  $("download").disabled = busy || !log.length;
}

function clearView() {
  spans.clear();
  log = [];
  $("events").replaceChildren();
  $("conversation-list").replaceChildren();
  $("capability-list").replaceChildren();
  $("conversation").hidden = true;
  $("capabilities").hidden = true;
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
  $("node-agent").classList.toggle("active", active.some((name) => name === "invoke_agent Cena"));
  $("node-mcp").classList.toggle("active", active.some((name) => /^execute_tool (search|book)$/.test(name)));
  $("node-agenda").classList.toggle("active", active.some((name) => /Agenda|consultar_agenda|free_slots/.test(name)));
  $("node-budget").classList.toggle("active", active.some((name) => /a2a |consultar_presupuesto/.test(name)));
  $("node-model").classList.toggle("active", active.some((name) => /^(chat|text_completion|generate_content) /.test(name)));
}

function titleFor(name) {
  if (name === "mcp discover Restaurantes") return "MCP → initialize / tools/list";
  if (name === "execute_tool search") return "MCP → search";
  if (name === "execute_tool book") return "MCP → book";
  if (name === "execute_tool consultar_agenda") return "Cena → Agenda · as_tool()";
  if (name === "execute_tool free_slots") return "Agenda → free_slots";
  if (name === "execute_tool book_after_agenda") return "Cena → reserva autorizada por Agenda";
  if (name === "execute_tool consultar_presupuesto") return "Cena ⇄ Presupuesto · negociación A2A";
  if (name === "execute_tool negociar_cena") return "Cena → negociación: Agenda + Presupuesto A2A";
  if (name === "a2a discover Presupuesto") return "A2A → obtener Agent Card";
  if (name === "a2a message/send Presupuesto") return "A2A ⇄ message/send · tarea remota";
  if (name.startsWith("invoke_agent")) return `Agente ${name.slice("invoke_agent ".length)}`;
  if (/^(chat|text_completion|generate_content) /.test(name)) return "Agente ⇄ modelo de Foundry";
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
    const parent = spans.get(event.parent);
    const depth = Math.min(4, parent ? parent.depth + 1 : 0);
    li.dataset.depth = String(depth);
    span = { li, title, meta, raw, name: event.name, parent: event.parent, traceId: event.trace_id, depth, ended: false };
    spans.set(event.id, span);
  }
  span.title.textContent = titleFor(event.name);
  if (event.type === "span_end") {
    span.ended = true;
    span.li.classList.remove("running");
    span.li.classList.toggle("failed", event.failed);
    const task = event.details["gen_ai.tool.call.result"];
    const state = task?.state ? `${task.state} · ` : "";
    span.meta.textContent = `${event.failed ? "Error · " : ""}${state}${(event.duration_ms / 1000).toFixed(2)} s`;
    if (task?.states) span.title.textContent += ` · ${task.states.join(" → ")}`;
    span.raw.textContent = JSON.stringify({ span: event.name, parent: span.parent, trace_id: span.traceId, ...event.details }, null, 2);
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

function prettyContent(content) {
  if (typeof content !== "string") return JSON.stringify(content, null, 2);
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    return content;
  }
}

function renderConversation(event) {
  const item = document.createElement("li");
  item.className = `conversation-message ${event.role === "assistant" ? "agent-message" : "user-message"}`;
  const label = document.createElement("strong");
  label.textContent = `${event.agent} · ${event.role === "assistant" ? "Respuesta" : "Petición"}`;
  const content = document.createElement("pre");
  content.textContent = prettyContent(event.content);
  item.append(label, content);
  $("conversation-list").append(item);
  $("conversation").hidden = false;
}

function addCapabilityItem(list, title, description, metadata) {
  const item = document.createElement("li");
  const heading = document.createElement("h4");
  heading.textContent = title;
  item.append(heading);
  if (description) item.append(paragraph("capability-description", description));
  if (metadata) {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(metadata, null, 2);
    item.append(pre);
  }
  list.append(item);
}

function renderCapabilities(event) {
  const list = $("capability-list");
  const details = event.details || {};
  if (event.system === "MCP") {
    for (const tool of details.tools || []) {
      addCapabilityItem(list, `${tool.name} · herramienta MCP`, tool.description,
        tool.parameters);
    }
  } else if (event.system === "A2A") {
    addCapabilityItem(list, `${details.name || "Presupuesto"} · Agent Card`,
      details.description, {
        version: details.version,
        protocolVersion: details.protocolVersion,
        capabilities: details.capabilities,
      });
    for (const skill of details.skills || []) {
      addCapabilityItem(list, `${skill.name || skill.id} · skill A2A`,
        skill.description, { id: skill.id, tags: skill.tags, examples: skill.examples });
    }
  } else {
    addCapabilityItem(list, event.title, "", details);
  }
  $("capabilities").hidden = false;
}

function showResult(event) {
  const data = event.data;
  $("result").hidden = false;
  $("booking-summary").replaceChildren();
  $("answer").textContent = data.result;
  $("result-json").textContent = JSON.stringify(data, null, 2);
  $("elapsed").textContent = elapsed(event.duration_ms);
  if (data.agenda) {
    $("booking-summary").append(paragraph("muted",
      `Agenda consultada: ${data.agenda.slots.join(", ") || "sin huecos"} · ${data.agenda.day} · ${data.agenda.people} ponentes.`));
  }
  for (const decision of data.budget || []) {
    $("booking-summary").append(paragraph("muted",
      `Presupuesto · ${decision.restaurant_id}: ${decision.approved ? "APROBADO" : "RECHAZADO"} · ${decision.per_head} €/persona · límite ${decision.max_per_head} €${decision.includes_drinks ? " con bebida" : " sin bebida"}.`));
  }
  const booking = data.booking;
  if (!booking) {
    $("result-title").textContent = "Esta vez no hay mesa.";
    $("booking-summary").append(paragraph("muted", data.budget?.length
      ? "Presupuesto ha rechazado todas las propuestas. No se ha realizado ninguna reserva."
      : data.agenda
      ? "Agenda no permite la hora solicitada para ese grupo. No se ha realizado ninguna reserva."
      : "La comprobación MCP no encontró candidatos. No se ha llamado al modelo ni realizado una reserva."));
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
  if (event.type === "conversation") renderConversation(event);
  if (event.type === "discovery") renderCapabilities(event);
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
  const request = { mode: $("mode").value, near, people: Number($("people").value), max_per_head: Number($("price").value),
    when: $("when").value + ":00" + $("offset").value };
  if (request.mode === "a2a") request.includes_drinks = $("includes-drinks").checked;
  log.push({ type: "request", data: request, at: new Date().toISOString() });
  setBusy(true);
  started = performance.now();
  timer = setInterval(() => { $("elapsed").textContent = elapsed(performance.now() - started); }, 250);
  status("Iniciando", "running");
  updateNodes();
  try {
    await loadConfig();
    const response = await fetch("/api/run", { method: "POST", redirect: "manual",
      headers: { "Content-Type": "application/json", "X-Demo-Token": token }, body: JSON.stringify(request) });
    if (!response.ok) throw await responseError(response);
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
  $("price").value = $("mode").value === "mcp" ? "50" : "45";
  $("includes-drinks").checked = true;
  $("when").value = "2026-10-23T20:30";
  $("offset").value = "+02:00";
  for (const [id, selected] of [["preset-book", !empty], ["preset-empty", empty]]) {
    $(id).classList.toggle("selected", selected);
    $(id).setAttribute("aria-pressed", String(selected));
  }
}
function selectMode(mode) {
  if (running) return;
  $("mode").value = mode;
  $("demo-label").textContent = `EL LABORATORIO / DEMO ${{mcp: "01", tools: "02", a2a: "03"}[mode]}`;
  $("node-agenda").hidden = mode === "mcp";
  $("node-budget").hidden = mode !== "a2a";
  $("drinks-field").hidden = mode !== "a2a";
  $("price-label").textContent = mode === "a2a" ? "Límite / persona (€)" : "Menú / persona (€)";
  $("price-help").textContent = mode === "a2a"
    ? "La casilla responde a la aclaración real de Presupuesto (input-required). Con 45 € y bebida: La Plaza (48 €) se rechaza y El Patio (43 €) se aprueba. No se modifica la hora."
    : "El límite solo incluye el menú, bebida aparte. Agenda tiene huecos el viernes a las 20:30 y 21:15 para hasta 12 ponentes. No se cambia la hora solicitada.";
  for (const value of ["mcp", "tools", "a2a"]) {
    $(`chapter-${value}`).classList.toggle("current", mode === value);
    $(`chapter-${value}`).setAttribute("aria-pressed", String(mode === value));
  }
  clearView();
  preset(false);
}
$("mode").addEventListener("change", () => selectMode($("mode").value));
$("chapter-mcp").addEventListener("click", () => selectMode("mcp"));
$("chapter-tools").addEventListener("click", () => selectMode("tools"));
$("chapter-a2a").addEventListener("click", () => selectMode("a2a"));
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

setBusy(true);
loadConfig().then((config) => {
  const cloud = config.hosting === "azure";
  $("hosting-label").textContent = cloud ? "AZURE · ENTRA · MCP REAL" : "LOCAL → AZURE REAL";
  $("hosting-note").textContent = cloud
    ? "Cena se ejecuta en Azure App Service con identidad administrada. Acceso protegido por Microsoft Entra. El modelo y el MCP también están en Azure."
    : "Cena se ejecuta en este equipo con Azure CLI. El modelo y Restaurantes están en Azure. No usa la Function HTTP de Cena.";
  setBusy(false);
  status("Lista para conectar");
}).catch((error) => { notice(error.message); status("Servidor no disponible", "error"); });
