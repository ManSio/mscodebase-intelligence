@echo off
REM ============================================================================
REM fix_zed_settings.bat — Удаляет current_dir из настроек MSCodeBase в Zed
REM
REM Проблема: Zed не подставляет $ZED_WORKTREE_ROOT в current_dir (баг #36019).
REM Из-за этого MCP-сервер стартует с CWD=literal и не находит проект.
REM Решение: убрать current_dir — resolve_project_root() сам определит корень.
REM
REM Использование: fix_zed_settings.bat
REM ============================================================================
setlocal enabledelayedexpansion

set SETTINGS=%APPDATA%\Zed\settings.json

if not exist "%SETTINGS%" (
    echo [ERROR] Файл настроек не найден: %SETTINGS%
    echo [INFO]  Откройте Zed хотя бы раз, чтобы создать settings.json
    exit /b 1
)

echo ============================================================================
echo  MSCodeBase Intelligence — Fix Zed settings
echo  File: %SETTINGS%
echo ============================================================================
echo.

REM Создаём бэкап
set BACKUP=%SETTINGS%.backup.%RANDOM%
copy /Y "%SETTINGS%" "%BACKUP%" >nul
echo [1/4] Бэкап создан: %BACKUP%

REM Удаляем current_dir через Python (безопаснее, чем sed на Windows)
python -c "
import json, sys
p = r'%SETTINGS%'
try:
    with open(p, 'r', encoding='utf-8') as f:
        s = json.load(f)
except json.JSONDecodeError as e:
    print(f'[ERROR] Невозможно распарсить {p}: {e}', file=sys.stderr)
    sys.exit(1)

changed = False
# MCP server
mcp = s.get('context_servers', {}).get('mscodebase-intelligence', {})
if 'current_dir' in mcp:
    print(f'[2/4] Удаляю current_dir из MCP-сервера (было: {mcp[\"current_dir\"]!r})')
    del mcp['current_dir']
    changed = True

# LSP server
lsp = s.get('lsp', {}).get('mscodebase-lsp', {})
if 'current_dir' in lsp:
    print(f'[3/4] Удаляю current_dir из LSP-сервера (было: {lsp[\"current_dir\"]!r})')
    del lsp['current_dir']
    changed = True

if changed:
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=4, ensure_ascii=False)
    print('[4/4] OK — настройки Zed обновлены. Перезапустите Zed.')
else:
    print('[4/4] OK — current_dir не найден, ничего не меняли.')
"
set RC=%ERRORLEVEL%
if not %RC% == 0 (
    echo [ERROR] Python-скрипт завершился с кодом %RC%
    exit /b %RC%
)

echo.
echo [DONE] Готово. Следующие шаги:
echo   1. Перезапустите Zed IDE.
echo   2. Откройте проект.
echo   3. Проверьте логи MCP: mscodebase-intelligence должен определить project_root.
echo.
echo Если project_root не определится — откройте issue, добавив вывод:
echo   python -m src.main --help
echo.
endlocal
