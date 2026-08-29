$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
    & .venv\Scripts\python.exe -m pip install --upgrade pip
}

$DependencyStatus = & .venv\Scripts\python.exe -c "import importlib.util; names = ('PySide6', 'keyboard', 'pyperclip'); print('ready' if all(importlib.util.find_spec(name) for name in names) else 'missing')"
if ($DependencyStatus -ne "ready") {
    & .venv\Scripts\python.exe -m pip install -r requirements.txt
}

& .venv\Scripts\python.exe run.py
