import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.core.file_guard import FileGuard
from src.mcp.server import create_mcp_server


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
    create_mcp_server()
    print("✅ Компоненты созданы успешно!")


if __name__ == "__main__":
    test_setup()
