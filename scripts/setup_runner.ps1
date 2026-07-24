<#
.SYNOPSIS
    Installe le runner GitHub self-hosted pour rafraichir les snapshots de chaines.

.DESCRIPTION
    A lancer UNE FOIS, dans un PowerShell ADMINISTRATEUR (l'installation du
    service Windows l'exige). Le script :
      1. lit le jeton GitHub depuis le gestionnaire d'identifiants (compte Keenzzz) ;
      2. demande a l'API GitHub un jeton d'enregistrement de runner (ephemere) ;
      3. telecharge la derniere version du runner GitHub (win-x64) ;
      4. l'extrait dans C:\actions-runner ;
      5. l'enregistre sur le depot et l'installe en SERVICE (demarre au boot,
         tourne sans session ouverte -- indispensable pour un PC allume par
         intermittence) ;
      6. demarre le service.

    Le service tourne sous NT AUTHORITY\NETWORK SERVICE et sort par ta connexion
    (IP residentielle) : c'est ce qui permet de collecter Pathe/CGR/Grand Ecran,
    que les IP de datacenter ne peuvent pas atteindre.

    Aucun secret n'est stocke dans ce fichier : le jeton est lu a l'execution.

    Fichier volontairement en ASCII pur : Windows PowerShell 5.1 lit les .ps1 en
    cp1252, des accents UTF-8 y casseraient le parsing.

.EXAMPLE
    # Dans un PowerShell "Executer en tant qu'administrateur" :
    powershell -ExecutionPolicy Bypass -File scripts\setup_runner.ps1
#>

param(
    [string]$Repo      = "Keenzzz/seanceo",
    [string]$RunnerDir = "C:\actions-runner",
    [string]$Name      = "$env:COMPUTERNAME-seanceo"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = `
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Fail($msg) { Write-Host "ECHEC : $msg" -ForegroundColor Red; exit 1 }

# --- 0. Verifier les droits administrateur -----------------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent() `
    ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $admin) {
    Fail "Relance ce script dans un PowerShell ADMINISTRATEUR (installation du service requise)."
}

# --- 1. Jeton GitHub depuis le gestionnaire d'identifiants -------------------
Write-Host "1/6  Lecture du jeton GitHub (gestionnaire d'identifiants)..." -ForegroundColor Cyan
$cred  = "protocol=https`nhost=github.com`n`n" | git credential fill
$token = ($cred | Where-Object { $_ -like 'password=*' }) -replace '^password=', ''
if (-not $token) { Fail "Aucun jeton GitHub trouve. Fais un 'git push' manuel une fois pour l'enregistrer." }

$ghHeaders = @{
    Authorization = "Bearer $token"
    "User-Agent"  = "seanceo-setup-runner"
    Accept        = "application/vnd.github+json"
}

# --- 2. Jeton d'enregistrement de runner -------------------------------------
Write-Host "2/6  Demande d'un jeton d'enregistrement de runner..." -ForegroundColor Cyan
try {
    $reg = (Invoke-RestMethod -Method Post -Headers $ghHeaders `
        -Uri "https://api.github.com/repos/$Repo/actions/runners/registration-token").token
} catch {
    Fail "Impossible d'obtenir un jeton d'enregistrement (droit admin sur $Repo requis). $_"
}

# --- 3. Derniere version du runner -------------------------------------------
Write-Host "3/6  Recherche de la derniere version du runner..." -ForegroundColor Cyan
$rel = Invoke-RestMethod -Headers @{ "User-Agent" = "seanceo-setup-runner" } `
    -Uri "https://api.github.com/repos/actions/runner/releases/latest"
$ver = $rel.tag_name.TrimStart('v')
$url = "https://github.com/actions/runner/releases/download/v$ver/actions-runner-win-x64-$ver.zip"
Write-Host "     version $ver"

# --- 4. Telechargement + extraction ------------------------------------------
Write-Host "4/6  Telechargement et extraction dans $RunnerDir..." -ForegroundColor Cyan
if (-not (Test-Path $RunnerDir)) { New-Item -ItemType Directory -Path $RunnerDir | Out-Null }
$zip = Join-Path $RunnerDir "runner.zip"
Invoke-WebRequest -Uri $url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $RunnerDir -Force
Remove-Item $zip

# --- 5. Enregistrement + installation en service -----------------------------
Write-Host "5/6  Enregistrement du runner et installation du service..." -ForegroundColor Cyan
Push-Location $RunnerDir
try {
    & .\config.cmd --unattended --replace `
        --url "https://github.com/$Repo" `
        --token $reg `
        --name $Name `
        --labels "windows" `
        --runasservice
    if ($LASTEXITCODE -ne 0) { Fail "config.cmd a echoue (code $LASTEXITCODE)." }
} finally {
    Pop-Location
}

# --- 6. Verification du service ----------------------------------------------
Write-Host "6/6  Verification du service..." -ForegroundColor Cyan
$svc = Get-Service | Where-Object { $_.Name -like "actions.runner.*" } | Select-Object -First 1
if ($svc) {
    if ($svc.Status -ne "Running") { Start-Service $svc.Name }
    Write-Host ""
    Write-Host "OK -- runner '$Name' installe en service ($($svc.Name), etat $($svc.Status))." -ForegroundColor Green
    Write-Host "Il apparait dans GitHub : Settings > Actions > Runners." -ForegroundColor Green
    Write-Host "Prochain rafraichissement auto : cron du workflow (tous les 2 jours)." -ForegroundColor Green
    Write-Host "Test immediat : onglet Actions > 'Rafraichir snapshots chaines' > Run workflow." -ForegroundColor Green
} else {
    Fail "Service du runner introuvable apres installation."
}
