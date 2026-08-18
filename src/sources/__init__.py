"""SOURCE LAYER (ТЗ §1, §2) — откуда берётся код.

    src/sources/base.py        — WorkspaceSource Protocol + FileChangeEvent
    src/sources/local_fs/      — LocalFsSource (локальный путь; Фаза 1)
    src/sources/git_url/       — GitUrlSource (Фаза 2, plan: UNIVERSAL_ENGINE_PLAN)
    src/sources/upload/        — UploadSource (Фаза 2)

Направление зависимостей: source → core (вниз по схеме
ADAPTER → TRANSPORT → SOURCE → CORE). Source-слой НЕ импортирует adapters/.
"""
