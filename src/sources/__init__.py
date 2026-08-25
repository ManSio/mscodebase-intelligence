"""SOURCE LAYER (ТЗ §1, §2) — откуда берётся код.

    src/sources/__init__.py     — этот пакет
    src/sources/local_fs/       — LocalFsSource (локальный путь; Фаза 1)
    src/sources/git_url/        — GitUrlSource (Фаза 2, plan: UNIVERSAL_ENGINE_PLAN)
    src/sources/upload/         — UploadSource (Фаза 2)

Протокол WorkspaceSource + FileChangeEvent живёт в core-интерфейсах
(src/core/interfaces/workspace_source.py, паттерн IEmbedder) — core
объявляет интерфейс, этот слой его реализует.

Направление зависимостей: source → core (вниз по схеме
ADAPTER → TRANSPORT → SOURCE → CORE). Source-слой НЕ импортирует adapters/.
"""
