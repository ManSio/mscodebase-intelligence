@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ==================================================
echo  MSCodebase Intelligence - Инсталлятор
echo ==================================================
echo.

:: 1. Проверка наличия requirements.txt
if not exist "requirements.txt" (
    echo ❌ Файл requirements.txt не найден в текущей директории!
    pause
    exit /b 1
)

:: 2. Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден!
    echo Установите Python 3.10+ с сайта https://python.org
    echo При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
    pause
    exit /b 1
)

:: 3. Создание venv
echo [1/4] Создание виртуального окружения...
if not exist "venv" (
    python -m venv venv
    if !errorlevel! NEQ 0 (
        echo ❌ Не удалось создать venv. Проверьте права доступа.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

:: 4. Обновление pip
echo [2/4] Обновление pip...
python -m pip install --upgrade pip --quiet

:: 5. Установка зависимостей
echo [3/4] Установка зависимостей (это может занять время)...
python -m pip install -r requirements.txt
if !errorlevel! NEQ 0 (
    echo ❌ Ошибка установки зависимостей. Проверьте интернет-соединение.
    pause
    exit /b 1
)

:: 6. Настройка Zed
echo [4/4] Настройка Zed IDE...
echo.
echo Режим установки:
echo   1. Локально для текущего проекта (рекомендуется)
echo   2. Глобально (для всех проектов в Zed)
echo.
set /p MODE="Ваш выбор (1/2): "

if "%MODE%"=="2" (
    echo Настройка глобальной конфигурации...
    python -m src.main --install-global
) else (
    echo Настройка локальной конфигурации...
    python -m src.main --install
)

if !errorlevel! NEQ 0 (
    echo ❌ Ошибка при настройке Zed. Проверьте, запущен ли Zed.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo  ✅ Установка завершена успешно!
echo.
echo  Следующие шаги:
echo  1. Перезапустите Zed IDE.
echo  2. Откройте проект в Zed.
echo  3. Откройте Agent Panel (Ctrl+Shift+P -^> "Agent Panel: Toggle").
echo  4. Задайте вопрос: "Найди файлы, отвечающие за роутинг".
echo ==================================================
pause
