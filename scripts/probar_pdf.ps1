<#
.SYNOPSIS
  Corre las pruebas de PDF (WeasyPrint) en un contenedor Linux.

.DESCRIPTION
  WeasyPrint necesita Pango/GTK, que no están en Windows. Esta imagen trae las mismas librerías y
  fuentes (Liberation Sans) que la imagen de producción de `constancias` y monta el repositorio.
  Solo corre las pruebas marcadas `pdf`, que no necesitan base de datos.

.EXAMPLE
  .\scripts\probar_pdf.ps1              # usa la imagen si ya existe
  .\scripts\probar_pdf.ps1 -Reconstruir # la vuelve a construir (cambio de dependencias)
#>
param([switch]$Reconstruir, [string[]]$Pytest = @())

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$imagen = 'cc-pruebas-pdf'

if ($Reconstruir -or -not (docker image ls -q $imagen)) {
    Write-Host "Construyendo la imagen $imagen..."
    docker build -f "$raiz/infra/docker/pruebas-pdf/Dockerfile" -t $imagen "$raiz/infra/docker/pruebas-pdf"
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir la imagen.' }
}

docker run --rm -v "${raiz}:/app" -w /app $imagen `
    python -m pytest -q -p no:cacheprovider -m pdf services/constancias/tests/test_pdf.py @Pytest
exit $LASTEXITCODE
