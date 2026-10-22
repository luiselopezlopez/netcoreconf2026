param(
    [string]$EnvironmentName = 'poliamor-demo',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$previousConfig = $env:AZD_CONFIG_DIR
$parameterFile = Join-Path $root ".azure\web-parameters-$([guid]::NewGuid().ToString('N')).json"
Push-Location $root
try {
    $env:AZD_CONFIG_DIR = Join-Path $root '.azure\azd-config'
    $valuesJson = azd env get-values --environment $EnvironmentName --output json
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el entorno azd.' }
    $values = $valuesJson | ConvertFrom-Json
    $accountJson = az account show --output json --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw 'No hay sesion de Azure CLI.' }
    $account = $accountJson | ConvertFrom-Json
    if ($account.id -ne $values.AZURE_SUBSCRIPTION_ID -or $account.tenantId -ne $values.AZURE_TENANT_ID) {
        throw 'La suscripcion/tenant de Azure CLI no coincide con azd.'
    }
    $resourceToken = $values.SERVICE_RESTAURANTES_NAME -replace '^func-restaurantes-', ''
    if ($resourceToken -notmatch '^[a-z0-9]{13}$') { throw 'Sufijo de recursos no reconocido.' }
    $parameters = @{
        location = @{ value = $values.AZURE_LOCATION }
        environmentName = @{ value = $EnvironmentName }
        resourceToken = @{ value = $resourceToken }
        foundryAccountName = @{ value = $values.AZURE_AI_ACCOUNT_NAME }
        foundryProjectName = @{ value = $values.AZURE_AI_PROJECT_NAME }
        modelDeploymentName = @{ value = $values.AZURE_AI_MODEL_DEPLOYMENT_NAME }
        restaurantsAppName = @{ value = $values.SERVICE_RESTAURANTES_NAME }
    }
    @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'; parameters = $parameters
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    if ($ValidateOnly) {
        az deployment group validate --subscription $account.id `
            --resource-group $values.AZURE_RESOURCE_GROUP --name poliamor-web `
            --template-file (Join-Path $root 'infra\web.bicep') --parameters "@$parameterFile" `
            --output none --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'La validacion ARM de la web ha fallado.' }
        Write-Host 'Validacion ARM correcta. No se han creado recursos.'
    } else {
        $deploymentJson = az deployment group create --subscription $account.id `
            --resource-group $values.AZURE_RESOURCE_GROUP --name poliamor-web `
            --template-file (Join-Path $root 'infra\web.bicep') --parameters "@$parameterFile" `
            --query properties.outputs --output json --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'Ha fallado el aprovisionamiento de la web.' }
        $outputs = $deploymentJson | ConvertFrom-Json
        foreach ($name in @('SERVICE_WEB_NAME', 'SERVICE_WEB_URI')) {
            azd env set $name $outputs.$name.value --environment $EnvironmentName
            if ($LASTEXITCODE -ne 0) { throw "No se pudo guardar $name en azd." }
        }
        Write-Host "Infraestructura web anonima lista: $($outputs.SERVICE_WEB_URI.value)."
    }
} finally {
    if (Test-Path -LiteralPath $parameterFile) { Remove-Item -LiteralPath $parameterFile -Force }
    $env:AZD_CONFIG_DIR = $previousConfig
    Remove-Variable parameters, outputs -ErrorAction SilentlyContinue
    Pop-Location
}
