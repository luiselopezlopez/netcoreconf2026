# Prompt para GitHub Copilot (modo agente)

> Pégalo tal cual en el chat de Copilot con el repositorio vacío abierto. Está escrito para que Copilot trabaje por fases y pida confirmación entre ellas.

---

Actúa como ingeniero senior de Python y Azure. Vas a implementar las tres demos de una charla de 45 minutos titulada "Poliamor en los tiempos de la IA" (NetCoreConf Madrid 2026) sobre MCP, agents as tools y Agent2Agent, y la infraestructura mínima en Azure para ejecutarlas en directo.

## Principio rector: ir a mínimos

Esto es código de demo que dos personas tienen que mantener y levantar la mañana del evento. Optimiza para **pocas piezas, pocas dependencias y cero sorpresas**. Ante la duda entre "completo" y "simple", elige simple. No añadas nada que no esté en este prompt sin preguntar antes.

## Stack obligatorio

- Python 3.12, un `requirements.txt` por función, versiones fijadas.
- **Microsoft Agent Framework** (paquete `agent-framework`, Python) para todos los agentes.
- Modelos servidos desde **Azure AI Foundry** (un único proyecto, un único deployment: `gpt-4.1-mini` o el más barato disponible con tool calling).
- Todo desplegado en **Azure Functions** (plan Flex Consumption, modelo de programación Python v2).
- Autenticación entre componentes con **identidades administradas** y `DefaultAzureCredential`. Sin secretos en código ni en `local.settings.json` versionado.
- Infraestructura en **Bicep** desplegable con `azd up`. Un solo `main.bicep` más los módulos imprescindibles.
- Datos de demo **en memoria** (listas Python). Nada de bases de datos, colas ni Service Bus.

Antes de escribir código, consulta la documentación actual de: el trigger MCP de Azure Functions (`mcpToolTrigger`, extension bundle preview), el paquete `agent-framework` (clases `AzureAIAgentClient`, `MCPStreamableHTTPTool`, método `as_tool()` y el módulo `agent_framework.a2a`) y el protocolo A2A (Agent Card en `/.well-known/agent.json`, JSON-RPC, estados de Task). Las firmas exactas pueden haber cambiado; usa las vigentes y dime qué versiones has fijado.

## Escenario común a las tres demos

Organizar la cena de ponentes: *"Cena para 12 ponentes el viernes, cerca del venue, máximo 45 € por cabeza"*. Tres capacidades:

| Componente | Qué es | Dónde vive |
|---|---|---|
| **Restaurantes** | Servidor MCP con dos tools: `search(near, people, max_per_head)` y `book(restaurant_id, when, people)`. Sin modelo detrás. | Function App `func-restaurantes` |
| **Agenda** | Agente con una tool `free_slots(day, people)` que devuelve franjas libres. Se usa como herramienta del orquestador (`as_tool()`). | Dentro de `func-orquestador` |
| **Presupuesto** | Agente remoto expuesto por A2A: skills `aprobar_gasto` y `consultar_saldo`. Debe poder devolver `input-required` (pregunta si los 45 € incluyen bebida) y rechazar la primera propuesta si supera el límite. | Function App `func-presupuesto`, con **su propia** identidad administrada |
| **Orquestador** | Agente "Cena" que recibe la petición por HTTP y delega en Restaurantes (MCP), Agenda (as tool) y Presupuesto (A2A). | Function App `func-orquestador` |

Datos de ejemplo: 5 restaurantes (dos por encima de 45 €, uno sin disponibilidad el viernes, dos válidos) y dos franjas libres (20:30 y 21:15). El resultado esperado de la demo completa es una reserva en un restaurante válido a las 20:30 aprobada por Presupuesto tras un rechazo previo.

## Estructura del repositorio

```
.
├── azure.yaml                 # azd: tres servicios → tres Function Apps
├── infra/
│   ├── main.bicep             # RG, Foundry, storage, App Insights, plan, 3 Function Apps, RBAC
│   └── main.parameters.json
├── src/
│   ├── restaurantes/          # function_app.py con dos mcpToolTrigger + data.py
│   ├── orquestador/           # function_app.py (HTTP trigger) + agents.py + data.py
│   └── presupuesto/           # function_app.py (agent card + endpoint A2A) + agent.py
├── scripts/
│   ├── warmup.sh              # una llamada a cada Function App para evitar cold start
│   ├── demo1.sh               # lista tools MCP y lanza al orquestador solo con MCP
│   ├── demo2.sh               # orquestador con Agenda como tool
│   └── demo3.sh               # orquestador completo con Presupuesto por A2A
├── .vscode/mcp.json           # configuración para consumir Restaurantes desde VS Code
└── README.md
```

El orquestador acepta un parámetro `mode` (`mcp` | `tools` | `a2a`) para que las tres demos usen el mismo código y solo cambie qué herramientas se registran.

## Infraestructura (Bicep) — lista cerrada

1. Un grupo de recursos.
2. Una cuenta Azure AI Services con un proyecto de Foundry y un deployment de modelo.
3. Una cuenta de almacenamiento compartida por las tres Function Apps.
4. Un Application Insights (+ Log Analytics) compartido; las Functions exportan trazas OpenTelemetry del Agent Framework ahí.
5. Un plan Flex Consumption y tres Function Apps (Python 3.12), cada una con identidad administrada asignada por el sistema.
6. RBAC: `func-orquestador` y `func-presupuesto` con rol *Azure AI User* sobre el proyecto de Foundry. `func-orquestador` con permiso para invocar `func-presupuesto` (usa autenticación Easy Auth con Entra o, si complica demasiado, clave de función leída de app settings inyectada por Bicep; indícame cuál eliges y por qué).
7. `func-restaurantes` protegido con clave de función; el orquestador y VS Code la pasan en la cabecera `x-functions-key`.

Nada más: sin Key Vault, sin VNet, sin APIM, sin Container Apps, sin Cosmos.

## Observabilidad

Habilita el tracing del Agent Framework hacia Application Insights para que en la demo 2 se pueda abrir la traza y ver el árbol de llamadas (orquestador → Agenda → `free_slots`, orquestador → `search`, orquestador → `book`) con tokens y duración. Documenta en el README la consulta KQL o la vista de Foundry donde se ve.

## Entregables de documentación

- `README.md` con: prerequisitos, `azd up`, cómo ejecutar cada demo con los scripts, cómo configurar `.vscode/mcp.json`, cómo ver las trazas y cómo apagar todo (`azd down`).
- Un bloque "Guion técnico" por demo con los comandos en el orden exacto en que se lanzan en el escenario y la salida esperada.

## Fases de trabajo

Trabaja en este orden y para al final de cada fase para que la revise:

1. **Esqueleto e infra**: estructura de carpetas, `azure.yaml`, Bicep completo, `azd up` funcionando con tres Functions "hola mundo".
2. **Demo 1**: servidor MCP de Restaurantes + orquestador en modo `mcp` + `.vscode/mcp.json`.
3. **Demo 2**: agente Agenda como tool + tracing visible en Application Insights.
4. **Demo 3**: Presupuesto por A2A con los estados `submitted → working → input-required → working → completed` y el rechazo de la primera propuesta.
5. **Scripts y README**.

## Criterios de aceptación

- `azd up` desde cero termina sin intervención manual en menos de 15 minutos.
- Cada `scripts/demoN.sh` se ejecuta en menos de 30 segundos tras el warmup y produce la salida descrita.
- Ningún secreto en el repositorio; `local.settings.json` está en `.gitignore` y hay un `local.settings.sample.json`.
- Cada Function App tiene menos de 200 líneas de Python propias (sin contar datos de ejemplo).
- `azd down --purge` deja la suscripción limpia.

## Lo que NO quiero

- Frameworks de orquestación adicionales, abstracciones "por si acaso", capas de repositorio, inyección de dependencias ni interfaces.
- Tests más allá de un smoke test por Function que compruebe que arranca y responde.
- CI/CD, Dockerfiles, dev containers ni pre-commit.
- Persistencia de ningún tipo.
- Cambios en el alcance sin preguntar.

Empieza por la fase 1. Antes de generar código, resume en diez líneas cómo vas a resolver los dos puntos con más riesgo (el trigger MCP de Functions y el endpoint A2A dentro de una Function HTTP) y qué versiones de paquetes vas a fijar.
