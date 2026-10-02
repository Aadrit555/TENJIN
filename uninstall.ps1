<#
.SYNOPSIS
    TENJIN Autonomous Engineering System Uninstallation Script.
.DESCRIPTION
    Stops background daemons, unregisters Windows Task Scheduler tasks,
    and removes background services cleanly without deleting user code.
#>

$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "TENJIN SYSTEM UNINSTALLATION" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$tenjinExe = "$scriptDir\.venv\Scripts\tenjin.exe"

# 1. Stop Daemon
if (Test-Path $tenjinExe) {
    Write-Host "`nStopping active TENJIN daemon..." -ForegroundColor White
    & $tenjinExe stop
}

# 2. Unregister Windows Scheduled Task
Write-Host "Unregistering Windows Task Scheduler background task..." -ForegroundColor White
if (Test-Path $tenjinExe) {
    & $tenjinExe uninstall
} else {
    $schtasks = Get-Command schtasks -ErrorAction SilentlyContinue
    if ($schtasks) {
        & schtasks /Delete /TN "TENJIN_Personal_Engineer" /F 2>&1 | Out-Null
    }
}

# 3. Clean up PID file
$pidPath = "$scriptDir\data\worker.pid"
if (Test-Path $pidPath) {
    Remove-Item -Force $pidPath
}

Write-Host "`nTENJIN background service uninstalled successfully." -ForegroundColor Green
Write-Host "Local database and audit reports were preserved in $scriptDir\data and $scriptDir\reports." -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Yellow
