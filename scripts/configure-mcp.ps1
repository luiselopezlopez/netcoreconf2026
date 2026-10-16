$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'check-context.ps1')
if (-not $env:AZURE_RESOURCE_GROUP -or -not $env:SERVICE_RESTAURANTES_NAME -or
    -not $env:SERVICE_ORQUESTADOR_NAME -or -not $env:SERVICE_RESTAURANTES_URI) {
    throw 'Faltan outputs del entorno azd para configurar MCP.'
}
$key = $null
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
    Write-Host 'Conexion MCP configurada sin mostrar la clave.'
} finally {
    Remove-Variable key
}
