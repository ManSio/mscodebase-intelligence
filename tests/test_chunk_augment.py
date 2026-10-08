"""Phase 1 (E26): file-level chunk augmentation — unit + wiring.

- Template exactness is pinned (frozen AUG_TEMPLATE): FILE/SYMBOLS/DOC order,
  dedup, 500-char doc cap, backslash normalization, empty cases.
- Wiring: flag OFF (default) leaves parse output byte-identical;
  flag ON prefixes every chunk (AST and fallback share the choke point).
- Formula guard lives in experiments (E26 exact TF*IDF); here we pin the INPUT.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.indexing.chunk_augment import (  # noqa: E402
    augment_enabled,
    build_file_prefix,
    module_doc,
    top_level_defs,
)

BODY = '''"""Module docstring here."""

import os


class Foo:
    pass


def bar(x):
    return x


def bar(y):
    return y
'''


def test_top_level_defs_order_and_dedup():
    assert top_level_defs(BODY) == ["Foo", "bar"]


def test_top_level_defs_empty():
    assert top_level_defs("x = 1\n") == []


def test_module_doc_capped_and_folded():
    assert module_doc(BODY) == "Module docstring here."
    assert module_doc("x = 1\n") == ""
    long_doc = '"""' + "word " * 500 + '"""\nx=1\n'
    assert len(module_doc(long_doc)) == 500


def test_build_file_prefix_exact():
    assert build_file_prefix("a\\b.py", BODY) == (
        "FILE: a/b.py\nSYMBOLS: Foo bar\nDOC: Module docstring here.\n"
    )


def test_build_file_prefix_empty_case():
    assert build_file_prefix("x.py", "x = 1\n") == "FILE: x.py\nSYMBOLS: \nDOC: \n"


def test_flag_default_off_and_parsing(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_AUGMENT_CHUNKS", raising=False)
    assert augment_enabled() is False


def test_flag_on_values(monkeypatch):
    for v in ("1", "true", "yes", "TRUE"):
        monkeypatch.setenv("MSCODEBASE_AUGMENT_CHUNKS", v)
        assert augment_enabled() is True
    for v in ("0", "false", "", "no"):
        monkeypatch.setenv("MSCODEBASE_AUGMENT_CHUNKS", v)
        assert augment_enabled() is False


def _make_parser(tmp_path):
    from src.core.indexing.index_parser import IndexParser

    pm = SimpleNamespace(get_safe_path=lambda p: Path(p))
    return IndexParser(parser=None, path_manager=pm, project_path=tmp_path)


def test_wiring_off_leaves_texts_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_AUGMENT_CHUNKS", raising=False)
    f = tmp_path / "m.py"
    f.write_text(BODY, encoding="utf-8")
    parsed = _make_parser(tmp_path).parse_file(f, "m.py")
    assert parsed is not None and parsed["chunk_texts"]
    assert all("FILE:" not in t for t in parsed["chunk_texts"])
    assert all("FILE:" not in t for t in parsed["chunk_texts_full"])


def test_wiring_on_prefixes_every_chunk(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_AUGMENT_CHUNKS", "true")
    f = tmp_path / "m.py"
    f.write_text(BODY, encoding="utf-8")
    parsed = _make_parser(tmp_path).parse_file(f, "m.py")
    assert parsed is not None and parsed["chunk_texts"]
    for t in parsed["chunk_texts"]:
        assert t.startswith("FILE: m.py\nSYMBOLS: Foo bar\nDOC: Module docstring here.\n")
    for t in parsed["chunk_texts_full"]:
        assert t.startswith("FILE: m.py\nSYMBOLS: Foo bar\nDOC: Module docstring here.\n")


def test_wiring_on_off_differ_only_by_prefix(tmp_path, monkeypatch):
    f = tmp_path / "m.py"
    f.write_text(BODY, encoding="utf-8")
    monkeypatch.delenv("MSCODEBASE_AUGMENT_CHUNKS", raising=False)
    off = _make_parser(tmp_path).parse_file(f, "m.py")
    monkeypatch.setenv("MSCODEBASE_AUGMENT_CHUNKS", "true")
    on = _make_parser(tmp_path).parse_file(f, "m.py")
    assert len(off["chunk_texts"]) == len(on["chunk_texts"])
    for t_off, t_on in zip(off["chunk_texts"], on["chunk_texts"]):
        assert t_on.endswith(t_off)
