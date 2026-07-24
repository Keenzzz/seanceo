<#
.SYNOPSIS
    (Re)cree la tache planifiee qui rafraichit les snapshots Pathe/CGR/Grand Ecran.

.DESCRIPTION
    Le rafraichissement des chaines doit partir d'une IP residentielle (ces API
    bloquent les datacenters). On le confie donc au Planificateur de taches
    Windows, sous le compte de l'utilisateur, "seulement quand il est connecte" :
    pas de service, pas de compte systeme, pas de mot de passe. La tache lance
    scripts/refresh_chains.py (collecte + garde-fou + commit + push).

    A lancer une fois (aucun droit admin requis pour une tache "quand connecte").
    Idempotent : -Force remplace une tache existante du meme nom.

    ASCII pur : PowerShell 5.1 lit les .ps1 en cp1252.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1
#>

param(
    [string]$RepoDir  = "C:\Users\knz92\Projects\cine-indes",
    [string]$TaskName = "Seanceo - rafraichir snapshots chaines",
    [int]$DaysInterval = 2,
    [string]$AtTime   = "5am"
)

$ErrorActionPreference = "Stop"

# Chemin de Python : on prend celui qui execute ce script si dispo, sinon on
# resout via la commande 'python'. Le pipeline est stdlib pur, toute 3.x va.
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Python introuvable dans le PATH." }

$action  = New-ScheduledTaskAction -Execute $py -Argument "scripts\refresh_chains.py" -WorkingDirectory $RepoDir
$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval $DaysInterval -At $AtTime
# StartWhenAvailable = rattrape un run manque si le PC etait eteint a l'heure dite.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# Compte courant, "seulement quand l'utilisateur est connecte" (pas de mot de passe).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Collecte Pathe/CGR/Grand Ecran (IP residentielle) puis commit+push. Voir scripts/refresh_chains.py." `
    -Force | Out-Null

Write-Host "OK - tache '$TaskName' creee (tous les $DaysInterval jours a $AtTime)." -ForegroundColor Green
Write-Host "Lancer maintenant : Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Green
Write-Host "Voir l'etat       : Get-ScheduledTaskInfo -TaskName '$TaskName'" -ForegroundColor Green
Write-Host "Mettre en pause   : Disable-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Green
