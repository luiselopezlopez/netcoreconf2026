param(
    [string]$EnvironmentName = 'poliamor-demo',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$previousConfig = $env:AZD_CONFIG_DIR
$parameterFile = Join-Path $root ".azure\web-parameters-$([guid]::NewGuid().ToString('N')).json"
$secret = $null
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
    $userId = az ad signed-in-user show --query id --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($userId)) {
        throw 'No se pudo identificar al usuario para restringir el acceso Entra.'
    }
    $resourceToken = $values.SERVICE_RESTAURANTES_NAME -replace '^func-restaurantes-', ''
    if ($resourceToken -notmatch '^[a-z0-9]{13}$') { throw 'Sufijo de recursos no reconocido.' }
    $webName = "web-poliamor-$resourceToken"
    $clientId = '00000000-0000-0000-0000-000000000001'
    $secret = 'validation-placeholder-never-deployed'
    $registrationName = "$EnvironmentName-web"
    if (-not $ValidateOnly) {
        $registrationsJson = az ad app list --display-name $registrationName --output json --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron consultar los registros Entra.' }
        $registrations = @($registrationsJson | ConvertFrom-Json |
            Where-Object displayName -eq $registrationName)
        if ($registrations.Count -gt 1) { throw 'Hay varios registros Entra con ese nombre; no se elige uno arbitrariamente.' }
        if ($registrations.Count -eq 0) {
            $registrationJson = az ad app create --display-name $registrationName `
                --sign-in-audience AzureADMyOrg --enable-id-token-issuance true `
                --web-redirect-uris "https://$webName.azurewebsites.net/.auth/login/aad/callback" `
                --output json --only-show-errors
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el registro Entra.' }
            $registration = $registrationJson | ConvertFrom-Json
        } else {
            $registration = $registrations[0]
        }
        $clientId = $registration.appId
        $principalsJson = az ad sp list --filter "appId eq '$clientId'" --query '[].id' --output json --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar el principal Entra.' }
        if (@($principalsJson | ConvertFrom-Json).Count -eq 0) {
            az ad sp create --id $clientId --output none --only-show-errors
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el principal Entra.' }
        }
        $existingWebJson = az webapp list --resource-group $values.AZURE_RESOURCE_GROUP `
            --query "[?name=='$webName'].name" --output json --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar la web existente.' }
        $secret = $null
        $credentialsJson = az ad app credential list --id $clientId --output json --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar la caducidad de la credencial Entra.' }
        $credentials = @($credentialsJson | ConvertFrom-Json |
            Where-Object { $_.displayName -eq 'demo-web-login' -and [datetime]$_.endDateTime -gt (Get-Date).AddDays(30) })
        if (@($existingWebJson | ConvertFrom-Json).Count -gt 0 -and $credentials.Count -gt 0) {
            $secret = az webapp config appsettings list --resource-group $values.AZURE_RESOURCE_GROUP `
                --name $webName --query "[?name=='WEB_AUTH_CLIENT_SECRET'].value | [0]" `
                --output tsv --only-show-errors
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo recuperar la credencial de login existente.' }
        }
        if ([string]::IsNullOrWhiteSpace($secret)) {
            $credentialJson = az ad app credential reset --id $clientId --append `
                --display-name demo-web-login --years 1 --output json --only-show-errors
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo emitir la credencial de login Entra.' }
            $credential = $credentialJson | ConvertFrom-Json
            $secret = $credential.password
            if ([string]::IsNullOrWhiteSpace($secret)) { throw 'Entra no devolvio una credencial valida.' }
        }
    }
    $parameters = @{
        location = @{ value = $values.AZURE_LOCATION }
        environmentName = @{ value = $EnvironmentName }
        resourceToken = @{ value = $resourceToken }
        entraClientId = @{ value = $clientId }
        allowedUserId = @{ value = $userId }
        entraClientSecret = @{ value = $secret }
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
        Write-Host 'Validacion ARM correcta. No se han creado recursos ni credenciales.'
    } else {
        $deploymentJson = az deployment group create --subscription $account.id `
            --resource-group $values.AZURE_RESOURCE_GROUP --name poliamor-web `
            --template-file (Join-Path $root 'infra\web.bicep') --parameters "@$parameterFile" `
            --query properties.outputs --output json --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'Ha fallado el aprovisionamiento de la web.' }
        $outputs = $deploymentJson | ConvertFrom-Json
        $webUri = $outputs.SERVICE_WEB_URI.value
        az ad app update --id $clientId --web-redirect-uris "$webUri/.auth/login/aad/callback" `
            --output none --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo ajustar el callback de login al hostname real.' }
        foreach ($name in @('SERVICE_WEB_NAME', 'SERVICE_WEB_URI')) {
            azd env set $name $outputs.$name.value --environment $EnvironmentName
            if ($LASTEXITCODE -ne 0) { throw "No se pudo guardar $name en azd." }
        }
        Write-Host "Infraestructura web lista: $webUri. Acceso Entra restringido al usuario de Azure CLI."
    }
} finally {
    if (Test-Path -LiteralPath $parameterFile) { Remove-Item -LiteralPath $parameterFile -Force }
    $env:AZD_CONFIG_DIR = $previousConfig
    Remove-Variable secret, parameters, credential, credentialJson -ErrorAction SilentlyContinue
    Pop-Location
}
