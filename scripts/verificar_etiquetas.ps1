# Verifica (solo lectura) que los recursos del proyecto lleven las tres etiquetas (T-019).
# Uso: $env:AWS_PROFILE='cc-test'; .\scripts\verificar_etiquetas.ps1 [-Esperados 14]
param([string]$Ambiente = 'test', [int]$Esperados = 0)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$cfg = Get-Content (Join-Path $raiz 'infra\config\ambientes.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$amb = $cfg.ambientes.$Ambiente
$perfil = $amb.perfil
$region = $amb.region
$esperadas = @{}
$amb.etiquetas.PSObject.Properties | ForEach-Object { $esperadas[$_.Name] = $_.Value }

& powershell -NoProfile -File (Join-Path $PSScriptRoot 'aws_guard.ps1') -Ambiente $Ambiente
if ($LASTEXITCODE -ne 0) { exit 1 }

$json = aws resourcegroupstaggingapi get-resources `
    --tag-filters "Key=proyecto,Values=$($esperadas['proyecto'])" "Key=ambiente,Values=$Ambiente" `
    --profile $perfil --region $region --output json
if ($LASTEXITCODE -ne 0) { Write-Host 'No se pudo consultar la API de etiquetas.' -ForegroundColor Red; exit 1 }
$recursos = ($json | ConvertFrom-Json).ResourceTagMappingList

$fallos = 0
foreach ($r in $recursos) {
    $tags = @{}
    $r.Tags | ForEach-Object { $tags[$_.Key] = $_.Value }
    $faltan = @($esperadas.Keys | Where-Object { $tags[$_] -ne $esperadas[$_] })
    if ($faltan) { $fallos++; Write-Host "FALTA $($faltan -join ',') -> $($r.ResourceARN)" -ForegroundColor Red }
    else { Write-Host "OK  $($r.ResourceARN)" }
}
Write-Host "Recursos etiquetados: $($recursos.Count). Con etiquetas incorrectas: $fallos."
if ($Esperados -gt 0 -and $recursos.Count -lt $Esperados) {
    Write-Host "Se esperaban al menos $Esperados recursos etiquetados." -ForegroundColor Red
    exit 1
}
if ($fallos -gt 0) { exit 1 }
exit 0
