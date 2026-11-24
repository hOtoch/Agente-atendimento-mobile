<#
.SYNOPSIS
  Deploy na VPS com um comando: build do painel, conferencia do bundle, envio, migrations e restart.

.DESCRIPTION
  Envia sempre um COMMIT (padrao: origin/main), nunca alteracoes locais soltas. O build do painel roda
  numa worktree propria (.worktrees/deploy) no commit exato, com NEXT_PUBLIC_API_URL=/api definido
  aqui no PowerShell (o Git Bash converteria /api num caminho do Windows). Na VPS, cada deploy vira um
  release novo; se a API ou o painel nao subirem, o deploy anterior volta sozinho.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File infra\prod\deploy.ps1
  powershell -ExecutionPolicy Bypass -File infra\prod\deploy.ps1 -Ref main -SemConfirmar
#>
param(
  [string]$Ref = 'origin/main',
  [string]$Servidor = 'root@189.24.10.237',
  [string]$Chave = (Join-Path $env:USERPROFILE '.ssh\id_ed25519_vps'),
  [string]$Dominio = '189-24-10-237.sslip.io',
  [switch]$SemConfirmar
)

$ErrorActionPreference = 'Stop'
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Tar = Join-Path $env:SystemRoot 'System32\tar.exe'
$SshOpts = @('-i', $Chave, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20')

function Write-Passo([string]$Texto) { Write-Host "`n== $Texto" -ForegroundColor Cyan }

# O codigo de saida decide se um programa falhou. Em PowerShell 5.1, texto no stderr (progresso do git,
# avisos do npm) nao pode virar erro: por isso 'Continue' dentro destas funcoes.
function Invoke-Nativo {
  param([string]$Exe, [string[]]$Argumentos)
  $ErrorActionPreference = 'Continue'
  & $Exe @Argumentos
  if ($LASTEXITCODE -ne 0) { throw "falhou ($LASTEXITCODE): $Exe $($Argumentos -join ' ')" }
}

function Get-Saida {
  param([string]$Exe, [string[]]$Argumentos)
  $ErrorActionPreference = 'Continue'
  $saida = & $Exe @Argumentos
  if ($LASTEXITCODE -ne 0) { throw "falhou ($LASTEXITCODE): $Exe $($Argumentos -join ' ')" }
  return $saida
}

if (-not (Test-Path $Chave)) { throw "chave SSH nao encontrada: $Chave" }

Write-Passo "conexao com $Servidor"
# Antes do build: falha em segundos se a chave ou o servidor tiverem problema.
$ErrorActionPreference = 'Continue'
& ssh @SshOpts $Servidor 'true'
$codigo = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($codigo -ne 0) {
  throw ("sem acesso SSH a $Servidor (codigo $codigo). Se aparecer 'bad permissions', a chave privada " +
    "precisa ser lida so pelo seu usuario: icacls `"$Chave`" /inheritance:r /grant:r `"$($env:USERNAME):(R,W)`"")
}
Write-Host 'ok'

Write-Passo "commit a enviar"
Invoke-Nativo git @('-C', $Raiz, 'fetch', 'origin', '--quiet')
$Sha = (Get-Saida git @('-C', $Raiz, 'rev-parse', '--verify', "$Ref^{commit}")).Trim()
$Curto = $Sha.Substring(0, 7)
Invoke-Nativo git @('-C', $Raiz, 'log', '-1', '--format=%h %s (%an, %ar)', $Sha)
$NoOrigin = Get-Saida git @('-C', $Raiz, 'branch', '-r', '--contains', $Sha)
if (-not $NoOrigin) {
  Write-Host "ATENCAO: $Curto ainda nao esta no GitHub (origin). Vai para a VPS mesmo assim." -ForegroundColor Yellow
}
if (-not $SemConfirmar) {
  $resposta = Read-Host "Enviar $Curto para $Dominio? (s/N)"
  if ($resposta -notmatch '^[sS]') { Write-Host 'cancelado'; exit 1 }
}

Write-Passo "worktree de build ($Curto)"
$Wt = Join-Path $Raiz '.worktrees\deploy'
if (-not (Test-Path (Join-Path $Wt '.git'))) {
  Invoke-Nativo git @('-C', $Raiz, 'worktree', 'add', '--detach', $Wt, $Sha)
} else {
  Invoke-Nativo git @('-C', $Wt, 'checkout', '--detach', '--force', '--quiet', $Sha)
  Invoke-Nativo git @('-C', $Wt, 'clean', '-fdq')
}
$Front = Join-Path $Wt 'frontend'

$HashLock = (Get-FileHash (Join-Path $Front 'package-lock.json')).Hash
$MarcaLock = Join-Path $Front 'node_modules\.deploy-lock-hash'
if (-not (Test-Path $MarcaLock) -or (Get-Content $MarcaLock -Raw).Trim() -ne $HashLock) {
  Write-Passo "npm ci (package-lock mudou)"
  Push-Location $Front
  try { Invoke-Nativo npm.cmd @('ci', '--no-audit', '--no-fund', '--loglevel=error') } finally { Pop-Location }
  Set-Content -Path $MarcaLock -Value $HashLock -Encoding ascii
}

Write-Passo "build do painel (NEXT_PUBLIC_API_URL=/api)"
$Next = Join-Path $Front '.next'
if (Test-Path $Next) { Remove-Item -Recurse -Force $Next }
$antes = $env:NEXT_PUBLIC_API_URL
$env:NEXT_PUBLIC_API_URL = '/api'
Push-Location $Front
try { Invoke-Nativo npm.cmd @('run', 'build') } finally { Pop-Location; $env:NEXT_PUBLIC_API_URL = $antes }

Write-Passo "conferencia do bundle"
$Estaticos = Get-ChildItem -Path (Join-Path $Next 'static') -Recurse -File -Include *.js
foreach ($proibido in @('Program Files', 'localhost:8000')) {
  $achou = $Estaticos | Select-String -SimpleMatch $proibido -List | Select-Object -First 1
  if ($achou) { throw "bundle invalido: '$proibido' em $($achou.Path)" }
}
Write-Host "ok: sem 'Program Files' nem 'localhost:8000' no JS do navegador"

Write-Passo "pacotes"
$Tmp = Join-Path $env:TEMP "deploy-atendimento-$Curto"
if (Test-Path $Tmp) { Remove-Item -Recurse -Force $Tmp }
New-Item -ItemType Directory -Path $Tmp | Out-Null
$PacoteApp = Join-Path $Tmp 'app.tar.gz'
$PacoteNext = Join-Path $Tmp 'next.tar.gz'
Invoke-Nativo git @('-C', $Raiz, 'archive', '--format=tar.gz', '-o', $PacoteApp, $Sha)
Invoke-Nativo $Tar @('-czf', $PacoteNext, '-C', $Front, '--exclude', '.next/cache', '--exclude', '.next/dev', '.next')
Get-ChildItem $Tmp | ForEach-Object { Write-Host ("{0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)) }

Write-Passo "envio para $Servidor"
Invoke-Nativo scp ($SshOpts + @($PacoteApp, $PacoteNext, "${Servidor}:/tmp/"))

$Release = "/opt/atendimento/releases/$(Get-Date -Format 'yyyyMMdd-HHmmss')-$Curto"
$Remoto = "set -e; mkdir -p '$Release/frontend'; " +
  "tar -xzf /tmp/app.tar.gz -C '$Release'; tar -xzf /tmp/next.tar.gz -C '$Release/frontend'; " +
  "rm -f /tmp/app.tar.gz /tmp/next.tar.gz; " +
  "bash '$Release/infra/prod/deploy-remoto.sh' '$Release' '$Dominio'"
Write-Passo "na VPS"
Invoke-Nativo ssh ($SshOpts + @($Servidor, $Remoto))
Remove-Item -Recurse -Force $Tmp

Write-Passo "conferencia pelo dominio"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$saude = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 "https://$Dominio/api/health"
$login = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 "https://$Dominio/login"
Write-Host "api/health: $($saude.StatusCode) $($saude.Content)"
Write-Host "login: $($login.StatusCode)"
Write-Host "`nDeploy de $Curto concluido em https://$Dominio" -ForegroundColor Green
