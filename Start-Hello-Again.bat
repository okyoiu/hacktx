@echo off
setlocal
cd /d "%~dp0"
title Hello Again - Launcher

echo ========================================
echo          Hello Again Launcher
echo ========================================
echo.

REM Verify this launcher is in the project root.
if not exist "pyproject.toml" (
    echo ERROR: I cannot find pyproject.toml in:
    echo   %CD%
    echo.
    echo Move this .bat file into the main hacktx-main project folder,
    echo beside pyproject.toml, .env.example, capture, memory, and overlay.
    echo.
    pause
    exit /b 1
)

REM Ensure local environment file exists.
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo Created .env from .env.example.
        echo Add your real API keys and database settings, save, then run this launcher again.
        start "Edit Hello Again .env" notepad.exe "%CD%\.env"
        pause
        exit /b 1
    ) else (
        echo ERROR: .env is missing and .env.example was not found.
        pause
        exit /b 1
    )
)

REM Check required tools.
where uv >nul 2>nul
if errorlevel 1 (
    echo ERROR: uv was not found on PATH. Install uv, then reopen Windows or sign out/in.
    echo See https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
    echo ERROR: Node.js was not found on PATH. Install Node.js LTS, then reopen this launcher.
    echo See https://nodejs.org/en/download
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Setting up Python dependencies...
    uv sync
    if errorlevel 1 goto :failed
) else (
    echo Python virtual environment found.
)

if not exist "overlay\package.json" (
    echo ERROR: overlay\package.json was not found. Is this the project root?
    pause
    exit /b 1
)

if not exist "overlay\node_modules" (
    echo Installing overlay dependencies...
    pushd overlay
    call npm.cmd install
    if errorlevel 1 (
        popd
        goto :failed
    )
    popd
) else (
    echo Overlay dependencies found.
)

echo.
echo Starting Hello Again...
echo Keep this window open while using the app.
echo.
pushd overlay
call npm.cmd start
set "APP_EXIT=%ERRORLEVEL%"
popd
if not "%APP_EXIT%"=="0" goto :failed
exit /b 0

:failed
echo.
echo Hello Again could not start because a setup or launch command failed.
echo Read the error above, fix it, and double-click this file again.
pause
exit /b 1
