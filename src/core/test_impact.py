"""test_impact.py — статическое предсказание blast radius изменения (Фаза 1).

"Агент вносит изменение и точно знает, что будет": перед любым прогоном,
по списку изменённых файлов (и опционально символам) детерминированно
вычисляется:
  1. affected_tests  — тест-файлы, которые импортируют изменённые модули
     (префиксный матч: src.core.a покрывает src.core.a.b) или содержат
     имя изменённого файла/символа;
  2. affected_gates   — гейты, которые сканируют изменённые зоны
     (architecture_linter / check_layer_boundaries / ruff);
  3. risk_level       — "low" | "medium" | "high" по числу затронутых тестов.

Чистый AST/refscan: БЕЗ зависимости от live-индекса (LanceDB) — как
architecture_linter и tests/test_architecture_invariants.py. Детерминизм —
то, ради чего это делается: предиктор обязан давать одинаковый ответ
на одинаковом дереве, иначе "точно знать что будет" превращается в лотерею.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set

__all__ = [
    "module_of",
    "referenced_modules",
    "predict_affected_tests",
    "affected_gates",
    "risk_level",
]

# Слово-граница после имени модуля: "src.core.a" матчит "src.core.a.b"
# (под-импорт), но НЕ "src.core.a_legacy" (после 'a' идёт '_' — word char).
_MODULE_BOUNDARY = r"(?=$|[.\W])"


def _rel(path, repo_root: Path):
    """Путь относительно repo_root: абсолютный — через relative_to; относительный — как есть.

    resolve() для относительных путей привязывает их к CWD, а не к repo_root
    (await: тесты передают 'src/core/a.py' при корне tmp_path) — здесь этого
    не происходит, предиктор детерминирован независимо от CWD.
    """
    p = Path(path)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return None
    return p


def module_of(path: Path, repo_root: Path) -> str:
    """'src/core/a.py' → 'src.core.a' (работает и с absolute, и с relative)."""
    rel = _rel(path, repo_root)
    if rel is None:
        return ""
    return ".".join(rel.with_suffix("").parts)


def referenced_modules(file_path: Path, repo_root: Path) -> Set[str]:
    """Абсолютные имена модулей, которые файл импортирует (AST, absolute+relative).

    SyntaxError-файлы возвращают пустое множество (не роняем предиктор —
    сам pytest покажет синтаксис как fail).
    """
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    mod = module_of(file_path, repo_root)
    pkg = mod.rsplit(".", 1)[0] if "." in mod else mod
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: from .x / from ..y — резолвим через пакет
                parts = pkg.split(".") if pkg else []
                up = node.level - 1
                if up > 0:
                    parts = parts[:-up] if up <= len(parts) else []
                base = ".".join(parts)
                m = f"{base}.{node.module}" if base and node.module else (base or (node.module or ""))
            else:
                m = node.module or ""
            if m.startswith("."):  # защита от кривого резолва
                continue
            out.add(m)
    return out


def predict_affected_tests(
    changed_files: List[str],
    repo_root: str,
    symbols: List[str] | None = None,
    tests_dir: str = "tests",
) -> Dict:
    """Изменённые файлы/символы → затронутые тест-файлы.

    Правило затронутости теста T:
      - T импортирует изменённый модуль M (или его под-модуль), ИЛИ
      - имя изменённого файла (test-коллеги) встречается в T, ИЛИ
      - переданный символ встречается в T (слово-граница имени модуля).

    Returns:
        {"targets": [...], "affected_tests": [относительные пути], "risk_level": ...}
    """
    root = Path(repo_root).resolve()
    targets: Set[str] = set()
    for f in changed_files:
        rel = _rel(f, root)
        if rel is None:
            continue  # файл вне репо (напр. системный) — вне скоупа предиктора
        targets.add(module_of(rel, root))
        targets.add(rel.stem)
    if symbols:
        targets.update(symbols)

    affected: List[str] = []
    tdir = root / tests_dir
    if tdir.is_dir():
        for tf in sorted(tdir.rglob("test_*.py")):
            text = tf.read_text(encoding="utf-8", errors="replace")
            refs = referenced_modules(tf, root)
            if _hits_target(refs, text, targets):
                try:
                    affected.append(str(tf.relative_to(root)).replace(chr(92), "/"))
                except ValueError:
                    affected.append(str(tf))

    return {
        "targets": sorted(targets),
        "affected_tests": affected,
        "risk_level": risk_level(len(affected)),
    }


def _hits_target(refs: Set[str], text: str, targets: Set[str]) -> bool:
    for t in targets:
        mod_re = re.compile(re.escape(t) + _MODULE_BOUNDARY)
        # import-мачтинг: под-модули (src.core.a cover src.core.a.b)
        if any(mod_re.search(r) for r in refs):
            return True
        if mod_re.search(text):  # имя файла/символа в теле теста
            return True
    return False


def affected_gates(changed_files: List[str], repo_root: str) -> List[str]:
    """Какие гейты сканируют изменённые зоны (для Phase 2 прогона)."""
    root = Path(repo_root).resolve()
    zones = set()
    for f in changed_files:
        rel = _rel(f, root)
        if rel is None:
            continue
        parts = rel.parts
        if parts and parts[0] == "src":
            zones.add("src")
            if len(parts) > 1 and parts[1] == "core":
                zones.add("core")
        if parts and parts[0] == "tests":
            zones.add("tests")
    gates: List[str] = []
    if "core" in zones or "src" in zones:
        gates.append("architecture_linter")
        gates.append("check_layer_boundaries")
    if zones:
        gates.append("ruff")
    return gates


def risk_level(n_affected: int) -> str:
    """Порог риска по числу затронутых тестов (калибруется тестом)."""
    if n_affected == 0:
        return "low"
    if n_affected <= 5:
        return "medium"
    return "high"
