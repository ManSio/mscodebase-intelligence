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

:: Local, direct mode: the daemon binds 127.0.0.1 and runs WITHOUT a Bearer token
:: (empty variable = auth disabled, src/remote_main.py). The hardcoded token that
:: used to live here was removed in 2026-11; the value is still in git history,
:: so rotate it before ever exposing this port. Remote/Docker deployments still
:: set MSCODEBASE_REMOTE_TOKEN on the server and in the client headers.
set "MSCODEBASE_REMOTE_TOKEN="

:: First arg = project path, else use PROJECT_PATH env, else current dir
if not "%~1"=="" (
    set "PROJECT_PATH=%~1"
) else if "%PROJECT_PATH%"=="" (
    set "PROJECT_PATH=%CD%"
)

echo Project: %PROJECT_PATH%
cd /d "%SCRIPT_DIR%"
"%VENV_PY%" -m src.remote_main --host 127.0.0.1 --port 8089
