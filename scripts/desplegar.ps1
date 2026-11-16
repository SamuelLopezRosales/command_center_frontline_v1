<#
.SYNOPSIS
  Despliegue replicable de un ambiente de Command Center (T-227, docs/despliegue.md).

.DESCRIPTION
  Un solo comando por ambiente. En orden: guardia de cuenta (PA-1 a PA-3), verificación previa
  (solo lecturas), empaquetado de las Lambdas y build del frontend, cdk diff, costo estimado,
  PAUSA PARA APROBACIÓN (frase exacta tecleada en la consola), cdk deploy del grupo Base,
  imágenes migrar/ops en ECR, migraciones, contraseñas de los roles, cdk deploy de los Servicios y
  los datos para el primer usuario.

  El perfil y la cuenta salen de infra/config/ambientes.json. Antes de ejecutarlo defina el perfil:
      $env:AWS_PROFILE = 'cc-test'
  El script rechaza llaves de acceso en el entorno, nunca imprime credenciales, nunca borra ni
  destruye nada (eso lo hace la persona, regla 8) y no tiene un modo "sí a todo": sin consola
  interactiva y sin la frase exacta, no despliega.

.PARAMETER Ambiente
  Nombre del ambiente definido en infra/config/ambientes.json (por ejemplo: test).

.PARAMETER SoloRevisar
  Guardia, verificación previa, empaquetado, cdk diff y costo. No despliega ni crea nada.
  AVISO: cdk diff publica las plantillas en el bucket de assets del CDKToolkit (compartido).

.PARAMETER SoloSynth
  Solo cdk synth sin credenciales de AWS (no llama a AWS).

.PARAMETER Dias
  Días de la ventana de uso para el costo estimado (por defecto 14).

.PARAMETER HorasServiciosPorDia
  Horas al día con los servicios de ECS encendidos (24 por defecto) para el costo estimado.

.PARAMETER Contexto
  Contextos de CDK 'clave=valor' (por ejemplo certificado_alb_arn=arn:...). Solo los permitidos.

.PARAMETER Simular
  Imprime lo que haría y el costo estimado, sin ejecutar ningún comando externo (equivale a -WhatIf).

.EXAMPLE
  .\scripts\desplegar.ps1 -Ambiente test -SoloRevisar
  .\scripts\desplegar.ps1 -Ambiente test -SoloRevisar -Dias 7
  .\scripts\desplegar.ps1 -Ambiente test
  .\scripts\desplegar.ps1 -Ambiente prod -Contexto certificado_alb_arn=arn:aws:acm:..., dominio_interno=cc.interno
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{1,19}$')]
    [string]$Ambiente,
    [switch]$SoloRevisar,
    [switch]$SoloSynth,
    [ValidateRange(1, 90)]
    [int]$Dias = 0,
    [ValidateRange(0, 24)]
    [double]$HorasServiciosPorDia = 24,
    [string[]]$Contexto = @(),
    [switch]$Simular
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

if ($SoloRevisar -and $SoloSynth) {
    Write-Host '-SoloRevisar y -SoloSynth son excluyentes.' -ForegroundColor Red
    exit 2
}

$argumentos = @('--ambiente', $Ambiente)
if ($SoloRevisar) { $argumentos += '--solo-revisar' }
if ($SoloSynth) { $argumentos += '--solo-synth' }
if ($Simular -or $WhatIfPreference) { $argumentos += '--simular' }
if ($Dias -gt 0) { $argumentos += @('--dias', "$Dias") }
$argumentos += @('--horas-servicios-por-dia', ([string]$HorasServiciosPorDia).Replace(',', '.'))
foreach ($c in $Contexto) { $argumentos += @('--contexto', $c) }

& uv run --project $raiz --python 3.12 python (Join-Path $PSScriptRoot 'desplegar.py') @argumentos
exit $LASTEXITCODE
