"""Guard: JS/TS-символы реально извлекаются (замер 2026-11-16).

Повод: «в JS-проектах мало узлов графа». Измерено на живых индексах:
MSPortfolio — 82 кодовых файла в индексе → 425 символьных узлов
(113 Function, 66 Interface, 241 Variable); ghost-rovers — 8 файлов → 327 узлов
(114 Function). Число «665 файлов» в chunks.db — это документы/конфиги, а не код.

Этот тест держит сам механизм: если парсер перестанет отдавать символы для
.js/.ts/.tsx, тест покраснеет.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.indexing.parser import CodeParser

JS_SOURCE = """\
import { helper } from "./util.js";

export function buildReport(input) {
  return helper(input);
}

export function loadData(path) {
  return path;
}

export class Reporter {
  render(data) {
    return String(data);
  }
}

const formatRow = (row) => row;
"""

TS_SOURCE = """\
export interface Order {
  id: number;
}

export function placeOrder(order: Order): boolean {
  return order.id > 0;
}
"""


@pytest.fixture(scope="module")
def parser() -> CodeParser:
    return CodeParser()


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("mod.js", JS_SOURCE, {"buildReport", "loadData", "Reporter"}),
        ("mod.ts", TS_SOURCE, {"placeOrder", "Order"}),
    ],
)
def test_js_and_ts_definitions_are_extracted(parser, tmp_path: Path, name, source, expected):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")

    definitions = parser.extract_definitions_scm(path)
    names = {d.get("name") for d in definitions}

    assert expected <= names, f"{name}: не найдено {expected - names}"


def test_parse_file_returns_symbols_for_js(parser, tmp_path: Path):
    """parse_file — путь, которым пользуется индексация (_ast_symbols)."""
    path = tmp_path / "app.js"
    path.write_text(JS_SOURCE, encoding="utf-8")

    chunks, symbols = parser.parse_file(path)

    assert chunks, "JS-файл обязан дать AST-чанки"
    assert symbols, "символы обязаны попасть в SymbolIndex"
    symbol_names = {
        (s.get("name") if isinstance(s, dict) else getattr(s, "symbol", None))
        for s in symbols
    }
    assert {"buildReport", "loadData"} <= symbol_names
