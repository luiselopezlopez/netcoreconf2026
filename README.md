# Poliamor en los tiempos de la IA

Demos para NetCoreConf: MCP, agents as tools y Agent2Agent, con Microsoft
Agent Framework y Azure Functions.

## Estado: fase 2

Las fases 1 y 2 estan desplegadas y verificadas el **2026-10-16** en `MCT Luise 2`,
grupo `rg-poliamor-demo`, region `spaincentral`.
La demo MCP ya busca y reserva restaurantes ficticios mediante el agente
Cena. La web local y la web en Azure permiten ver trazas del framework en directo.
Agenda, exportacion de trazas a Azure y negociacion A2A todavia no estan implementadas.
Las fases siguientes se implementan despues de revisar la anterior:

1. Esqueleto, infraestructura y tres Functions funcionando.
2. Restaurantes por MCP y orquestador en modo `mcp`.
3. Agenda mediante `as_tool()` y trazas.
4. Presupuesto remoto por A2A.
5. Guiones Bash, ensayo y documentacion final.

El alcance procede del [documento de referencia](prompt-copilot-demos-poliamor.md)
y de la [presentacion](Poliamor_en_los_tiempos_de_la_IA_NetCoreConf.pptx).

## Infraestructura

[azure.yaml](azure.yaml) despliega los tres servicios. La infraestructura esta
en [main.bicep](infra/main.bicep) y [resources.bicep](infra/resources.bicep):

- Un grupo `rg-<entorno>`, exclusivo de estas demos.
- Tres Function Apps Linux, Python 3.12, cada una con identidad administrada
  de sistema y su propio plan Flex Consumption FC1.
- Storage LRS compartido, sin claves de cuenta, con host IDs y contenedores
  de despliegue distintos.
- Un Application Insights y un workspace Log Analytics compartidos.
- Un recurso Foundry, proyecto `cena` y deployment `gpt-4.1-mini`,
  version `2025-04-14`, SKU `GlobalStandard`, capacidad 10.
- Rol Foundry User (antes Azure AI User, mismo ID) sobre el proyecto para
  Orquestador y Presupuesto. Restaurantes no tiene acceso al modelo.
- Roles Blob Data Owner para el runtime/despliegue y Monitoring Metrics
  Publisher para telemetria con identidad.

No hay bases de datos, colas de negocio, Service Bus, Key Vault, VNet, APIM,
Docker ni CI/CD. Los contenedores de Storage contienen paquetes y datos del
host Functions, no persistencia del escenario.

### Coste y region

Region acordada: `spaincentral`. Comprobar disponibilidad y cuota antes de
reprovisionar. No se cambia automaticamente de region o modelo.

Flex escala a cero, sin instancias always-ready. Los tres planes no reservan
maquinas: se factura ejecucion; el modelo GlobalStandard se factura por
tokens, no como capacidad provisionada PTU. Storage y la ingestion/retencion
de logs pueden generar coste aunque las demos apenas se usen.

No es un despliegue gratuito ni hay un tope de factura. El coste depende de
las llamadas y del volumen almacenado. Para orientarse: consultar
[precios de Functions](https://azure.microsoft.com/pricing/details/functions/),
[precios de Azure OpenAI](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/)
y Cost Management. La consulta regional de Retail Prices realizada durante
el preflight devolvio ceros no utilizables como estimacion: no se interpretan
como garantia de gratuidad.

## Prerrequisitos

- Python **3.12** y entorno virtual local.
- Azure CLI autenticado, Azure Developer CLI (`azd`) y PowerShell 7 (`pwsh`,
  utilizado por el hook de comprobacion de contexto).
- Functions Core Tools v4 para ejecutar las apps localmente.
- Permiso para crear recursos y asignar roles en la suscripcion destino.
- Proveedores Microsoft.Web, Microsoft.Storage, Microsoft.Insights,
  Microsoft.OperationalInsights y Microsoft.CognitiveServices registrados.
- Cuota para el modelo y capacidad Flex en la region elegida.
- Bash funcional para los futuros guiones `.sh`; no se necesita en fase 1.

Versiones verificadas en fase 1: Python 3.12.10, Core Tools 4.13.0, azd 1.32.0,
Bicep 0.41.2 y `azure-functions==1.25.0`.
Cada app tiene su propio requirements. Orquestador usa los componentes
oficiales `agent-framework-core`, `agent-framework-azure-ai` y
`agent-framework-openai`, todos fijados en `1.0.0rc6`, sin el metapaquete
que instala integraciones adicionales. El conjunto con `azure-ai-projects==2.4.0`,
`azure-identity==1.26.0` y `mcp==1.26.0` se ha probado en Python 3.12 y Azure.
Las versiones exactas estan en [requirements.txt](src/orquestador/requirements.txt).

**Compatibilidad:** `AzureAIAgentClient` esta deprecated y utiliza Agents V1.
Se mantiene el cliente previsto por la demo, comprobado contra este proyecto;
no se presenta como recomendacion para proyectos nuevos. Cada peticion con
candidatos crea un agente/hilo transitorio y los elimina al terminar,
tambien en caso de error.
A2A y exportacion OpenTelemetry se fijaran en sus fases correspondientes.

La instalacion global de Core Tools de esta maquina devuelve un error al
iniciar: falta `Azure.Security.KeyVault.Secrets, Version=4.6.0.0`.
No se ha modificado esa instalacion compartida. Se ha instalado y verificado
por SHA256 la distribucion oficial 4.16.0 en
`.azure\tools\core-tools-4.16.0`. Para usarla desde la raiz:

```powershell
$env:PATH = (Join-Path $PWD '.azure\tools\core-tools-4.16.0') + ';' + $env:PATH
```

Con esta copia aislada el host local arranca y responde al contrato health.
Los tests Python no dependen de Core Tools.

## Web para presentar la demo MCP

Desde la raiz, con la sesion de `az login` activa y los requirements de
la web instalados en `.venv` (incluyen los de Orquestador):

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\demo_web\requirements.txt
pwsh -NoProfile -File .\scripts\start-demo-web.ps1
```

Abrir **http://127.0.0.1:8080**. Tambien se puede usar la tarea VS Code
**Terminal > Run Task > demo: web**. Para otro puerto o entorno:

```powershell
pwsh -NoProfile -File .\scripts\start-demo-web.ps1 -Port 8081 -EnvironmentName poliamor-demo
```

La ejecucion local no requiere npm, Core Tools ni despliegue nuevo. El script carga los
outputs de azd, comprueba la suscripcion activa y obtiene la clave MCP sin
imprimirla. La identidad de Azure CLI debe tener acceso al proyecto Foundry
y permiso para consultar las claves de Restaurantes. No usa el proyecto
seleccionado en Foundry Toolkit. Las variables del proceso se restauran al salir.

**Guion de escenario:**

1. Elegir **Con reserva** y pulsar **Organizar cena**: 12 personas, viernes
   23/10/2026 a las 20:30 UTC+02, zona-demo, limite de menu 50 EUR.
2. Seguir la comprobacion inicial `search` de MCP y, despues, el agente Cena,
   sus llamadas al modelo de Foundry y sus herramientas `search` / `book`.
   Abrir una llamada para ver sus argumentos, resultado y duracion reales.
3. Mostrar la reserva ficticia y el menu + bebida por persona. En MCP el
   limite solo se aplica al menu; no hay negociacion presupuestaria A2A.
4. Elegir **Sin disponibilidad** y repetir: solo se ejecuta el preflight
   MCP, sin modelo ni reserva. Los pasos de Agenda y Presupuesto son
   pendientes, no botones funcionales ni secuencias simuladas.
5. **Descargar registro** guarda el ensayo visible en JSON sin credenciales.
   **Limpiar vista** borra la pantalla, no cancela ni deshace ejecuciones.

El backend [server.py](demo_web/server.py) ejecuta el mismo `organize` de
Orquestador **en el proceso web**, con el modelo Foundry y el MCP de Restaurantes
remotos. No llama a `/api/cena` de Azure ni usa la identidad administrada
de esa Function. Las trazas son spans OpenTelemetry reales del framework,
incluido el preflight invocado mediante su `FunctionTool`; no se muestran
razonamientos internos, prompts del modelo ni headers de autenticacion.
El frontend usa solo archivos locales, sin CDN ni fuentes externas.

En modo local escucha exclusivamente en loopback, exige Host/origen local y un token de
sesion para ejecutar, limita el cuerpo y permite una sola ejecucion simultanea.
No publicar el servidor de desarrollo directamente en Internet; para Azure
se usa la configuracion protegida descrita mas abajo. Argumentos y
resultados de herramientas se capturan **solo en el proceso web**;
usar datos ficticios. No hay exportador de telemetria ni historial persistente.
Cerrar la pestana no cancela el agente: esperar a que termine antes de
parar con Ctrl+C para permitir la limpieza de agente/hilo.

Pruebas locales del backend, sin consumo Azure:

```powershell
.\.venv\Scripts\python.exe -m unittest demo_web.test_web
```

## Desplegar los servicios Azure

### Publicar la web en el entorno existente

Web desplegada en `poliamor-demo`:
**https://web-poliamor-wnmjunhobdnpc.azurewebsites.net**.
Abrirla e iniciar sesion con la misma cuenta de Microsoft Entra usada para
provisionar el entorno. Elegir **Con reserva** y pulsar **Organizar cena**
para seguir las llamadas reales al modelo y a las herramientas MCP.

Verificacion del 2026-10-16: `/health` devuelve HTTP 200 con
`{"service":"demo-web","status":"ok"}`; `/` y `/api/config` sin autenticar
redirigen a Microsoft Entra (HTTP 302). La prueba completa desde la web
de Azure queda pendiente de iniciar sesion interactivamente; no se ha
verificado aun una reserva ejecutada desde ese hosting.

La web se despliega aparte de las Functions, con
[web.bicep](infra/web.bicep). No hay que ejecutar `azd provision` sobre
la infraestructura base para agregar la web. Despues de validar el destino
y los costes:

```powershell
.\scripts\provision-demo-web.ps1 -ValidateOnly
.\scripts\provision-demo-web.ps1
$env:AZD_CONFIG_DIR = Join-Path $PWD '.azure\azd-config'
azd deploy web --environment poliamor-demo --no-prompt
azd env get-value SERVICE_WEB_URI --environment poliamor-demo
```

La primera compilacion remota y el arranque pueden tardar varios minutos.
Si azd avisa que no observa cambios de estado, no dar por terminado el
despliegue solo por su codigo de salida: comprobar el resultado del build
y que `/health` devuelve 200. Durante el primer despliegue hubo respuestas
503 hasta completar la compilacion y superar el sondeo de arranque.

El script crea un App Service Linux **B1 / Python 3.12** en el mismo grupo
y region, y un registro Microsoft Entra single-tenant dedicado. Se necesita
permiso para crear aplicaciones Entra, ademas de recursos y asignaciones RBAC.
El login se restringe al usuario que ejecuta el script (object ID).
El servidor tambien comprueba el principal inyectado por EasyAuth: no basta
con conocer la URL. `/health` es publico y solo devuelve el estado del proceso.

En Azure se usa Gunicorn (un worker, ocho threads, una sola ejecucion de demo
simultanea) y la identidad administrada de la web, con Foundry User solo en
el proyecto `cena`. `AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential`
restringe `DefaultAzureCredential` a esa unica credencial.
La clave MCP y la credencial Entra se guardan solo en app settings, nunca
en el frontend, outputs o ZIP. El fichero temporal de parametros se elimina
al terminar, tambien si falla el despliegue. La credencial de login dura un
ano; repetir el script antes de caducar la renueva si quedan menos de 30 dias.
No se deshabilita la autenticacion para resolver fallos de acceso.

[package-demo-web.ps1](scripts/package-demo-web.ps1), hook prepackage de azd,
prepara una carpeta ignorada con una lista cerrada de archivos:
UI/backend, requirements y los dos modulos de Orquestador. No empaqueta el
repositorio, `.env`, configuraciones locales ni documentos de la presentacion.
Agenda y A2A siguen pendientes; desplegar la web no las implementa.

**Coste consultado para B1 Linux en Spain Central:** 0,0158 EUR/h, unos
11,53 EUR por 730 horas, antes de impuestos y sin incluir los consumos
existentes de Foundry/Functions/Storage. B1 no escala a cero; detener la
web no deja de facturar el plan. La eliminacion del plan/web para cesar
ese coste requiere una accion explicita y no afecta a las otras demos.

### Infraestructura base y Functions

Ejemplo desde PowerShell, en la raiz del repositorio:

```powershell
az login
az account show --output table
$env:AZD_CONFIG_DIR = Join-Path $PWD '.azure\azd-config'
azd config set auth.useAzCliAuth true
azd env new poliamor-demo --subscription <ID-DE-LA-SUSCRIPCION-ACTIVA> --location spaincentral
azd up --no-prompt
```

El destino acordado es `MCT Luise 2`
(`c8fb8cba-3849-4961-9032-eaaea4b65cdd`). `azd env new` solo se ejecuta al crear
el entorno; para uno existente, usar `azd env select poliamor-demo`.
En cada terminal nueva, volver a establecer `AZD_CONFIG_DIR` antes de usar
azd. Esta configuracion aislada reutiliza la sesion de Azure CLI y no
modifica la configuracion global de azd ni depende de su token anterior.

[check-context.ps1](scripts/check-context.ps1) impide provisionar si azd y
la suscripcion activa de Azure CLI no coinciden. No usa el proyecto
seleccionado en Foundry Toolkit ni modifica recursos ajenos.

El hook postdeploy [configure-mcp.ps1](scripts/configure-mcp.ps1) obtiene la
clave de sistema `mcp_extension` una vez indexado Restaurantes y configura
la URL y la clave MCP en los app settings de Orquestador. No imprime la clave
ni la guarda en outputs azd. Se puede repetir; si la clave aun no existe,
falla expresamente en lugar de usar la clave maestra.

Los outputs de azd contienen nombres y endpoints, no claves:

```powershell
azd env get-value AZURE_RESOURCE_GROUP
azd env get-value SERVICE_RESTAURANTES_URI
azd env get-value SERVICE_ORQUESTADOR_URI
azd env get-value SERVICE_PRESUPUESTO_URI
```

Las identidades son de sistema: tras provisionar, RBAC puede tardar en
propagarse. Si el despliegue falla con un 403, revisar la asignacion y volver
a ejecutar `azd deploy --all --no-prompt`; no habilitar claves de Storage ni
ampliar permisos para ocultar el error.

## Comprobar la fase 1

Resultado verificado en Azure:

| Servicio | Endpoint health | Con clave | Sin clave |
| --- | --- | --- | --- |
| Restaurantes | https://func-restaurantes-wnmjunhobdnpc.azurewebsites.net/api/health | 200 | 401 |
| Orquestador | https://func-orquestador-wnmjunhobdnpc.azurewebsites.net/api/health | 200 | 401 |
| Presupuesto | https://func-presupuesto-wnmjunhobdnpc.azurewebsites.net/api/health | 200 | 401 |

Tambien se verificaron las tres identidades distintas, sus ocho asignaciones
RBAC y el modelo en estado `Succeeded`. Las claves no se guardan en el repo.
El despliegue inicial encontro operaciones concurrentes incompatibles:
la infraestructura serializa ahora los planes y crea el deployment del
modelo despues del proyecto Foundry. El reintento completo fue correcto.

Cada app expone `GET /api/health`, con autenticacion de nivel Function.
Respuesta esperada, cambiando el servicio:

```json
{"status": "ok", "service": "restaurantes", "phase": 1}
```

Ejemplo protegido, sin mostrar ni guardar la clave:

```powershell
$subscription = azd env get-value AZURE_SUBSCRIPTION_ID
$group = azd env get-value AZURE_RESOURCE_GROUP
$name = azd env get-value SERVICE_RESTAURANTES_NAME
$uri = azd env get-value SERVICE_RESTAURANTES_URI
$key = az functionapp keys list --subscription $subscription --resource-group $group --name $name --query functionKeys.default --output tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($key)) {
    throw 'No se pudo obtener la clave del servicio.'
}
try {
    Invoke-RestMethod "$uri/api/health" -Headers @{ 'x-functions-key' = $key }
} finally {
    Remove-Variable key
}
```

No usar `--debug`, imprimir claves ni pegarlas en comandos versionados.
Sin cabecera, la app debe rechazar la peticion con HTTP 401.

### Local y smoke tests

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\src\orquestador\requirements.txt
foreach ($service in 'restaurantes', 'orquestador', 'presupuesto') {
    python -m unittest discover -s ".\src\$service" -p test_smoke.py -v
    if ($LASTEXITCODE -ne 0) { throw "Fallo en $service" }
}
Copy-Item .\src\restaurantes\local.settings.sample.json .\src\restaurantes\local.settings.json
Set-Location .\src\restaurantes
$env:AzureWebJobsSecretStorageType = 'Files'
func start
```

Los smoke tests comprueban health, indexacion y los contratos propios de
cada app. Restaurantes cubre busqueda/reserva y rechazo por disponibilidad;
Orquestador cubre entradas invalidas y respuestas 200/409 con el agente simulado.
El host local suele desactivar la comprobacion de claves: no sustituye la
prueba de autenticacion en Azure. Para MCP local, `Files` permite gestionar
los secretos del host sin una cadena de conexion Storage. Sin almacenamiento
local configurado Core Tools puede informar storage unhealthy aunque las
rutas HTTP respondan; no es una prueba de salud de Storage.

Los settings reales, entornos virtuales y estado azd estan excluidos por
[.gitignore](.gitignore). Los samples no contienen credenciales.

## Demo 1: MCP

Restaurantes expone exactamente `search` y `book` mediante el binding MCP
nativo de Functions y Streamable HTTP:

https://func-restaurantes-wnmjunhobdnpc.azurewebsites.net/runtime/webhooks/mcp

- `search` filtra zona, capacidad y precio del **menu sin bebida**.
- `days` contiene dias en ingles; una lista vacia indica sin disponibilidad.
- `book` valida restaurante, dia y capacidad. Devuelve una reserva simulada,
  no persiste ni realiza cobros.
- Hay cinco restaurantes ficticios en `zona-demo`; no representa un lugar real.
- El agente descarta El Puerto y reserva La Plaza: menu 42 EUR y bebida 6 EUR.
  Esta fase no valida el presupuesto total de 45 EUR: eso pertenece a la demo A2A.

Ejemplo desde PowerShell, con el entorno azd seleccionado:

```powershell
$group = azd env get-value AZURE_RESOURCE_GROUP
$name = azd env get-value SERVICE_ORQUESTADOR_NAME
$uri = azd env get-value SERVICE_ORQUESTADOR_URI
$key = az functionapp keys list --resource-group $group --name $name --query functionKeys.default --output tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($key)) {
    throw 'No se pudo obtener la clave del orquestador.'
}
try {
    $body = @{
        mode = 'mcp'; near = 'zona-demo'; people = 12; max_per_head = 45
        when = '2026-10-23T20:30:00+02:00'
    } | ConvertTo-Json
    Invoke-RestMethod "$uri/api/cena" -Method Post -ContentType application/json `
        -Headers @{ 'x-functions-key' = $key } -Body $body
} finally {
    Remove-Variable key
}
```

Respuesta: `mode`, texto `result` y objeto `booking` con `booking_id`,
`restaurant_id=plaza`, 12 personas, fecha/hora exacta, `menu_per_head=42`,
`drink_per_head=6`, `currency=EUR` y `simulated=true`.
El texto y el UUID varian; los valores de la reserva proceden del resultado
real de MCP, no de texto inventado por el modelo.

HTTP 400 para JSON/parametros invalidos o modos todavia no implementados.
HTTP 409 con `status=unavailable` y `booking=null` si no hay zona o dia
disponible. Esta decision se comprueba primero con una llamada MCP `search`
determinista, sin depender de que el modelo decida usar herramientas. Si hay
candidatos, Cena hace su propia busqueda y reserva con MCP. Los fallos
tecnicos no se convierten en reservas ficticiamente
exitosas: Functions los registra como errores.

### MCP y depuracion en VS Code

[mcp.json](.vscode/mcp.json) configura el servidor remoto y solicita la
clave de sistema `mcp_extension` mediante un campo protegido. No introducir
una clave de funcion: el endpoint la rechaza con 403; sin clave devuelve 401.
La clave maestra no es necesaria.

Para depurar Orquestador, instalar sus requirements en `.venv`, copiar
[local.settings.sample.json](src/orquestador/local.settings.sample.json) a
`local.settings.json` en la misma carpeta y completar los valores:

- `AZURE_AI_PROJECT_ENDPOINT`: output homonimo de `azd env get-value`.
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`: `gpt-4.1-mini`.
- `RESTAURANTES_MCP_URL`: endpoint remoto anterior.
- `RESTAURANTES_MCP_KEY`: clave de sistema obtenida de Azure, solo en el
  fichero local ignorado o en variables de entorno; nunca en un commit.

Autenticarse con Azure CLI: localmente se usa la identidad del desarrollador;
en Azure se usa la identidad administrada de la Function App.
[launch.json](.vscode/launch.json) inicia la
[tarea Functions](.vscode/tasks.json) y conecta debugpy al puerto 9091.
La tarea fija explicitamente el Python de `.venv`, sin depender del Python global.
Solicitar `POST http://localhost:7071/api/cena` con el mismo cuerpo para
alcanzar un breakpoint. No se usa Agent Inspector: el host es Azure Functions.
La tarea referencia la copia aislada de Core Tools descrita anteriormente.

### Verificacion realizada

- Tres smoke tests y `pip check`: correctos.
- Tres health Azure: 200 con clave y 401 sin clave.
- MCP real: protocolo `2025-06-18`, `tools/list` y `tools/call` correctos.
- Cena en Azure con identidad administrada, version final: tres reservas
  correctas, 13,70 s, 12,88 s y 11,57 s; las dos ultimas, tras warmup, por debajo de 30 s.
  Son mediciones de ensayo, no un SLA ni una garantia de cold start.
- JSON invalido y modo A2A: 400. Zona inexistente y sabado sin plazas:
  seis comprobaciones consecutivas con 409 y sin reservar.
- Hook de configuracion repetido dos veces sin errores. Cero agentes
  remanentes en el proyecto tras los ensayos.
- Python propio, incluyendo smoke y excluyendo datos: Restaurantes 119
  lineas, Orquestador 189 y Presupuesto 33; menos de 200 por app.

## Seguridad y siguientes fases

- Foundry y Storage usan identidades; no hay claves de esos servicios.
- Las llamadas HTTP usan claves limitadas. MCP usa `mcp_extension`
  (clave **de sistema**, no maestra); A2A usara clave de funcion.
- A2A publicara `/.well-known/agent-card.json` y el alias de las slides,
  `/.well-known/agent.json`.
- La traza del Agent Framework, los scripts de demos y su guion tecnico
  aun no estan implementados; la demo MCP si esta operativa.
- La negociacion A2A sera efimera: un reciclado puede perder la Task.
  El guion reiniciara explicitamente; no se promete continuidad durable.

## Apagar y eliminar el entorno

Solo despues de confirmar que se quieren borrar los recursos de este entorno:

```powershell
azd env select poliamor-demo
azd env get-value AZURE_RESOURCE_GROUP
azd down --purge
```

Esto elimina el entorno de las demos, no limpia toda la suscripcion.
La purga es destructiva. Mantener el entorno levantado para revision no
demuestra que el borrado este verificado; esa prueba requiere autorizacion
y ejecucion separadas. Revisar Cost Management y el grupo de recursos
despues de eliminar.
