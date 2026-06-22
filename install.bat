@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

title MSCodebase Intelligence — Установка расширения для Zed IDE

:: ============================================================================
:: Установка делегируется Python-скрипту
:: ============================================================================

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"

echo ==================================================
echo  MSCodebase Intelligence — Установка
echo ==================================================
echo.

:: Шаг 1: Проверка Python
:: ============================================================================
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден!
    echo Установите Python 3.10+ с сайта https://python.org
    echo При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
echo [1/2] ✅ Python найден: !PY_VER!

:: Шаг 2: Запуск встроенного установщика Python
:: Он сам: создаёт venv, ставит зависимости, качает модель, правит settings.json
:: ============================================================================
echo [2/2] Запуск встроенного установщика...
echo.

cd /d "!SCRIPT_DIR!"
python -u install.py

if errorlevel 1 (
    echo.
    echo ❌ Ошибка установки. Смотри вывод выше.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo  ✅ Установка завершена успешно!
echo.
echo  Следующие шаги:
echo   1. Перезапустите Zed IDE.
echo   2. Откройте любой проект.
echo   3. Откройте Agent Panel (Ctrl+Shift+P ^-> "Agent Panel: Toggle").
echo   4. Задайте вопрос: "Найди файлы, отвечающие за роутинг"
echo.
echo  Для удаления расширения запустите:
echo    !APPDATA!\Zed\extensions\mscodebase-intelligence\uninstall.bat
echo ==================================================
echo.
pause
exit /b 0
