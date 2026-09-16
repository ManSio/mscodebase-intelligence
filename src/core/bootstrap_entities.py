# -*- coding: utf-8 -*-
"""Bootstrap Step B1: статический детектор data structures (сущностей) проекта.

Цель (KNOWN_ISSUES, FEATURE Bootstrap Pipeline): для нового проекта найти
чистые структуры данных по AST-сигналам `@dataclass` и наследования `NamedTuple`,
НЕ через регекс-поиск. Регекс `Table(` даёт 90% шума (это вызовы LanceDB
`db.open_table(...)`, а не SQL-схемы); AST-детектор по классам их априори не видит.

Роль в bootstrap (уточнена Exp 9, 2026-09-16): статический слой НЕ заменяет
dynamic trace (recall union 70% < 100% dynamic на linked); его место —
fallback для динамически-пустых тестов (88/176 мок-тестов имеют стат.
кандидатов) и pre-filter ранжирования. Сам по себе отчёт о сущностях —
вход для `mscodebase bootstrap` (Шаг 3) и контекст для LLM.

Соглашения (как в bootstrap_tests.py):
- Только надёжные AST-сигналы: декоратор dataclass (Name/Call/Attribute) и база
  NamedTuple (Name/Attribute). Pydantic/TypedDict в репо отсутствуют — не
  детектируются.
- Не резолвим импорты (`from typing import NamedTuple as NT` вне скоупа).
- Read-only, идемпотентно, без shared state — concurrency-safe по построению.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SRC_DIR_NAME = "src"

KIND_DATACLASS = "dataclass"
KIND_NAMEDTUPLE = "namedtuple"

_IGNORED_DIRS = {".venv", "venv", ".git", "__pycache__", "node_modules", "site-packages"}


@dataclass
class EntityShape:
    """Одна найденная data structure."""

    name: str
    kind: str  # KIND_DATACLASS | KIND_NAMEDTUPLE
    file_path: str  # abs-путь к файлу (в Windows — backslashes)
    line: int  # 1-based строка объявления класса
    fields: List[str]  # аннотированные атрибуты класса

    def as_dict(self) -> Dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "line": self.line,
            "fields": self.fields,
        }


@dataclass
class EntitiesBootstrapStats:
    """Счётчики прогона детектора сущностей."""

    files_scanned: int = 0
    classes_total: int = 0
    entities_found: int = 0
    dataclass_count: int = 0
    namedtuple_count: int = 0
    # Вызовы db.open_table(...) — подтверждение, что регекс-шум Table( НЕ
    # интерпретируется как сущности (это не классы).
    open_table_calls: int = 0
    errors: list = field(default_factory=list)
    entities: List[EntityShape] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "files_scanned": self.files_scanned,
            "classes_total": self.classes_total,
            "entities_found": self.entities_found,
            "dataclass_count": self.dataclass_count,
            "namedtuple_count": self.namedtuple_count,
            "open_table_calls": self.open_table_calls,
            "errors": self.errors,
            "entities": [e.as_dict() for e in self.entities],
        }


def _is_dataclass_decorator(node: ast.expr) -> bool:
    """Декоратор — dataclass в формах Name (@dataclass), Call (@dataclass(k=...)),
    Attribute (@dataclasses.dataclass / dataclasses.dataclass(k=...))."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == "dataclass"
    if isinstance(target, ast.Attribute):
        return target.attr == "dataclass"
    return False


def _is_namedtuple_base(node: ast.expr) -> bool:
    """База класса — NamedTuple: Name (class C(NamedTuple)) или
    Attribute (class C(typing.NamedTuple)). collections.namedtuple — это
    фабрика-функция, не класс, потому сюда не попадает."""
    if isinstance(node, ast.Name):
        return node.id == "NamedTuple"
    if isinstance(node, ast.Attribute):
        return node.attr == "NamedTuple"
    return False


def _class_fields(class_node: ast.ClassDef) -> List[str]:
    """Аннотированные атрибуты класса (поля структуры данных)."""
    fields: List[str] = []
    for stmt in class_node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.append(stmt.target.id)
    return fields


def _open_table_calls_in(tree: ast.AST) -> int:
    """Число вызовов <expr>.open_table(...) в дереве — счётчик регекс-шума."""
    count = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open_table"
        ):
            count += 1
    return count


def detect_entities(
    project_root: Path,
    src_dir: Optional[Path] = None,
    ignore_dirs: Optional[set] = None,
) -> EntitiesBootstrapStats:
    """Поиск data structures (dataclass/NamedTuple) в Python-файлах проекта.

    Args:
        project_root: корень проекта (резолвится).
        src_dir: каталог исходников (default project_root/src).
        ignore_dirs: имена каталогов, пропускаемых при обходе
            (default — стандартный набор .venv/venv/.git/etc).

    Returns:
        EntitiesBootstrapStats: счётчики + список EntityShape.
    """
    root = Path(project_root).resolve()
    src_root = (src_dir or root / SRC_DIR_NAME).resolve()
    ignored = set(ignore_dirs) if ignore_dirs is not None else set(_IGNORED_DIRS)

    stats = EntitiesBootstrapStats()

    if not src_root.is_dir():
        return stats

    for path in sorted(src_root.rglob("*.py")):
        if any(part in ignored for part in path.parts):
            continue
        stats.files_scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            stats.errors.append(f"{path}: {type(exc).__name__}: {exc}")
            continue

        stats.open_table_calls += _open_table_calls_in(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            stats.classes_total += 1

            entity = None
            if any(_is_dataclass_decorator(d) for d in node.decorator_list):
                entity = EntityShape(
                    name=node.name,
                    kind=KIND_DATACLASS,
                    file_path=str(path),
                    line=node.lineno,
                    fields=_class_fields(node),
                )
            elif any(_is_namedtuple_base(b) for b in node.bases):
                entity = EntityShape(
                    name=node.name,
                    kind=KIND_NAMEDTUPLE,
                    file_path=str(path),
                    line=node.lineno,
                    fields=_class_fields(node),
                )

            if entity is None:
                continue
            stats.entities_found += 1
            if entity.kind == KIND_DATACLASS:
                stats.dataclass_count += 1
            else:
                stats.namedtuple_count += 1
            stats.entities.append(entity)

    return stats
