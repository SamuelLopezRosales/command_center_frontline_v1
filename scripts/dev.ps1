# Equivalente en PowerShell del Makefile (make no estÃ¡ instalado en este equipo).
# Uso: .\scripts\dev.ps1 setup|hooks|lint|format|test|ci|test-env|test-env-down
param([Parameter(Mandatory = $true)][ValidateSet('setup', 'hooks', 'lint', 'format', 'test', 'ci', 'test-env', 'test-env-down')][string]$Tarea)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Uv {
    param([string[]]$Argumentos)
    & uv @Argumentos
    if ($LASTEXITCODE -ne 0) { throw "FallÃ³: uv $($Argumentos -join ' ')" }
}

switch ($Tarea) {
    'setup'  { Invoke-Uv @('sync', '--python', '3.12') }
    'hooks'  { Invoke-Uv @('run', '--python', '3.12', 'pre-commit', 'install') }
    'lint'   {
        Invoke-Uv @('run', '--python', '3.12', 'ruff', 'check', '.')
        Invoke-Uv @('run', '--python', '3.12', 'ruff', 'format', '--check', '.')
    }
    'format' {
        Invoke-Uv @('run', '--python', '3.12', 'ruff', 'format', '.')
        Invoke-Uv @('run', '--python', '3.12', 'ruff', 'check', '--fix', '.')
    }
    'test'   { Invoke-Uv @('run', '--python', '3.12', 'pytest') }
    'test-env' {
        docker compose up -d --wait
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo levantar el entorno local (¿Docker Desktop está iniciado?)' }
    }
    'test-env-down' { docker compose down }
    'ci'     { & (Join-Path $PSScriptRoot 'ci.ps1'); exit $LASTEXITCODE }
}
