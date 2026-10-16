$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$target = Join-Path $root '.azure\web-package'
New-Item -ItemType Directory -Force -Path (Join-Path $target 'demo_web\static'),
    (Join-Path $target 'src\orquestador') | Out-Null
foreach ($name in @('server.py', 'wsgi.py', 'requirements.txt')) {
    Copy-Item (Join-Path $root "demo_web\$name") (Join-Path $target "demo_web\$name") -Force
}
foreach ($name in @('index.html', 'app.js', 'style.css')) {
    Copy-Item (Join-Path $root "demo_web\static\$name") (Join-Path $target "demo_web\static\$name") -Force
}
foreach ($name in @('agents.py', 'function_app.py', 'requirements.txt')) {
    Copy-Item (Join-Path $root "src\orquestador\$name") (Join-Path $target "src\orquestador\$name") -Force
}
Copy-Item (Join-Path $root 'demo_web\package-requirements.txt') (Join-Path $target 'requirements.txt') -Force
Write-Host 'Paquete web preparado por allowlist; sin .env, claves ni local.settings.json.'
