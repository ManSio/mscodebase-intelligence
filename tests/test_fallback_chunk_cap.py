"""Кап fallback-чанков на файл (MSCODEBASE_MAX_FALLBACK_CHUNKS).

Данные (JSON) индексируются fallback-веткой и давали до 1 146 чанков на файл.
Кап ограничивает их, не трогая AST-чанки кода (там чанк = определение символа).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.indexing.index_parser import IndexParser
from src.core.indexing.parser import CodeParser
from src.sources.local_fs import LocalFsSource


def _parser(project: Path) -> IndexParser:
    source = LocalFsSource(project)
    return IndexParser(
        parser=CodeParser(),
        path_manager=source.path_manager,
        project_path=project,
    )


def _write_json(path: Path, entries: int = 400) -> None:
    payload = {
        f"dataset_{i}": {"prompt": f"question {i}", "answer": f"answer {i} " * 20}
        for i in range(entries)
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_fallback_chunks_are_capped_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MAX_FALLBACK_CHUNKS", raising=False)
    project = tmp_path
    target = project / "runtime.json"
    _write_json(target)

    parsed = _parser(project).parse_file(
        full_path=target, rel_path_str="runtime.json"
    )

    assert parsed is not None
    assert len(parsed["chunk_texts"]) == 20
    assert len(parsed["chunk_texts_full"]) == 20
    assert len(parsed["chunk_metadatas"]) == 20
    marker = "fallback chunks truncated"
    assert marker in parsed["chunk_texts"][-1], "обрезка должна быть видна в выдаче"
    assert marker in parsed["chunk_texts_full"][-1]


def test_cap_zero_means_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_MAX_FALLBACK_CHUNKS", "0")
    project = tmp_path
    target = project / "runtime.json"
    _write_json(target)

    parsed = _parser(project).parse_file(
        full_path=target, rel_path_str="runtime.json"
    )

    assert parsed is not None
    assert len(parsed["chunk_texts"]) > 20
    assert "fallback chunks truncated" not in "".join(parsed["chunk_texts"])


def test_cap_does_not_touch_ast_code_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_MAX_FALLBACK_CHUNKS", "2")
    project = tmp_path
    target = project / "many.py"
    body = "\n\n".join(f"def f{i}():\n    return {i}" for i in range(12))
    target.write_text(body + "\n", encoding="utf-8")

    parsed = _parser(project).parse_file(full_path=target, rel_path_str="many.py")

    assert parsed is not None
    assert len(parsed["chunk_texts"]) > 2, "AST-чанки капом не режутся"
    assert not any(
        "Scope: fallback" in t for t in parsed["chunk_texts"]
    ), "файл не должен падать в fallback"


def test_bad_value_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_MAX_FALLBACK_CHUNKS", "много")
    project = tmp_path
    target = project / "runtime.json"
    _write_json(target)

    parsed = _parser(project).parse_file(
        full_path=target, rel_path_str="runtime.json"
    )

    assert parsed is not None
    assert len(parsed["chunk_texts"]) == 20


def test_negative_value_keeps_the_cap_on(tmp_path, monkeypatch):
    """-1 — опечатка, а не «выключить»: только явный 0 снимает кап."""
    monkeypatch.setenv("MSCODEBASE_MAX_FALLBACK_CHUNKS", "-1")
    project = tmp_path
    target = project / "runtime.json"
    _write_json(target)

    parsed = _parser(project).parse_file(
        full_path=target, rel_path_str="runtime.json"
    )

    assert parsed is not None
    assert len(parsed["chunk_texts"]) == 20
