@echo off
REM ============================================================================
REM sync_to_installed.bat — Синхронизация исходников расширения с установленной
REM                         копией в %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
REM
REM Использование:
REM   sync_to_installed.bat          — синхронизация исходников (исключая venv/)
REM   sync_to_installed.bat --full   — полная синхронизация (включая .gitignore)
REM
REM После синхронизации требуется перезапустить Zed для подхвата новых версий.
REM ============================================================================
setlocal enabledelayedexpansion

set SOURCE=%~dp0
set DEST=%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence

if not exist "%DEST%" (
    echo [ERROR] Папка расширения не найдена: %DEST%
    echo [INFO]  Установите расширение сначала через install.bat
    exit /b 1
)

echo ============================================================================
echo  MSCodeBase Intelligence — Sync to Installed
echo  Source: %SOURCE%
echo  Dest:   %DEST%
echo ============================================================================
echo.

REM --- Папки для синхронизации (исключаем venv, __pycache__, .codebase_indices) ---
set DIRS=src docs tests scripts .github .zed .agents

REM --- Файлы в корне ---
set FILES=*.py *.bat *.md *.toml *.txt *.cfg .gitignore .gitattributes .zed.settings.json.example

echo [1/4] Копирование исходников (src/)...
robocopy "%SOURCE%src" "%DEST%\src" /E /NP /NDL /NFL /NS /NC ^
    /XD __pycache__ .pyc "*.pyc" .pytest_cache .venv ^
    /XF "*.pyc" "*.pyo" >nul 2>&1

echo [2/4] Копирование документации (docs/)...
if exist "%SOURCE%docs" (
    robocopy "%SOURCE%docs" "%DEST%\docs" /E /NP /NDL /NFL /NS /NC >nul 2>&1
)

echo [3/4] Копирование конфигурационных файлов...
robocopy "%SOURCE%." "%DEST%." *.py *.bat *.md *.toml *.cfg .gitignore ^
    /NP /NDL /NFL /NS /NC >nul 2>&1

echo [4/4] Копирование скиллов (.agents/)...
if exist "%SOURCE%.agents" (
    robocopy "%SOURCE%.agents" "%DEST%\.agents" /E /NP /NDL /NFL /NS /NC >nul 2>&1
)

echo.
echo [OK] Синхронизация завершена.
echo [INFO] Перезапустите Zed, чтобы изменения вступили в силу.
echo.
echo  Файлы синхронизированы:
echo    - src/mcp/server.py      — MCP инструменты (26 tools)
echo    - src/utils/zed_config.py — Автонастройка Zed
echo    - src/core/              — Ядро расширения
echo    - docs/                  — Документация
echo    - .agents/skills/        — Скиллы для AI-агента
echo.
echo  ПРИМЕЧАНИЕ: venv/ не синхронизируется (изолированное окружение)
echo              для обновления зависимостей запустите: python -m pip install -r requirements.txt
echo.

REM --- Очистка stale-файлов в installed, которых нет в source ---
if /I "%1"=="--full" (
    echo [4b/4] Очистка stale-файлов...
    for %%d in (%DIRS%) do (
        if exist "%DEST%\%%d" (
            robocopy "%SOURCE%%%d" "%DEST%\%%d" /MIR /NP /NDL /NFL /NS /NC ^
                /XD __pycache__ .pyc .pytest_cache .venv ^
                /XF "*.pyc" "*.pyo" >nul 2>&1
        )
    )
    echo [OK] Stale-файлы удалены.
    echo [INFO] Полная синхронизация с зеркалированием завершена.
) else (
    echo [INFO] Для синхронизации с удалением файлов используйте: sync_to_installed.bat --full
)

endlocal
