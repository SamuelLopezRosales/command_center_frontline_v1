# Pipeline mínimo de integración (T-016). No despliega ni llama a AWS:
#   1) lint (ruff)  2) pruebas  3) cdk synth con cdk-nag  4) construcción local de imágenes
# Todo el script corre sin acceso a credenciales de AWS (ni el perfil por defecto del equipo).
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$vacio = Join-Path $raiz '.tmp_aws_vacio'
Set-Content -Path $vacio -Value '' -Encoding ascii
foreach ($v in @(Get-ChildItem Env:AWS_* -ErrorAction SilentlyContinue)) { Remove-Item "Env:$($v.Name)" -ErrorAction SilentlyContinue }
$env:AWS_CONFIG_FILE = $vacio
$env:AWS_SHARED_CREDENTIALS_FILE = $vacio
$env:AWS_EC2_METADATA_DISABLED = 'true'
$env:CDK_DEFAULT_ACCOUNT = '034362033822'
$env:CDK_DEFAULT_REGION = 'us-east-1'
$env:PYTHONIOENCODING = 'utf-8'

function Paso([string]$nombre, [scriptblock]$accion) {
    Write-Host "== $nombre" -ForegroundColor Cyan
    & $accion
    if ($LASTEXITCODE -ne 0) { Write-Host "FALLÓ: $nombre" -ForegroundColor Red; exit 1 }
}

Paso 'lint' { uv run --python 3.12 ruff check .; if ($LASTEXITCODE -eq 0) { uv run --python 3.12 ruff format --check . } }
Paso 'pruebas' { uv run --python 3.12 pytest -q -p no:cacheprovider }
Paso 'cdk synth (cdk-nag)' {
    Push-Location (Join-Path $raiz 'infra')
    try { cdk synth -c ambiente=test --no-notices --quiet --output cdk.out.ci } finally { Pop-Location }
}
Paso 'imágenes (local, sin subir)' {
    $global:LASTEXITCODE = 0
    $dockerfiles = Get-ChildItem -Path (Join-Path $raiz 'services'), (Join-Path $raiz 'lambdas') -Recurse -Filter Dockerfile -ErrorAction SilentlyContinue
    if (-not $dockerfiles) { Write-Host 'Sin Dockerfile todavía; se omite.'; return }
    foreach ($d in $dockerfiles) {
        $etiqueta = 'cc-local/' + ($d.Directory.Name.ToLower())
        docker build -t $etiqueta -f $d.FullName $raiz
        if ($LASTEXITCODE -ne 0) { return }
    }
}
Remove-Item -Recurse -Force (Join-Path $raiz 'infra/cdk.out.ci') -ErrorAction SilentlyContinue
Write-Host 'CI correcto (sin despliegue).' -ForegroundColor Green
exit 0
