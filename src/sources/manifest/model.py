"""Модель манифестной записи (Backlog B-1, ADR-0005 scaling).

Нормализованная модель ManifestEntry по спеке B-1 (детали — в приватных
research-документах; публичный контракт — archive в ADR-0005 и тестовый корпус).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ManifestEntry:
    ecosystem: str  # "python" | "npm" | "go" | "cargo" | "maven" | "nuget" | "composer" | "gem"
    name: str       # нормализованное имя (python: PEP 503; npm: lowercase; ...)
    spec: str       # сырой specifier строкой (семантика НЕ парсится в фазе 1)
    kind: str       # "manifest" | "lockfile" | "workspace"
    source: str     # относительный путь файла
    line: int = 0


_PEP503_RE = re.compile(r"[-_.]+")


def normalize_python(name: str) -> str:
    """Каноническое имя PyPI (PEP 503): lowercase, [-_.]+ -> '-', strip пробелы."""
    return _PEP503_RE.sub("-", (name or "").strip().lower())


def normalize_npm(name: str) -> str:
    """npm-имена уже lowercase; лёгкий trim."""
    return (name or "").strip().lower()


def normalize_dotted(name: str) -> str:
    """Точечное имя (го/композер-подобное) — просто trim."""
    return (name or "").strip()
