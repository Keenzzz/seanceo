<#
.SYNOPSIS
    Repare le service du runner GitHub qui refuse de demarrer (erreur Win 1068).

.DESCRIPTION
    A lancer dans un PowerShell ADMINISTRATEUR. Le service du runner a ete
    installe mais n'a pas pu demarrer (erreur 1068). Ce script tente, dans
    l'ordre, du moins au plus intrusif :
      1. donner au compte NETWORK SERVICE les permissions sur le dossier runner ;
      2. lui accorder le droit "Ouvrir une session en tant que service" ;
      3. demarrer le service.
    Si ca ne suffit pas, il propose de RECONFIGURER le service sous TON compte
    Windows (il demande alors ton mot de passe, saisi localement, jamais transmis).

    ASCII pur : PowerShell 5.1 lit les .ps1 en cp1252, les accents casseraient tout.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\fix_runner_service.ps1
#>

param(
    [string]$Repo      = "Keenzzz/seanceo",
    [string]$RunnerDir = "C:\actions-runner"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = `
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Fail($m) { Write-Host "ECHEC : $m" -ForegroundColor Red; exit 1 }

# --- 0. Admin ----------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent() `
    ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $admin) { Fail "Relance dans un PowerShell ADMINISTRATEUR." }

# --- Trouver le service ------------------------------------------------------
$svc = Get-Service | Where-Object { $_.Name -like "actions.runner.*" } | Select-Object -First 1
if (-not $svc) { Fail "Aucun service de runner trouve. Relance d'abord setup_runner.ps1." }
$svcName = $svc.Name
Write-Host "Service cible : $svcName (etat $($svc.Status))" -ForegroundColor Cyan

# --- 1. Permissions sur le dossier -------------------------------------------
Write-Host "1/3  Permissions NETWORK SERVICE sur $RunnerDir..." -ForegroundColor Cyan
& icacls $RunnerDir /grant "*S-1-5-20:(OI)(CI)F" /T /Q | Out-Null

# --- 2. Droit 'Ouvrir une session en tant que service' pour NETWORK SERVICE ---
Write-Host "2/3  Droit 'log on as a service' pour NETWORK SERVICE..." -ForegroundColor Cyan
$inf = "$env:TEMP\rt_secpol.inf"
$sdb = "$env:TEMP\rt_secpol.sdb"
& secedit /export /cfg $inf /areas USER_RIGHTS | Out-Null
$content = Get-Content $inf
$sid = "*S-1-5-20"   # NT AUTHORITY\NETWORK SERVICE
if ($content -match '^SeServiceLogonRight') {
    $line = ($content | Where-Object { $_ -match '^SeServiceLogonRight' })
    if ($line -notmatch [regex]::Escape($sid)) {
        $content = $content -replace '^(SeServiceLogonRight.*)$', "`$1,$sid"
    }
} else {
    $content = $content -replace '(\[Privilege Rights\])', "`$1`r`nSeServiceLogonRight = $sid"
}
$content | Set-Content $inf -Encoding Unicode
& secedit /configure /db $sdb /cfg $inf /areas USER_RIGHTS | Out-Null
Remove-Item $inf, $sdb -ErrorAction SilentlyContinue

# --- 3. Tentative de demarrage -----------------------------------------------
Write-Host "3/3  Demarrage du service..." -ForegroundColor Cyan
try { Start-Service $svcName -ErrorAction Stop } catch {}
Start-Sleep -Seconds 3
$svc = Get-Service $svcName
if ($svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "OK -- le service tourne (NETWORK SERVICE). Rien d'autre a faire." -ForegroundColor Green
    Write-Host "Test : GitHub > onglet Actions > 'Rafraichir snapshots chaines' > Run workflow." -ForegroundColor Green
    exit 0
}

# --- Repli : reconfiguration sous le compte utilisateur ----------------------
Write-Host ""
Write-Host "NETWORK SERVICE n'a pas suffi. On bascule le service sous TON compte." -ForegroundColor Yellow
$acct = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Compte : $acct" -ForegroundColor Yellow
Write-Host "(Si tu te connectes par code PIN / compte Microsoft sans mot de passe tape," -ForegroundColor Yellow
Write-Host " ce repli ne marchera pas -- dis-le moi, on prendra une autre voie.)" -ForegroundColor Yellow
$sec = Read-Host "Mot de passe Windows de $acct" -AsSecureString
$pw  = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
if (-not $pw) { Fail "Mot de passe vide." }

# Jeton GitHub pour re-enregistrer proprement
$cred  = "protocol=https`nhost=github.com`n`n" | git credential fill
$token = ($cred | Where-Object { $_ -like 'password=*' }) -replace '^password=', ''
if (-not $token) { Fail "Aucun jeton GitHub trouve." }
$gh = @{ Authorization = "Bearer $token"; "User-Agent" = "seanceo-fix-runner"; Accept = "application/vnd.github+json" }

# Supprimer le service casse
Stop-Service $svcName -Force -ErrorAction SilentlyContinue
& sc.exe delete $svcName | Out-Null
Start-Sleep -Seconds 2

Push-Location $RunnerDir
try {
    # Nettoyer l'enregistrement precedent puis re-enregistrer sous le compte user
    try {
        $rem = (Invoke-RestMethod -Method Post -Headers $gh `
            -Uri "https://api.github.com/repos/$Repo/actions/runners/remove-token").token
        & .\config.cmd remove --token $rem
    } catch { Write-Host "  (nettoyage de l'ancien enregistrement ignore)" -ForegroundColor DarkGray }

    $reg = (Invoke-RestMethod -Method Post -Headers $gh `
        -Uri "https://api.github.com/repos/$Repo/actions/runners/registration-token").token
    & .\config.cmd --unattended --replace `
        --url "https://github.com/$Repo" `
        --token $reg `
        --name "$env:COMPUTERNAME-seanceo" `
        --labels "windows" `
        --runasservice `
        --windowslogonaccount $acct `
        --windowslogonpassword $pw
    if ($LASTEXITCODE -ne 0) { Fail "config.cmd a echoue (code $LASTEXITCODE)." }
} finally {
    Pop-Location
}

Start-Sleep -Seconds 3
$svc = Get-Service | Where-Object { $_.Name -like "actions.runner.*" } | Select-Object -First 1
if ($svc -and $svc.Status -ne "Running") { Start-Service $svc.Name -ErrorAction SilentlyContinue; Start-Sleep 2; $svc = Get-Service $svc.Name }
if ($svc -and $svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "OK -- le service tourne sous $acct ($($svc.Name))." -ForegroundColor Green
    Write-Host "Test : GitHub > onglet Actions > 'Rafraichir snapshots chaines' > Run workflow." -ForegroundColor Green
} else {
    Fail "Le service ne demarre toujours pas. Copie-moi la sortie ci-dessus."
}
