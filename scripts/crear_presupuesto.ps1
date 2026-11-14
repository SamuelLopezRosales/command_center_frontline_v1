# Presupuesto con alertas (T-008 y T-009). Idempotente: consulta antes de crear.
# Uso: .\scripts\crear_presupuesto.ps1 -WhatIf   (no llama a AWS)
#      .\scripts\crear_presupuesto.ps1           (requiere aprobación: crea el presupuesto)
[CmdletBinding(SupportsShouldProcess = $true)]
param([string]$Ambiente = 'test')

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'crear_presupuesto.py'

if ($WhatIfPreference) {
    & uv run --project $raiz --python 3.12 python $script --ambiente $Ambiente --que-pasaria
    exit $LASTEXITCODE
}
& uv run --project $raiz --python 3.12 python $script --ambiente $Ambiente
exit $LASTEXITCODE
