@echo off
setlocal EnableDelayedExpansion

title MSCodebase Intelligence — MCP Server (manual start)

:: ─── Portable launch (WIN-15 audit fix) ────────────────────────────
:: Скрипт не зависит от машины автора: все пути выводятся из %~dp0.
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"

cd /d "!SCRIPT_DIR!"
if errorlevel 1 (
    echo [ERROR] Не удалось перейти в каталог расширения: !SCRIPT_DIR!
    pause
    exit /b 1
)

set "VENV_PY=!SCRIPT_DIR!\venv\Scripts\python.exe"
if not exist "!VENV_PY!" (
    echo [ERROR] Виртуальное окружение не найдено: !VENV_PY!
    echo Запустите сначала: python install.py
    pause
    exit /b 1
)

:: PYTHONUTF8=1 — принудительная UTF-8 кодировка (cp1251 ломает индексацию)
set "PYTHONUTF8=1"
"!VENV_PY!" -u -m src.main
