param(
    [string]$EnvironmentName = 'poliamor-demo',
    [ValidateRange(1024, 65535)][int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$names = @('AZD_CONFIG_DIR', 'AZURE_SUBSCRIPTION_ID', 'AZURE_TENANT_ID', 'AZURE_LOCATION',
    'AZURE_AI_PROJECT_ENDPOINT', 'AZURE_AI_MODEL_DEPLOYMENT_NAME', 'RESTAURANTES_MCP_URL',
    'RESTAURANTES_MCP_KEY', 'PRESUPUESTO_A2A_URL', 'PRESUPUESTO_A2A_KEY', 'AZURE_TOKEN_CREDENTIALS')
$previous = @{}
foreach ($name in $names) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw 'Falta .venv. Sigue los prerrequisitos del README e instala requirements de Orquestador.'
    }
    $env:AZD_CONFIG_DIR = Join-Path $root '.azure\azd-config'
    Push-Location $root
    try {
        $output = azd env get-values --environment $EnvironmentName --output json
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo cargar el entorno azd.' }
        $values = $output | ConvertFrom-Json
    } finally {
        Pop-Location
    }
    foreach ($name in @('AZURE_SUBSCRIPTION_ID', 'AZURE_TENANT_ID', 'AZURE_LOCATION',
        'AZURE_AI_PROJECT_ENDPOINT', 'AZURE_AI_MODEL_DEPLOYMENT_NAME')) {
        if ([string]::IsNullOrWhiteSpace($values.$name)) { throw "Falta el output $name." }
        [Environment]::SetEnvironmentVariable($name, $values.$name, 'Process')
    }
    & (Join-Path $PSScriptRoot 'check-context.ps1')
    $uri = [uri]$values.SERVICE_RESTAURANTES_URI
    if ($uri.Scheme -ne 'https' -or -not $uri.Host.EndsWith('.azurewebsites.net')) {
        throw 'El endpoint MCP no es una Function App HTTPS de Azure.'
    }
    $key = az functionapp keys list --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $values.AZURE_RESOURCE_GROUP --name $values.SERVICE_RESTAURANTES_NAME `
        --query systemKeys.mcp_extension --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($key)) {
        throw 'No se pudo obtener la clave MCP de Restaurantes.'
    }
    $env:RESTAURANTES_MCP_URL = $uri.AbsoluteUri.TrimEnd('/') + '/runtime/webhooks/mcp'
    $env:RESTAURANTES_MCP_KEY = $key
    $budgetUri = [uri]$values.SERVICE_PRESUPUESTO_URI
    if ($budgetUri.Scheme -ne 'https' -or -not $budgetUri.Host.EndsWith('.azurewebsites.net')) {
        throw 'El endpoint A2A no es una Function App HTTPS de Azure.'
    }
    $budgetKey = az functionapp keys list --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $values.AZURE_RESOURCE_GROUP --name $values.SERVICE_PRESUPUESTO_NAME `
        --query functionKeys.default --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($budgetKey)) {
        throw 'No se pudo obtener la clave Function de Presupuesto.'
    }
    $env:PRESUPUESTO_A2A_URL = $budgetUri.AbsoluteUri.TrimEnd('/') + '/a2a'
    $env:PRESUPUESTO_A2A_KEY = $budgetKey
    $env:AZURE_TOKEN_CREDENTIALS = 'AzureCliCredential'
    Write-Host 'Web local con Foundry, MCP y A2A reales. No se despliegan recursos nuevos.'
    & $python (Join-Path $root 'demo_web\server.py') $Port
    if ($LASTEXITCODE -ne 0) { throw 'El servidor web ha terminado con error.' }
} finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    Remove-Variable key, budgetKey, output, values -ErrorAction SilentlyContinue
}
