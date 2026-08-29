$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
    & .venv\Scripts\python.exe -m pip install --upgrade pip
}

& .venv\Scripts\python.exe -c "import PySide6, keyboard, pyperclip" 2>$null
if ($LASTEXITCODE -ne 0) {
    & .venv\Scripts\python.exe -m pip install -r requirements.txt
}

& .venv\Scripts\python.exe run.py
