# Poliamor en los tiempos de la IA

Demos para NetCoreConf: MCP, agents as tools y Agent2Agent, con Microsoft
Agent Framework y Azure Functions.

## Estado: fase 1

Por ahora hay **tres servicios de infraestructura con un endpoint health**.
Fase 1 desplegada y verificada el **2026-10-16** en `MCT Luise 2`,
grupo `rg-poliamor-demo`, region `spaincentral`.
Todavia no hay agentes, herramientas MCP, negociacion A2A ni reservas.
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
Cada app tiene su propio requirements. Las versiones de Agent Framework,
A2A y exportacion OpenTelemetry se resolveran y fijaran antes de introducir
esos componentes; no se instalan en los servicios health.

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

## Desplegar

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
python -m pip install -r .\src\restaurantes\requirements.txt
foreach ($service in 'restaurantes', 'orquestador', 'presupuesto') {
    python -m unittest discover -s ".\src\$service" -p test_smoke.py -v
    if ($LASTEXITCODE -ne 0) { throw "Fallo en $service" }
}
Copy-Item .\src\restaurantes\local.settings.sample.json .\src\restaurantes\local.settings.json
Set-Location .\src\restaurantes
func start
```

En fase 1 los tres requirements son iguales. Los smoke tests comprueban
que cada app indexa su funcion y devuelve el contrato health esperado.
El host local suele desactivar la comprobacion de claves: no sustituye la
prueba 401 en Azure. El endpoint health HTTP de esta fase no necesita
emulador Storage; las demos con bindings se configuraran posteriormente.

Los settings reales, entornos virtuales y estado azd estan excluidos por
[.gitignore](.gitignore). Los samples no contienen credenciales.

## Seguridad y siguientes fases

- Foundry y Storage usan identidades; no hay claves de esos servicios.
- Las llamadas HTTP usan claves limitadas. MCP usara `mcp_extension`
  (clave **de sistema**, no maestra); A2A usara clave de funcion.
- A2A publicara `/.well-known/agent-card.json` y el alias de las slides,
  `/.well-known/agent.json`.
- La traza del Agent Framework, los scripts de demos y su guion tecnico
  aun no estan implementados. No confundir el health con una demo funcional.
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
