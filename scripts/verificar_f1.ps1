# Verifica (solo lectura) los recursos de la Fase 1 en AWS (T-048, design.md §13.4 y §13.5).
# Uso: $env:AWS_PROFILE='cc-test'; .\scripts\verificar_f1.ps1
# Comprueba: RDS cifrado y sin acceso público; Object Lock activo en "constancias"; cada cola con
# su DLQ y cifrado KMS; el grupo de Cognito con MFA obligatorio; y las tres etiquetas en los
# stacks y en los recursos. No crea, cambia ni borra nada. Sale con 0 solo si todo está bien.
param([string]$Ambiente = 'test')

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

$script:fallos = 0
function Revisar([string]$nombre, [bool]$ok, [string]$detalle = '') {
    if ($ok) { Write-Host "OK     $nombre $detalle" -ForegroundColor Green }
    else { $script:fallos++; Write-Host "FALLA  $nombre $detalle" -ForegroundColor Red }
}
function Consultar([string[]]$argumentos) {
    $salida = & aws @argumentos --profile $perfil --region $region --output json
    if ($LASTEXITCODE -ne 0) { throw "Falló: aws $($argumentos -join ' ')" }
    return ($salida | Out-String | ConvertFrom-Json)
}
function Salida([string]$stack, [string]$clave) {
    $s = Consultar @('cloudformation', 'describe-stacks', '--stack-name', $stack)
    return ($s.Stacks[0].Outputs | Where-Object OutputKey -eq $clave).OutputValue
}
function EtiquetasOk($lista) {
    $t = @{}
    $lista | ForEach-Object { $t[$_.Key] = $_.Value }
    return @($esperadas.Keys | Where-Object { $t[$_] -ne $esperadas[$_] })
}

Write-Host '== Stacks'
$stacks = 'Security', 'Network', 'Storage', 'Data', 'Messaging', 'Auth', 'ComputeBase' |
    ForEach-Object { "Cc$_-$Ambiente" }
foreach ($n in $stacks) {
    $s = (Consultar @('cloudformation', 'describe-stacks', '--stack-name', $n)).Stacks[0]
    $faltan = EtiquetasOk $s.Tags
    Revisar $n (($s.StackStatus -match '_COMPLETE$' -and $s.StackStatus -notmatch 'ROLLBACK') -and -not $faltan) "($($s.StackStatus)$(if ($faltan) { "; faltan etiquetas: $($faltan -join ',')" }))"
}

Write-Host '== RDS'
$host_bd = Salida "CcData-$Ambiente" 'RdsEndpoint'
$bd = (Consultar @('rds', 'describe-db-instances')).DBInstances | Where-Object { $_.Endpoint.Address -eq $host_bd }
Revisar 'Instancia encontrada' ($null -ne $bd) $host_bd
if ($bd) {
    Revisar 'Almacenamiento cifrado' ($bd.StorageEncrypted -eq $true) "(llave: $($bd.KmsKeyId.Split('/')[-1]))"
    Revisar 'Sin acceso público' ($bd.PubliclyAccessible -eq $false)
    Revisar 'Disponible' ($bd.DBInstanceStatus -eq 'available') "($($bd.DBInstanceStatus))"
    $faltan = EtiquetasOk $bd.TagList
    Revisar 'Etiquetas de RDS' (-not $faltan) $(if ($faltan) { "faltan: $($faltan -join ',')" })
}

Write-Host '== S3 constancias'
$bucket = Salida "CcStorage-$Ambiente" 'ConstanciasBucket'
$lock = Consultar @('s3api', 'get-object-lock-configuration', '--bucket', $bucket)
$regla = $lock.ObjectLockConfiguration.Rule.DefaultRetention
Revisar 'Object Lock activo' ($lock.ObjectLockConfiguration.ObjectLockEnabled -eq 'Enabled') "($bucket; $($regla.Mode) $($regla.Days) día)"
$publico = Consultar @('s3api', 'get-public-access-block', '--bucket', $bucket)
$b = $publico.PublicAccessBlockConfiguration
Revisar 'Acceso público bloqueado' ($b.BlockPublicAcls -and $b.BlockPublicPolicy -and $b.IgnorePublicAcls -and $b.RestrictPublicBuckets)

Write-Host '== Colas SQS'
$urls = (Consultar @('sqs', 'list-queues', '--queue-name-prefix', "cc-$Ambiente-")).QueueUrls
Revisar 'Veinte colas (diez con su DLQ)' ($urls.Count -eq 20) "($($urls.Count))"
foreach ($u in $urls) {
    $a = (Consultar @('sqs', 'get-queue-attributes', '--queue-url', $u, '--attribute-names', 'All')).Attributes
    $nombre = $u.Split('/')[-1]
    $cifrada = [bool]$a.KmsMasterKeyId
    if ($nombre -match '-dlq(\.fifo)?$') {
        Revisar $nombre $cifrada '(DLQ, KMS)'
    } else {
        $dlq = if ($a.RedrivePolicy) { ($a.RedrivePolicy | ConvertFrom-Json).deadLetterTargetArn.Split(':')[-1] } else { '' }
        Revisar $nombre ($cifrada -and $dlq -like '*-dlq*') "(KMS=$cifrada, DLQ=$dlq)"
    }
}

Write-Host '== Cognito'
$pool_id = Salida "CcAuth-$Ambiente" 'UserPoolId'
$pool = (Consultar @('cognito-idp', 'describe-user-pool', '--user-pool-id', $pool_id)).UserPool
Revisar 'MFA obligatorio' ($pool.MfaConfiguration -eq 'ON') "($pool_id, $($pool.MfaConfiguration))"
$mfa = Consultar @('cognito-idp', 'get-user-pool-mfa-config', '--user-pool-id', $pool_id)
Revisar 'Solo TOTP, sin SMS' ($mfa.SoftwareTokenMfaConfiguration.Enabled -and -not $mfa.SmsMfaConfiguration)
$faltan = @($esperadas.Keys | Where-Object { $pool.UserPoolTags.$_ -ne $esperadas[$_] })
Revisar 'Etiquetas del grupo' (-not $faltan) $(if ($faltan) { "faltan: $($faltan -join ',')" })

Write-Host '== Etiquetas de todos los recursos del proyecto'
$recursos = (Consultar @('resourcegroupstaggingapi', 'get-resources', '--tag-filters', "Key=proyecto,Values=$($esperadas['proyecto'])")).ResourceTagMappingList
$malos = @($recursos | Where-Object { EtiquetasOk $_.Tags })
Revisar 'Las tres etiquetas en cada recurso' ($malos.Count -eq 0) "($($recursos.Count) recursos, $($malos.Count) incompletos)"
$malos | ForEach-Object { Write-Host "       $($_.ResourceARN)" -ForegroundColor Red }

Write-Host ''
if ($script:fallos -gt 0) { Write-Host "Verificación con $($script:fallos) fallas." -ForegroundColor Red; exit 1 }
Write-Host 'Verificación de la Fase 1 correcta.' -ForegroundColor Green
exit 0
