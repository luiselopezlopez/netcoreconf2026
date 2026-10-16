param([string]$EnvironmentName = 'poliamor-demo')

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$previousConfig = $env:AZD_CONFIG_DIR
$key = $null
Push-Location $root
try {
    $env:AZD_CONFIG_DIR = Join-Path $root '.azure\azd-config'
    $output = azd env get-values --environment $EnvironmentName --output json
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el entorno azd.' }
    $values = $output | ConvertFrom-Json
    $active = az account show --query id --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or $active -ne $values.AZURE_SUBSCRIPTION_ID) {
        throw 'La suscripcion activa no coincide con el entorno de demo.'
    }
    $key = az functionapp keys list --subscription $active --resource-group $values.AZURE_RESOURCE_GROUP `
        --name $values.SERVICE_ORQUESTADOR_NAME --query functionKeys.default --output tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($key)) {
        throw 'No se pudo obtener la clave Function de Orquestador.'
    }
    $body = @{ mode = 'a2a'; near = 'zona-demo'; people = 12; max_per_head = 45
        when = '2026-10-23T20:30:00+02:00'; includes_drinks = $true } | ConvertTo-Json -Compress
    $result = Invoke-RestMethod "$($values.SERVICE_ORQUESTADOR_URI.TrimEnd('/'))/api/cena" `
        -Method Post -ContentType 'application/json' -Headers @{ 'x-functions-key' = $key } `
        -Body $body -TimeoutSec 210
    if ($result.booking.restaurant_id -ne 'patio' -or $result.budget.Count -ne 2 -or
        $result.budget[0].approved -ne $false -or $result.budget[1].approved -ne $true) {
        throw 'El resultado no cumple el guion: rechazo de La Plaza y aprobacion de El Patio.'
    }
    $result | ConvertTo-Json -Depth 20
} finally {
    $env:AZD_CONFIG_DIR = $previousConfig
    Remove-Variable key, body, output, values -ErrorAction SilentlyContinue
    Pop-Location
}
