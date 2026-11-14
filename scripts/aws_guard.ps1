# Protocolo PA (tasks.md, sección 0.3), pasos PA-1 a PA-3.
# Uso: .\scripts\aws_guard.ps1 [-Ambiente test]
# Sale con código 0 solo si AWS_PROFILE es el del ambiente, la sesión es válida y la cuenta
# es la permitida. No usa ni muestra llaves de acceso.
param([string]$Ambiente = 'test')

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot

if (-not $env:AWS_PROFILE) {
    Write-Host 'PA-1: AWS_PROFILE no está definido. Ejecute: $env:AWS_PROFILE = "cc-test"' -ForegroundColor Red
    exit 1
}

$json = & uv run --project $raiz --python 3.12 python (Join-Path $PSScriptRoot 'aws_guard.py') $Ambiente
$codigo = $LASTEXITCODE
try {
    $r = $json | ConvertFrom-Json
} catch {
    Write-Host 'No se pudo interpretar el resultado de la guardia.' -ForegroundColor Red
    exit 1
}

if ($codigo -eq 0 -and $r.ok) {
    Write-Host "PA-1 a PA-3 correctos. Cuenta: $($r.cuenta). Identidad: $($r.arn)" -ForegroundColor Green
    exit 0
}
Write-Host "Protocolo PA detenido ($($r.codigo)): $($r.mensaje)" -ForegroundColor Red
exit 1
