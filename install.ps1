<#
.SYNOPSIS
    TENJIN Autonomous Engineering System Installation Script for Windows.
.DESCRIPTION
    Inspects environment prerequisites, creates the isolated virtual environment,
    installs dependencies, initializes SQLite storage, runs self-tests,
    and configures Windows Task Scheduler automatic background startup.
#>

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "TENJIN (天神) SYSTEM INSTALLATION & PREFLIGHT" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Inspect Python
Write-Host "`n[1/7] Inspecting Python environment..." -ForegroundColor Yellow
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue

if (-not $pyCmd -and -not $uvCmd) {
    Write-Error "Python 3.10+ or uv is required to install TENJIN. Neither was found."
}

# 2. Inspect Git
Write-Host "[2/7] Verifying Git version control..." -ForegroundColor Yellow
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Write-Error "Git is required for TENJIN isolated workspaces. Please install Git for Windows."
}
Write-Host "  Git found: $($gitCmd.Source)" -ForegroundColor Green

# 3. Inspect GitHub CLI
Write-Host "[3/7] Verifying GitHub authentication..." -ForegroundColor Yellow
$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
if ($ghCmd) {
    $ghAuth = & $ghCmd.Source auth status 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  GitHub CLI is authenticated." -ForegroundColor Green
    } else {
        Write-Host "  GitHub CLI installed but not authenticated. Run 'gh auth login' or export GITHUB_TOKEN." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "  GitHub CLI not detected. You may authenticate via GITHUB_TOKEN environment variable." -ForegroundColor DarkYellow
}

# 4. Create Virtual Environment
Write-Host "[4/7] Establishing virtual environment and installing dependencies..." -ForegroundColor Yellow
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if ($uvCmd) {
    if (-not (Test-Path "$scriptDir\.venv")) {
        & uv venv "$scriptDir\.venv" --python 3.12
    }
    & uv pip install -e ".[dev]"
} else {
    if (-not (Test-Path "$scriptDir\.venv")) {
        & python -m venv "$scriptDir\.venv"
    }
    & "$scriptDir\.venv\Scripts\pip.exe" install -e ".[dev]"
}

$tenjinExe = "$scriptDir\.venv\Scripts\tenjin.exe"
if (-not (Test-Path $tenjinExe)) {
    Write-Error "Failed to install tenjin CLI entrypoint at $tenjinExe"
}
Write-Host "  Installed tenjin CLI entrypoint." -ForegroundColor Green

# 5. Initialize Storage & Capability Doctor
Write-Host "[5/7] Executing system diagnostics & self-test..." -ForegroundColor Yellow
& $tenjinExe doctor
& $tenjinExe self-test

# 6. Configure Windows Task Scheduler
Write-Host "[6/7] Configuring Windows Task Scheduler for startup on logon..." -ForegroundColor Yellow
& $tenjinExe install

# 7. Initial Repository Discovery
Write-Host "[7/7] Executing initial repository synchronization..." -ForegroundColor Yellow
& $tenjinExe repos

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "TENJIN INSTALLATION COMPLETE" -ForegroundColor Green
Write-Host "Dashboard:  tenjin dashboard --port 8765" -ForegroundColor White
Write-Host "Daemon:     tenjin start" -ForegroundColor White
Write-Host "Doctor:     tenjin doctor" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
