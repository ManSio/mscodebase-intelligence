"""Зависимости плагина (Фаза 4, план §5.1) — pre-check перед установкой.

Скрытая RCE-поверхность: `import requests` в плагине исполняет и код requests.
Здесь — лёгкий офлайн-валидатор манифестных пинов (обязательный `==`):
  - каждый dependency обязан быть пином `name==ver` (как политика движка §5.19);
  - непрошитый (range/без версии) → warning (не блок: сервер не должен падать);
  - полный pip-audit-скан на установке — остаётся на инсталлятор (выход в registry).
"""
from __future__ import annotations

import re
from typing import List

_PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^=]+$")


class DependencyWarning:
    def __init__(self, dependency: str, message: str):
        self.dependency = dependency
        self.message = message

    def __repr__(self):
        return f"DependencyWarning({self.dependency!r}: {self.message})"

    def __iter__(self):
        yield self.dependency
        yield self.message


def validate_dependencies(dependencies: List[str]) -> List[DependencyWarning]:
    """Проверяет манифестные зависимости. Возвращает список warning'ов.

    Каждый пункт обязан быть пином `name==ver`. Непринятые форматы — warning
    (не отказ): блокировать загрузку плагина пин-политикой можно позже, когда
    зависимости действительно резолвятся (инсталлятор).
    """
    warns: List[DependencyWarning] = []
    for dep in dependencies or []:
        d = dep.strip()
        if not d:
            continue
        if not _PIN_RE.match(d):
            warns.append(DependencyWarning(
                d,
                "непрошитый dependency (нет `==`); резолв/аудит на инсталляторе "
                "(pip-audit §5.1). Диапазон/голость = скрытая RCE-поверхность.",
            ))
    return warns
