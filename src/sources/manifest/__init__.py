"""Многосистемный парсинг манифестов (Backlog B-1, ADR-0005 scaling).

Свои тонкие экстракторы на stdlib: ManifestEntry-модель + диспетчер по имени
файла. `manifest_packages(root) -> Set[str]` — контракт ADR-0005 (расширяем
список источников, не сигнатуру).

Точка входа:
  from src.sources.manifest import manifest_packages, extract_manifest_entries, ManifestEntry
"""
from __future__ import annotations

from src.sources.manifest.extract import (  # noqa: F401
    extract_manifest_entries,
    manifest_packages,
)
from src.sources.manifest.model import (  # noqa: F401
    ManifestEntry,
    normalize_dotted,
    normalize_npm,
    normalize_python,
)

__all__ = [
    "ManifestEntry",
    "extract_manifest_entries",
    "manifest_packages",
    "normalize_dotted",
    "normalize_npm",
    "normalize_python",
]
