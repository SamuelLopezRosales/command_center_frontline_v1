<#
.SYNOPSIS
  Stack local completo para probar el sistema en el navegador, sin AWS (docs/local.md).

.EXAMPLE
  .\scripts\local.ps1 up                 # levanta todo (idempotente)
  .\scripts\local.ps1 estado             # qué corre
  .\scripts\local.ps1 logs dashboard     # registro de un proceso (worker-pdf: contenedor)
  .\scripts\local.ps1 down               # detiene todo y conserva los datos
  .\scripts\local.ps1 down --borrar      # detiene y borra los datos
  .\scripts\local.ps1 reiniciar-datos    # borra base y LocalStack y vuelve a sembrar
  .\scripts\local.ps1 up --sin-pdf       # sin el worker de PDF (no usa Docker para eso)
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('up', 'down', 'estado', 'logs', 'reiniciar-datos')]
    [string]$Comando,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Resto = @()
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& uv run --python 3.12 python -m scripts.local.stack $Comando @Resto
exit $LASTEXITCODE
