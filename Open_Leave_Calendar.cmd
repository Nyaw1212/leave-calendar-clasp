@echo off
setlocal
cd /d "%~dp0python_app" || (echo Could not find the python_app folder.& pause & exit /b 1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\run_windows.ps1"
if errorlevel 1 (
    echo.
    echo The app could not be started. Review the message above.
    pause
    exit /b 1
)
endlocal
