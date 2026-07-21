"""Smoke-test: проверяет, что DI-контейнер создаётся без ошибок (multi-window).

Раньше вызывал create_mcp_server() (блокирующий stdio), что ломалось
под pytest. Теперь тестируем только DI + ProjectIndexerRegistry.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.core.indexing.file_guard import FileGuard
from src.core.di_container import create_service_collection, ProjectRootKey
from src.core.indexing.project_indexer_registry import (
    ProjectIndexerRegistry,
    get_global_registry,
    reset_global_registry,
)
from src.mcp.tools.base import resolve_indexer_for_request


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

    # 2. Тест DI-контейнера (multi-window, INC-6BCB)
    print("⏳ Инициализация DI-контейнера...")
    reset_global_registry()
    services = create_service_collection(project_path)
    registry: ProjectIndexerRegistry = services.resolve(ProjectIndexerRegistry)
    assert registry is not None, "ProjectIndexerRegistry не зарегистрирован"
    assert services.resolve(ProjectRootKey) is not None, "ProjectRootKey не зарегистрирован"
    print("✅ DI-контейнер + ProjectIndexerRegistry созданы успешно!")

    # 3. Резолв per-project Indexer (multi-window)
    indexer = resolve_indexer_for_request(
        services, explicit_project_root=str(project_path),
    )
    assert indexer.project_path.resolve() == project_path.resolve()
    print(f"✅ resolve_indexer_for_request → {indexer.project_path.name}")


if __name__ == "__main__":
    test_setup()
