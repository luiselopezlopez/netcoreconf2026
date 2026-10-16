$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'check-context.ps1')
if (-not $env:AZURE_RESOURCE_GROUP -or -not $env:SERVICE_RESTAURANTES_NAME -or
    -not $env:SERVICE_ORQUESTADOR_NAME -or -not $env:SERVICE_RESTAURANTES_URI -or
    -not $env:SERVICE_PRESUPUESTO_NAME -or -not $env:SERVICE_PRESUPUESTO_URI) {
    throw 'Faltan outputs del entorno azd para configurar MCP y A2A.'
}
$key = $null
$budgetKey = $null
try {
    $key = az functionapp keys list --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $env:AZURE_RESOURCE_GROUP --name $env:SERVICE_RESTAURANTES_NAME `
        --query systemKeys.mcp_extension --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($key)) {
        throw 'No existe la clave de sistema mcp_extension. Comprueba el despliegue y la indexacion de Restaurantes.'
    }
    az functionapp config appsettings set --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $env:AZURE_RESOURCE_GROUP --name $env:SERVICE_ORQUESTADOR_NAME `
        --settings "RESTAURANTES_MCP_KEY=$key" `
        "RESTAURANTES_MCP_URL=$($env:SERVICE_RESTAURANTES_URI.TrimEnd('/'))/runtime/webhooks/mcp" `
        --output none --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo configurar la conexion MCP del orquestador.'
    }
    $budgetKey = az functionapp keys list --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $env:AZURE_RESOURCE_GROUP --name $env:SERVICE_PRESUPUESTO_NAME `
        --query functionKeys.default --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($budgetKey)) {
        throw 'No se pudo obtener la clave Function de Presupuesto.'
    }
    az functionapp config appsettings set --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $env:AZURE_RESOURCE_GROUP --name $env:SERVICE_ORQUESTADOR_NAME `
        --settings "PRESUPUESTO_A2A_KEY=$budgetKey" `
        "PRESUPUESTO_A2A_URL=$($env:SERVICE_PRESUPUESTO_URI.TrimEnd('/'))/a2a" `
        --output none --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo configurar A2A en Orquestador.' }
    if ($env:SERVICE_WEB_NAME) {
        az webapp config appsettings set --subscription $env:AZURE_SUBSCRIPTION_ID `
            --resource-group $env:AZURE_RESOURCE_GROUP --name $env:SERVICE_WEB_NAME `
            --settings "PRESUPUESTO_A2A_KEY=$budgetKey" `
            "PRESUPUESTO_A2A_URL=$($env:SERVICE_PRESUPUESTO_URI.TrimEnd('/'))/a2a" `
            --output none --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo configurar A2A en la web.' }
    }
    Write-Host 'Conexiones MCP y A2A configuradas sin mostrar claves.'
} finally {
    Remove-Variable key, budgetKey
}
