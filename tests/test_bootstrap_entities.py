# -*- coding: utf-8 -*-
"""Tests для bootstrap_entities.detect_entities (детектор data structures)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.bootstrap_entities import (
    KIND_DATACLASS,
    KIND_NAMEDTUPLE,
    detect_entities,
)


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_detects_dataclass_and_namedtuple(tmp_path):
    _write(
        tmp_path,
        "src/models.py",
        "from dataclasses import dataclass\n"
        "from typing import NamedTuple\n\n"
        "@dataclass\n"
        "class User:\n"
        "    id: int\n"
        "    name: str\n\n"
        "class Point(NamedTuple):\n"
        "    x: float\n"
        "    y: float\n",
    )

    stats = detect_entities(tmp_path)

    assert stats.files_scanned == 1
    assert stats.classes_total == 2
    assert stats.dataclass_count == 1
    assert stats.namedtuple_count == 1
    assert stats.entities_found == 2
    assert stats.errors == []

    kinds = {e.name: e.kind for e in stats.entities}
    assert kinds == {"User": KIND_DATACLASS, "Point": KIND_NAMEDTUPLE}

    user = next(e for e in stats.entities if e.name == "User")
    assert user.file_path.replace("\\", "/").endswith("src/models.py")
    assert user.line == 5
    assert user.fields == ["id", "name"]


def test_dataclass_call_and_attribute_forms(tmp_path):
    """@dataclass(frozen=True) и @dataclasses.dataclass тоже детектируются."""
    _write(
        tmp_path,
        "src/m2.py",
        "import dataclasses\n"
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True)\n"
        "class Frozen:\n"
        "    a: int\n\n"
        "@dataclasses.dataclass\n"
        "class AttrDec:\n"
        "    b: str\n\n"
        "@dataclasses.dataclass(slots=True)\n"
        "class AttrCall:\n"
        "    c: bool\n",
    )

    stats = detect_entities(tmp_path)

    assert stats.dataclass_count == 3
    assert {e.name for e in stats.entities} == {"Frozen", "AttrDec", "AttrCall"}


def test_plain_classes_and_open_table_not_entities(tmp_path):
    """Классы без сигналов и db.open_table(...) — НЕ сущности (регекс-шум)."""
    _write(
        tmp_path,
        "src/m3.py",
        "class Service:\n"
        "    def run(self):\n"
        "        pass\n\n"
        "def query(db):\n"
        "    table = db.open_table('codebase_chunks')\n"
        "    return table.count_rows()\n",
    )

    stats = detect_entities(tmp_path)

    assert stats.classes_total == 1  # Service — класс, но без сигнала
    assert stats.entities_found == 0
    assert stats.open_table_calls == 1


def test_typing_namedtuple_attribute_base(tmp_path):
    _write(
        tmp_path,
        "src/m4.py",
        "import typing\n\nclass C(typing.NamedTuple):\n    x: int\n",
    )

    stats = detect_entities(tmp_path)

    assert stats.namedtuple_count == 1
    assert stats.entities[0].fields == ["x"]


def test_aliased_namedtuple_not_resolved(tmp_path):
    """Алиас `import NamedTuple as NT` НЕ резолвится — документированное ограничение."""
    _write(
        tmp_path,
        "src/m5.py",
        "from typing import NamedTuple as NT\n\nclass NotDetected(NT):\n    x: int\n",
    )

    stats = detect_entities(tmp_path)

    assert stats.namedtuple_count == 0
    assert stats.entities_found == 0


def test_broken_file_collected_as_error(tmp_path):
    _write(tmp_path, "src/good.py", "@dataclass\nclass OK:\n    a: int\n")
    _write(tmp_path, "src/broken.py", "def f(:\n")

    stats = detect_entities(tmp_path)

    assert stats.dataclass_count == 1
    assert len(stats.errors) == 1
    assert "broken" in stats.errors[0]


def test_missing_src_dir_returns_empty(tmp_path, tmp_path_factory):
    empty = tmp_path_factory.mktemp("no_src")

    stats = detect_entities(empty)

    assert stats.files_scanned == 0
    assert stats.entities_found == 0


def test_custom_src_dir(tmp_path):
    _write(
        tmp_path,
        "pkg/models.py",
        "@dataclass\nclass Item:\n    qty: int\n",
    )

    stats = detect_entities(tmp_path, src_dir=tmp_path / "pkg")

    assert stats.dataclass_count == 1
    assert stats.entities[0].file_path.replace("\\", "/").endswith("pkg/models.py")


def test_auto_detect_core_layout(tmp_path):
    """Нет src/ — детектор сам находит core/ (раскладка gemma_agent)."""
    _write(
        tmp_path,
        "core/models.py",
        "@dataclass\nclass User:\n    id: int\n",
    )
    _write(tmp_path, "tests/test_models.py", "def test_x():\n    pass\n")

    stats = detect_entities(tmp_path)

    assert stats.files_scanned == 1
    assert stats.dataclass_count == 1
    assert stats.src_root is not None
    assert Path(stats.src_root).name == "core"


def test_auto_detect_project_name_dir(tmp_path):
    """Пакет с именем проекта в корне (httpbin-стиль)."""
    proj = tmp_path / "myproj"
    _write(proj, "myproj/app.py", "@dataclass\nclass Item:\n    qty: int\n")

    stats = detect_entities(proj)

    assert stats.dataclass_count == 1
    assert stats.src_root is not None
    assert Path(stats.src_root).name == "myproj"


def test_auto_detect_statistical_fallback(tmp_path):
    """Без известных раскладок — побеждает каталог с максимумом .py,
    кроме tests/docs (там .py обычно больше = ложный выбор)."""
    _write(tmp_path, "widgets/a.py", "@dataclass\nclass A:\n    x: int\n")
    _write(tmp_path, "widgets/b.py", "@dataclass\nclass B:\n    y: int\n")
    _write(tmp_path, "docs/conf.py", "x = 1\n")
    for i in range(6):
        _write(tmp_path, f"tests/test_{i}.py", "def test_x():\n    pass\n")

    stats = detect_entities(tmp_path)

    assert stats.src_root is not None
    assert Path(stats.src_root).name == "widgets"
    assert stats.dataclass_count == 2


def test_env_src_dir_overrides_auto(tmp_path, monkeypatch):
    """MSCODEBASE_BOOTSTRAP_SRC_DIR задаёт корень без src/ и без раскладок."""
    _write(
        tmp_path,
        "custom/entities.py",
        "@dataclass\nclass Custom:\n    a: int\n",
    )
    _write(tmp_path, "core/other.py", "@dataclass\nclass Other:\n    b: int\n")
    monkeypatch.setenv("MSCODEBASE_BOOTSTRAP_SRC_DIR", str(tmp_path / "custom"))

    stats = detect_entities(tmp_path)

    assert stats.dataclass_count == 1
    assert stats.entities[0].name == "Custom"


def test_explicit_src_dir_beats_env(tmp_path, monkeypatch):
    """Явный src_dir — приоритет над env и над автодетектом."""
    _write(
        tmp_path,
        "manual/models.py",
        "@dataclass\nclass Manual:\n    a: int\n",
    )
    _write(
        tmp_path,
        "envdir/models.py",
        "@dataclass\nclass FromEnv:\n    b: int\n",
    )
    monkeypatch.setenv("MSCODEBASE_BOOTSTRAP_SRC_DIR", str(tmp_path / "envdir"))

    stats = detect_entities(tmp_path, src_dir=tmp_path / "manual")

    assert stats.dataclass_count == 1
    assert stats.entities[0].name == "Manual"
    assert stats.src_root.replace("\\", "/").endswith("/manual")


def test_missing_everything_returns_none_src_root(tmp_path_factory):
    """Ни src/, ни раскладок, ни .py-файлов → src_root=None, пустой прогон."""
    empty = tmp_path_factory.mktemp("totally_empty")

    stats = detect_entities(empty)

    assert stats.src_root is None
    assert stats.files_scanned == 0
    assert stats.entities_found == 0
