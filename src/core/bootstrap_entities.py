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
- Корень исходников НЕ хардкодится в src/: resolve_src_root определяет его
  автоматически (известные раскладки src/lib/core → имя проекта → статистика)
  или через env MSCODEBASE_BOOTSTRAP_SRC_DIR; явный src_dir — всегда приоритет.
- Read-only, идемпотентно, без shared state — concurrency-safe по построению.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SRC_DIR_NAME = "src"

KIND_DATACLASS = "dataclass"
KIND_NAMEDTUPLE = "namedtuple"

# Имена известных раскладок исходников (порядок = приоритет).
# gemma_agent использует core/, libraries/, modules/, httpbin — имя проекта,
# black — src/ — покрываем все реальные случаи, виденные при валидации.
_SRC_CANDIDATE_NAMES = ("src", "lib", "python", "packages", "app", "core", "libraries", "modules")

# Каталоги, которые никогда не являются корнем исходников (исключения в
# статистическом fallback и при проверке известных имён).
_NON_SRC_DIRS = {
    "venv", ".venv", ".git", "__pycache__", "node_modules", "site-packages",
    "tests", "test", "docs", "doc", "scripts", "tools", "examples", "benchmarks",
    "dist", "build", "data", "assets", "config", "backups", "wheels",
}

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

    src_root: Optional[str] = None  # определённый корень исходников (null при пустом прогоне)
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
            "src_root": self.src_root,
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


def resolve_src_root(project_root: Path, src_dir: Optional[Path] = None) -> Optional[Path]:
    """Определить корень исходников проекта (без хардкода только src/).

    Приоритет (детерминированный, первый сработавший):
    1. Явный src_dir (каталог-параметр или каталог-файл).
    2. Переменная окружения ``MSCODEBASE_BOOTSTRAP_SRC_DIR`` (настройка
       через конфиг/.env, по Хартии §9).
    3. Известные имена раскладок исходников (_SRC_CANDIDATE_NAMES): первый
       подкаталог, в котором есть хотя бы один .py.
    4. Каталог с именем проекта (httpbin-стиль: пакет в корне).
    5. Статистический fallback: top-level каталог с наибольшим числом .py,
       исключая _NON_SRC_DIRS и _IGNORED_DIRS.

    Returns:
        Path корня исходников или None, если не найдено ни одного .py.
    """
    root = Path(project_root).resolve()

    if src_dir is not None:
        s = src_dir if src_dir.is_absolute() else (root / src_dir)
        return s.resolve() if s.exists() else None

    env_src = os.environ.get("MSCODEBASE_BOOTSTRAP_SRC_DIR")
    if env_src:
        e = Path(env_src)
        e = e if e.is_absolute() else (root / e)
        if e.exists():
            return e.resolve()

    for name in _SRC_CANDIDATE_NAMES:
        cand = root / name
        if cand.is_dir() and any(cand.rglob("*.py")):
            return cand

    # Каталог с именем проекта в самом проекте (src-layout не обязателен).
    name_dir = root / root.name
    if name_dir.is_dir() and name_dir != root and any(name_dir.rglob("*.py")):
        return name_dir

    # Статистический fallback: максимум .py среди top-level каталогов,
    # кроме заведомо не-исходных (tests/docs/venv...) — там .py обычно больше.
    best: Optional[Path] = None
    best_count = -1
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in _NON_SRC_DIRS or child.name in _IGNORED_DIRS:
            continue
        count = sum(1 for _ in child.rglob("*.py"))
        if count > best_count:
            best, best_count = child, count
    return best if best is not None else None


def detect_entities(
    project_root: Path,
    src_dir: Optional[Path] = None,
    ignore_dirs: Optional[set] = None,
) -> EntitiesBootstrapStats:
    """Поиск data structures (dataclass/NamedTuple) в Python-файлах проекта.

    Args:
        project_root: корень проекта (резолвится).
        src_dir: каталог исходников; если None — автоматически определяется
            через resolve_src_root (в порядке: явный src_dir/env MSCODEBASE_
            BOOTSTRAP_SRC_DIR → известные раскладки src/lib/core → имя проекта
            → статистический максимум .py).
        ignore_dirs: имена каталогов, пропускаемых при обходе
            (default — стандартный набор .venv/venv/.git/etc).

    Returns:
        EntitiesBootstrapStats: счётчики + список EntityShape.
    """
    root = Path(project_root).resolve()
    resolved_src = resolve_src_root(root, src_dir)
    ignored = set(ignore_dirs) if ignore_dirs is not None else set(_IGNORED_DIRS)

    stats = EntitiesBootstrapStats()

    if resolved_src is None or not resolved_src.is_dir():
        stats.src_root = str(resolved_src) if resolved_src is not None else None
        return stats

    src_root = resolved_src
    stats.src_root = str(src_root)

    for path in sorted(src_root.rglob("*.py")):
        if any(part in ignored for part in path.parts):
            continue
        stats.files_scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
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
