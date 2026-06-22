import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.append(str(Path(__file__).parent))

from src.core.file_guard import FileGuard
from src.mcp.handler import create_mcp_server


def test_setup():
    project_path = Path(__file__).parent.resolve()
    print(f"🔍 Проверка проекта: {project_path}")

    # 1. Тест FileGuard
    guard = FileGuard(project_path)
    test_file = project_path / "src" / "main.py"
    if guard.is_safe_to_index(test_file):
        print("✅ FileGuard: src/main.py прошел проверку")
    else:
        print(
            "❌ FileGuard: src/main.py заблокирован (проверь .gitignore или расширения)"
        )

    # 2. Тест загрузки сервера (инициализация объектов)
    print("⏳ Инициализация компонентов...")
    create_mcp_server()  # type: ignore[unused-variable]
    print("✅ Компоненты созданы успешно!")

    # Ждём небольшого времени, чтобы фоновая инициализация успела начаться
    import time

    time.sleep(2)

    # Проверяем статус
    from src.mcp.handler import SERVER_READY, SERVER_STATUS_MESSAGE

    print(f"📊 Статус сервера: {SERVER_STATUS_MESSAGE}")
    if SERVER_READY:
        print("✅ Сервер готов к работе!")
    else:
        print("⚠️ Сервер всё ещё инициализируется (это нормально для фоновой загрузки)")


if __name__ == "__main__":
    test_setup()
