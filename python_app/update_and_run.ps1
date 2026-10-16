$ErrorActionPreference = "Stop"

# The app starts this script, then closes itself.  Waiting briefly prevents Git
# from replacing files while the old Python process is still shutting down.
Start-Sleep -Milliseconds 750

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

Write-Host ""
Write-Host "Updating Leave Calendar…" -ForegroundColor Cyan
& git pull --ff-only origin python-desktop-v2

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Update failed. The app was not restarted." -ForegroundColor Red
    Write-Host "Resolve the Git message above, then start the app again." -ForegroundColor Yellow
    Read-Host "Press Enter to close this window"
    exit $LASTEXITCODE
}

Set-Location $PSScriptRoot
& "$PSScriptRoot\run_windows.ps1"
