$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
}

& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements-build.txt
& .venv\Scripts\python.exe -m unittest discover -s tests -v

& .venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name LeaveCalendar `
    run.py

Write-Host ""
Write-Host "Build complete: $ProjectRoot\dist\LeaveCalendar.exe" -ForegroundColor Green
