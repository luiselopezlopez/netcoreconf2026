$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($env:AZURE_SUBSCRIPTION_ID)) {
    throw 'Falta AZURE_SUBSCRIPTION_ID en el entorno azd.'
}

$accountJson = az account show --output json
if ($LASTEXITCODE -ne 0) {
    throw 'No se pudo consultar la sesion de Azure CLI. Ejecuta az login.'
}
$account = $accountJson | ConvertFrom-Json
if ($account.id -ne $env:AZURE_SUBSCRIPTION_ID) {
    throw 'La suscripcion activa de Azure CLI no coincide con azd. Revisa ambas antes de desplegar.'
}
if ($account.state -ne 'Enabled') {
    throw 'La suscripcion activa no esta habilitada.'
}
if ($env:AZURE_TENANT_ID -and $account.tenantId -ne $env:AZURE_TENANT_ID) {
    throw 'El tenant de Azure CLI no coincide con el tenant guardado en azd.'
}

Write-Host "Destino verificado: $($account.name) / $($account.id) / $env:AZURE_LOCATION"
