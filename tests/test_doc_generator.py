"""DocGenerator: skip build-каталогов + .gitignore (инцидент infrawise 2026-08-16).

Регрессия: dist/context/scanner.py (байт-в-байт дубль src/context/scanner.py)
попадал в docs-выдачу, потому что собственный walk DocGenerator имел неполный
skip_dirs и не читал .gitignore. Теперь список синхронизирован с
SymbolIndex._should_skip_dir, плюс уважается .gitignore (как FileGuard).
"""

import re
import shutil
from pathlib import Path

from src.core.doc_generator import DocGenerator

FIXTURE = Path(__file__).parent / "fixtures" / "sample_module.py"


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
    """dist (build-каталог) и .gitignore dir-паттерн не попадают в docs."""
    proj = _project(tmp_path, gitignore="generated/\n")
    md = DocGenerator().generate(str(proj))
    dirs = _dirs(md)
    assert "src" in dirs
    assert not any("dist" in d for d in dirs)  # build-артефакт (skip_dirs)
    assert "generated" not in dirs  # .gitignore dir-паттерн (фикс 2026-08-16)


def test_no_gitignore_still_skips_build_dirs(tmp_path):
    """Без .gitignore build-каталоги всё равно исключаются (skip_dirs)."""
    proj = _project(tmp_path)
    md = DocGenerator().generate(str(proj))
    dirs = _dirs(md)
    assert "src" in dirs
    assert not any("dist" in d for d in dirs)
    # generated/ без .gitignore — обычная директория, попадает
    assert "generated" in dirs


def test_deep_spec_signature_and_description_columns(tmp_path):
    """Deep-spec: таблица содержит Signature+Description, валидна, без сырого `|`."""
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    shutil.copy(FIXTURE, proj / "src" / "sample_module.py")

    md = DocGenerator().generate(str(proj))
    lines = md.splitlines()

    header = next(line for line in lines if line.startswith("| Symbol"))
    assert "Signature" in header and "Description" in header
    header_cols = len(re.findall(r"(?<!\\)\|", header))

    # Каждая строка данных имеет то же число СТРУКТУРНЫХ (неэкранированных)
    # колонок, что и header (экранированные \| внутри ячеек не в счёт).
    for line in lines:
        if line.startswith("|") and "---" not in line and "Symbol" not in line:
            structural = len(re.findall(r"(?<!\\)\|", line))
            assert structural == header_cols, f"колонки расходятся: {line}"

    # Сигнатура и docstring доезжают в таблицу.
    assert "def standalone(value: str) -> str" in md
    assert "Add two integers" in md

    # Пайпы в docstring экранированы (иначе таблица ломается).
    assert "Echo the \\|input\\| value" in md
    assert "Echo the |input| value" not in md
