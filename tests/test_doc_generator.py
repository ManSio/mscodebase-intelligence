"""DocGenerator: skip build-каталогов + .gitignore (инцидент infrawise 2026-08-16).

Регрессия: dist/context/scanner.py (байт-в-байт дубль src/context/scanner.py)
попадал в docs-выдачу, потому что собственный walk DocGenerator имел неполный
skip_dirs и не читал .gitignore. Теперь список синхронизирован с
SymbolIndex._should_skip_dir, плюс уважается .gitignore (как FileGuard).
"""

import re
from pathlib import Path

from src.core.doc_generator import DocGenerator


def _project(tmp_path: Path, gitignore: str | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    # Дубль build-артефакта (как infrawise: dist == src байт-в-байт)
    (proj / "dist" / "context").mkdir(parents=True)
    (proj / "dist" / "context" / "scanner.py").write_text(
        "def scan():\n    pass\n", encoding="utf-8"
    )
    # Директория, игнорируемая ТОЛЬКО через .gitignore (не build-каталог)
    (proj / "generated").mkdir()
    (proj / "generated" / "gen.py").write_text("def gen():\n    pass\n", encoding="utf-8")
    if gitignore:
        (proj / ".gitignore").write_text(gitignore, encoding="utf-8")
    return proj


def _dirs(md: str) -> set:
    return set(re.findall(r"^# (.+)$", md, re.M))


def test_build_dirs_and_gitignore_excluded(tmp_path):
    """dist (build-каталог) и .gitignore-исключение не попадают в docs.

    Внимание: dir-паттерны .gitignore (generated/) парсером не матчатся
    (KNOWN_ISSUES 2026-08-16 — мёртвая ветка в _match_gitignore_pattern),
    поэтому тут file-level паттерн: механизм .gitignore-уважения проверяется
    честно, а dist закрыт skip_dirs.
    """
    proj = _project(tmp_path, gitignore="generated/gen.py\n")
    md = DocGenerator().generate(str(proj))
    dirs = _dirs(md)
    assert "src" in dirs
    assert not any("dist" in d for d in dirs)  # build-артефакт (skip_dirs)
    assert "generated" not in dirs  # .gitignore (file-level паттерн)


def test_no_gitignore_still_skips_build_dirs(tmp_path):
    """Без .gitignore build-каталоги всё равно исключаются (skip_dirs)."""
    proj = _project(tmp_path)
    md = DocGenerator().generate(str(proj))
    dirs = _dirs(md)
    assert "src" in dirs
    assert not any("dist" in d for d in dirs)
    # generated/ без .gitignore — обычная директория, попадает
    assert "generated" in dirs
