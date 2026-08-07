"""Тесты Jupyter .ipynb поддержки (extensions + CodeParser._parse_notebook) — A3."""

import json

from src.core.extensions import INDEX_EXTENSIONS, PARSE_EXTENSIONS


def _make_nb(cells, lang="python"):
    return json.dumps(
        {
            "cells": cells,
            "metadata": {"language_info": {"name": lang}},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )


def test_extensions_include_ipynb():
    assert ".ipynb" in INDEX_EXTENSIONS
    assert ".ipynb" in PARSE_EXTENSIONS


def test_parse_notebook_code_cells(tmp_path):
    from src.core.indexing.parser import CodeParser

    nb = tmp_path / "analysis.ipynb"
    nb.write_text(
        _make_nb(
            [
                {"cell_type": "markdown", "source": ["# Title"]},
                {"cell_type": "code", "source": ["import json\n", "data = json.loads('{}')\n"]},
                {"cell_type": "code", "source": ["def transform(x):\n", "    return x + 1\n"]},
            ]
        ),
        encoding="utf-8",
    )
    parser = CodeParser()
    chunks, symbols = parser.parse_file(nb)
    assert chunks, "notebook не дал чанков"
    assert len(chunks) >= 2
    assert any(str(s.get("name", "")).endswith("transform") for s in symbols)
    assert all(c["file"] == str(nb) for c in chunks)


def test_parse_notebook_top_level_cell_fallback(tmp_path):
    """Cell без функций/классов не теряется — становится чанком code_cell."""
    from src.core.indexing.parser import CodeParser

    nb = tmp_path / "scratch.ipynb"
    nb.write_text(
        _make_nb(
            [
                {"cell_type": "code", "source": ["import numpy as np\n", "x = np.arange(10)\n"]},
            ]
        ),
        encoding="utf-8",
    )
    parser = CodeParser()
    chunks, symbols = parser.parse_file(nb)
    assert chunks
    assert chunks[0]["type"] == "code_cell"
    assert "numpy" in chunks[0]["text"]


def test_parse_notebook_unknown_lang_fallback(tmp_path):
    from src.core.indexing.parser import CodeParser

    nb = tmp_path / "r_nb.ipynb"
    nb.write_text(
        _make_nb([{"cell_type": "code", "source": ["x <- c(1, 2, 3)\n"]}], lang="R"),
        encoding="utf-8",
    )
    parser = CodeParser()
    chunks, symbols = parser.parse_file(nb)
    assert chunks
    assert chunks[0]["type"] == "code_cell"


def test_parse_notebook_invalid_json(tmp_path):
    from src.core.indexing.parser import CodeParser

    nb = tmp_path / "broken.ipynb"
    nb.write_text("{not json", encoding="utf-8")
    parser = CodeParser()
    chunks, symbols = parser.parse_file(nb)
    assert chunks == [] and symbols == []
