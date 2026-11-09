@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
:: Strip trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "VENV_PY=%SCRIPT_DIR%\venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] Venv not found: %VENV_PY%
    pause
    exit /b 1
)

set "PYTHONPATH=%SCRIPT_DIR%"
set "MSCODEBASE_ALLOW_SELF_INDEX=1"

:: The remote token must come from the environment. A hardcoded default was
:: committed in 2026-11 (git 8f694ff) and is therefore in history: rotate it.
if "%MSCODEBASE_REMOTE_TOKEN%"=="" (
    echo [ERROR] MSCODEBASE_REMOTE_TOKEN is not set.
    echo         Set it first, then re-run this script:
    echo             set MSCODEBASE_REMOTE_TOKEN=^<token^>
    pause
    exit /b 1
)

:: First arg = project path, else use PROJECT_PATH env, else current dir
if not "%~1"=="" (
    set "PROJECT_PATH=%~1"
) else if "%PROJECT_PATH%"=="" (
    set "PROJECT_PATH=%CD%"
)

echo Project: %PROJECT_PATH%
cd /d "%SCRIPT_DIR%"
"%VENV_PY%" -m src.remote_main --host 127.0.0.1 --port 8089
