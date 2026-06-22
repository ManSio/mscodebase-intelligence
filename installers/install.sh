#!/bin/bash
set -e

echo "=========================================="
echo " MSCodebase Intelligence - Установка"
echo "=========================================="
echo

# 1. Проверка наличия requirements.txt
if [ ! -f "requirements.txt" ]; then
    echo "❌ Файл requirements.txt не найден в текущей директории!"
    exit 1
fi

# 2. Проверка Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не найден!"
    echo "Установите Python 3.10+:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  macOS: brew install python"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python версия: $PYTHON_VERSION"

# 3. Создание виртуального окружения
echo
echo "[1/4] Создание виртуального окружения..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 4. Обновление pip
echo "[2/4] Обновление pip..."
pip install --upgrade pip --quiet

# 5. Установка зависимостей
echo "[3/4] Установка зависимостей..."
if ! pip install -r requirements.txt; then
    echo "❌ Ошибка установки зависимостей!"
    exit 1
fi

# 6. Настройка Zed IDE
echo "[4/4] Настройка Zed IDE..."
echo
echo "Выберите режим установки:"
echo "  1. Только для текущего проекта (рекомендуется)"
echo "  2. Глобально для всех проектов"
echo
read -p "Ваш выбор (1/2): " MODE

if [ "$MODE" = "2" ]; then
    echo "Настройка глобальной конфигурации..."
    python3 -m src.main --install-global
else
    echo "Настройка локальной конфигурации..."
    python3 -m src.main --install
fi

if [ $? -ne 0 ]; then
    echo
    echo "❌ Ошибка при настройке Zed IDE. Убедитесь, что Zed запущен хотя бы один раз."
    exit 1
fi

echo
echo "=========================================="
echo " ✅ Установка завершена успешно!"
echo
echo " Следующие шаги:"
echo " 1. Перезапустите Zed IDE."
echo " 2. Откройте проект в Zed."
echo " 3. Откройте Agent Panel (Ctrl+Shift+P -> Agent)."
echo " 4. Спросите: \"Найди файлы про роутинг\""
echo "=========================================="
