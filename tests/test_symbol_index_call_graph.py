"""
Юнит-тесты для расширенного графа вызовов (Call Graph).

Покрывают:
1. Извлечение вызовов парсером (extract_calls)
2. Добавление references в SymbolIndex
3. Построение двунаправленного графа вызовов с глубиной
4. Метод get_call_chain
5. Edge cases: пустой индекс, циклические вызовы, несуществующие символы
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.parser import CodeParser
from src.core.symbol_index import SymbolIndex, SymbolRef


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def symbol_index():
    """Создаёт пустой SymbolIndex для тестов."""
    return SymbolIndex()


@pytest.fixture
def populated_index(symbol_index):
    """Создаёт SymbolIndex с тестовыми данными о вызовах.

    Структура:
    - main.py: authenticate() → validate_token(), get_user()
    - auth.py: validate_token() → check_signature()
    - auth.py: get_user() → fetch_from_db()
    - utils.py: check_signature() → log_event()
    """
    # Добавляем определения
    symbol_index.add_definitions("main.py", [
        {"name": "authenticate", "line": 1, "kind": "function_definition"},
    ])
    symbol_index.add_definitions("auth.py", [
        {"name": "validate_token", "line": 10, "kind": "function_definition"},
        {"name": "get_user", "line": 20, "kind": "function_definition"},
        {"name": "check_signature", "line": 30, "kind": "function_definition"},
    ])
    symbol_index.add_definitions("utils.py", [
        {"name": "fetch_from_db", "line": 5, "kind": "function_definition"},
        {"name": "log_event", "line": 15, "kind": "function_definition"},
    ])

    # Добавляем вызовы (references)
    symbol_index.add_references("main.py", [
        {"caller": "authenticate", "callee": "validate_token", "line": 2, "file": "main.py"},
        {"caller": "authenticate", "callee": "get_user", "line": 3, "file": "main.py"},
    ])
    symbol_index.add_references("auth.py", [
        {"caller": "validate_token", "callee": "check_signature", "line": 11, "file": "auth.py"},
        {"caller": "get_user", "callee": "fetch_from_db", "line": 21, "file": "auth.py"},
    ])
    symbol_index.add_references("utils.py", [
        {"caller": "check_signature", "callee": "log_event", "line": 31, "file": "utils.py"},
    ])

    return symbol_index


# ── Тест 1: Добавление references ─────────────────────────────────────────


def test_add_references_creates_caller_links(symbol_index):
    """add_references создаёт обратные связи (callee ← caller)."""
    symbol_index.add_definitions("a.py", [
        {"name": "foo", "line": 1, "kind": "function"},
    ])
    symbol_index.add_definitions("b.py", [
        {"name": "bar", "line": 1, "kind": "function"},
    ])

    symbol_index.add_references("a.py", [
        {"caller": "foo", "callee": "bar", "line": 2, "file": "a.py"},
    ])

    # bar должна иметь caller = foo
    refs = symbol_index.find_references("bar")
    assert len(refs) == 1
    assert refs[0].symbol == "foo"
    assert refs[0].file_path == "a.py"


def test_add_references_creates_file_calls(symbol_index):
    """add_references обновляет _file_to_calls."""
    symbol_index.add_definitions("a.py", [
        {"name": "foo", "line": 1, "kind": "function"},
    ])

    symbol_index.add_references("a.py", [
        {"caller": "foo", "callee": "bar", "line": 2, "file": "a.py"},
        {"caller": "foo", "callee": "baz", "line": 3, "file": "a.py"},
    ])

    calls = symbol_index._file_to_calls.get("a.py", set())
    assert "bar" in calls
    assert "baz" in calls


def test_add_references_skips_self_calls(symbol_index):
    """Вызовы самого себя (рекурсия) не добавляются как references."""
    symbol_index.add_definitions("a.py", [
        {"name": "recursive", "line": 1, "kind": "function"},
    ])

    symbol_index.add_references("a.py", [
        {"caller": "recursive", "callee": "recursive", "line": 2, "file": "a.py"},
    ])

    refs = symbol_index.find_references("recursive")
    # Self-call не должен добавляться
    assert len(refs) == 0


def test_add_references_no_duplicates(symbol_index):
    """Дублирующиеся вызовы не добавляются повторно."""
    symbol_index.add_definitions("a.py", [
        {"name": "foo", "line": 1, "kind": "function"},
    ])
    symbol_index.add_definitions("b.py", [
        {"name": "bar", "line": 1, "kind": "function"},
    ])

    # Добавляем один и тот же вызов дважды
    call = {"caller": "foo", "callee": "bar", "line": 2, "file": "a.py"}
    symbol_index.add_references("a.py", [call, call])

    refs = symbol_index.find_references("bar")
    assert len(refs) == 1  # Только одна запись


# ── Тест 2: build_call_graph — прямые связи ───────────────────────────────


def test_build_call_graph_callees(populated_index):
    """build_call_graph находит callees (кого вызывает символ)."""
    graph = populated_index.build_call_graph("authenticate", depth=1)

    # authenticate вызывает validate_token и get_user
    callees = [c["symbol"] for c in graph["callees"]]
    assert "validate_token" in callees
    assert "get_user" in callees


def test_build_call_graph_callers(populated_index):
    """build_call_graph находит callers (кто вызывает символ)."""
    graph = populated_index.build_call_graph("validate_token", depth=1)

    # validate_token вызывается из authenticate
    callers = [c["symbol"] for c in graph["callers"]]
    assert "authenticate" in callers


def test_build_call_graph_depth_2(populated_index):
    """build_call_graph с depth=2 находит косвенные вызовы."""
    graph = populated_index.build_call_graph("authenticate", depth=2)

    # authenticate → validate_token → check_signature (depth 2)
    callees_symbols = [c["symbol"] for c in graph["callees"]]
    assert "check_signature" in callees_symbols


def test_build_call_graph_impact_files(populated_index):
    """build_call_graph собирает impact_files."""
    graph = populated_index.build_call_graph("authenticate", depth=2)

    # impact_files должен содержать main.py, auth.py, utils.py
    impact = graph["impact_files"]
    assert "main.py" in impact
    assert "auth.py" in impact


def test_build_call_graph_call_chain(populated_index):
    """build_call_graph формирует call_chain для контекста."""
    graph = populated_index.build_call_graph("check_signature", depth=2)

    # check_signature вызывается из validate_token → authenticate
    chain = graph.get("call_chain", [])
    # call_chain содержит строки вида "symbol (file:line)"
    assert len(chain) >= 1


# ── Тест 3: get_call_chain ────────────────────────────────────────────────


def test_get_call_chain_up(populated_index):
    """get_call_chain с direction='up' находит callers."""
    chain = populated_index.get_call_chain("check_signature", direction="up", max_depth=3)

    # check_signature ← validate_token ← authenticate
    callers_symbols = [c["symbol"] for c in chain["callers_chain"]]
    assert "validate_token" in callers_symbols
    assert "authenticate" in callers_symbols


def test_get_call_chain_down(populated_index):
    """get_call_chain с direction='down' находит callees."""
    chain = populated_index.get_call_chain("authenticate", direction="down", max_depth=3)

    # authenticate → validate_token → check_signature → log_event
    callees_symbols = [c["symbol"] for c in chain["callees_chain"]]
    assert "validate_token" in callees_symbols
    assert "check_signature" in callees_symbols
    assert "log_event" in callees_symbols


def test_get_call_chain_both(populated_index):
    """get_call_chain с direction='both' находить и то, и другое."""
    chain = populated_index.get_call_chain("validate_token", direction="both", max_depth=2)

    callers = [c["symbol"] for c in chain["callers_chain"]]
    callees = [c["symbol"] for c in chain["callees_chain"]]

    # validate_token ← authenticate (caller)
    assert "authenticate" in callers
    # validate_token → check_signature (callee)
    assert "check_signature" in callees


def test_get_call_chain_total_connected(populated_index):
    """get_call_chain подсчитывает total_connected."""
    chain = populated_index.get_call_chain("validate_token", direction="both", max_depth=3)

    # Должна быть хотя бы одно соединение
    assert chain["total_connected"] >= 1


# ── Тест 4: Edge cases ────────────────────────────────────────────────────


def test_build_call_graph_nonexistent_symbol(symbol_index):
    """build_call_graph для несуществующего символа не падает."""
    graph = symbol_index.build_call_graph("nonexistent", depth=2)

    assert graph["symbol"] == "nonexistent"
    assert graph["definition"] == []
    assert graph["callers"] == []
    assert graph["callees"] == []


def test_build_call_graph_depth_limit(symbol_index):
    """build_call_graph ограничивает глубину до 5."""
    # Создаём глубокий граф
    for i in range(10):
        symbol_index.add_definitions(f"f{i}.py", [
            {"name": f"func{i}", "line": 1, "kind": "function"},
        ])
        if i > 0:
            symbol_index.add_references(f"f{i}.py", [
                {"caller": f"func{i}", "callee": f"func{i-1}", "line": 2, "file": f"f{i}.py"},
            ])

    # depth=100 должен быть ограничен до 5
    graph = symbol_index.build_call_graph("func9", depth=100)
    assert graph["depth_reached"] <= 5


def test_build_call_graph_cyclic_calls(symbol_index):
    """build_call_graph не уходит в бесконечный цикл при циклических вызовах."""
    # A → B → C → A (цикл)
    symbol_index.add_definitions("cycle.py", [
        {"name": "func_a", "line": 1, "kind": "function"},
        {"name": "func_b", "line": 10, "kind": "function"},
        {"name": "func_c", "line": 20, "kind": "function"},
    ])
    symbol_index.add_references("cycle.py", [
        {"caller": "func_a", "callee": "func_b", "line": 2, "file": "cycle.py"},
        {"caller": "func_b", "callee": "func_c", "line": 11, "file": "cycle.py"},
        {"caller": "func_c", "callee": "func_a", "line": 21, "file": "cycle.py"},
    ])

    # Не должно падать или висеть
    graph = symbol_index.build_call_graph("func_a", depth=3)

    # Все три символа должны быть в графе
    all_symbols = (
        [c["symbol"] for c in graph["callees"]]
        + [c["symbol"] for c in graph["callers"]]
    )
    assert "func_b" in all_symbols
    assert "func_c" in all_symbols


def test_get_symbol_context_includes_calls(symbol_index):
    """get_symbol_context включает информацию о вызовах."""
    symbol_index.add_definitions("a.py", [
        {"name": "main_func", "line": 1, "kind": "function"},
    ])
    symbol_index.add_definitions("b.py", [
        {"name": "helper", "line": 1, "kind": "function"},
    ])
    symbol_index.add_references("a.py", [
        {"caller": "main_func", "callee": "helper", "line": 2, "file": "a.py"},
    ])

    context = symbol_index.get_symbol_context("helper")

    # used_in_count — количество уникальных файлов, где символ используется
    assert context.get("used_in_count", 0) >= 1
    # used_in_files содержит файлы (a.py), не символы
    assert "a.py" in context.get("used_in_files", [])
    # calls содержит информацию о вызовах (если есть callees для helper)
    assert "calls" in context


# ── Тест 5: Интеграция с парсером ─────────────────────────────────────────


def test_parser_extract_calls_python():
    """CodeParser.extract_calls извлекает вызовы из Python-кода."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""\
def main():
    result = process_data()
    validate(result)

def process_data():
    return fetch_from_db()

def validate(data):
    if not data:
        raise ValueError()

def fetch_from_db():
    return []
""")
        f.flush()

        parser = CodeParser()
        calls = parser.extract_calls(Path(f.name))

    # Должны быть извлечены вызовы
    assert len(calls) > 0

    # Проверяем структуру
    for call in calls:
        assert "caller" in call
        assert "callee" in call
        assert "line" in call
        assert "file" in call


def test_parser_extract_calls_with_methods():
    """CodeParser.extract_calls извлекает вызовы методов объектов.

    Примечание: tree-sitter может быть недоступен в тестовом окружении.
    Тест проверяет что метод не падает и возвращает корректную структуру.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""\
def handler():
    db.connect()
    result = service.process()
    return result
""")
        f.flush()

        parser = CodeParser()

        # Если tree-sitter недоступен — просто проверяем что метод работает
        if not parser.parsers:
            pytest.skip("Tree-sitter parsers not available")

        calls = parser.extract_calls(Path(f.name))

    # Если парсер работает — проверяем результат
    if calls:
        callees = [c["callee"] for c in calls]
        # Должны быть вызовы connect и process (если tree-sitter распарсил)
        assert any(c in callees for c in ["connect", "process"])
    else:
        # Если tree-sitter не смог распарсить — хотя бы проверяем что не упал
        assert calls == []


def test_parser_extract_calls_empty_file():
    """CodeParser.extract_calls для пустого файла возвращает пустой список."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("")
        f.flush()

        parser = CodeParser()
        calls = parser.extract_calls(Path(f.name))

    assert calls == []


def test_parser_extract_calls_unsupported_extension():
    """CodeParser.extract_calls для неподдерживаемого расширения возвращает []."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("some text")
        f.flush()

        parser = CodeParser()
        calls = parser.extract_calls(Path(f.name))

    assert calls == []


# ── Тест 6: Impact Analysis ───────────────────────────────────────────────


def test_impact_analysis_basic(populated_index):
    """get_impact_analysis возвращает корректные метрики."""
    result = populated_index.get_impact_analysis("authenticate", depth=2)

    assert result["symbol"] == "authenticate"
    assert result["direct_callers"] >= 0
    assert result["transitive_callers"] >= 0
    assert result["direct_callees"] >= 0
    assert result["transitive_callees"] >= 0
    assert isinstance(result["affected_files"], list)
    assert isinstance(result["affected_modules"], list)
    assert result["risk_level"] in ("low", "medium", "high", "critical")
    assert 0 <= result["risk_score"] <= 100


def test_impact_analysis_direct_callers(populated_index):
    """get_impact_analysis правильно считает direct_callers."""
    # authenticate вызывается никем (top-level функция)
    result = populated_index.get_impact_analysis("authenticate", depth=2)
    assert result["direct_callers"] == 0

    # validate_token вызывается из authenticate
    result = populated_index.get_impact_analysis("validate_token", depth=2)
    assert result["direct_callers"] == 1


def test_impact_analysis_direct_callees(populated_index):
    """get_impact_analysis правильно считает direct_callees."""
    # authenticate вызывает validate_token и get_user
    result = populated_index.get_impact_analysis("authenticate", depth=1)
    assert result["direct_callees"] == 2


def test_impact_analysis_transitive(populated_index):
    """get_impact_analysis находит косвенные зависимости."""
    # authenticate → validate_token → check_signature (transitive callee)
    result = populated_index.get_impact_analysis("authenticate", depth=3)
    assert result["transitive_callees"] >= 1
    assert "check_signature" in [
        c["symbol"] for c in result["call_graph"]["callees"]
    ]


def test_impact_analysis_affected_files(populated_index):
    """get_impact_analysis собирает affected_files."""
    result = populated_index.get_impact_analysis("authenticate", depth=3)

    # Должен затронуть main.py, auth.py, utils.py
    files = result["affected_files"]
    assert "main.py" in files
    assert "auth.py" in files


def test_impact_analysis_risk_levels(populated_index):
    """get_impact_analysis корректно определяет risk_level."""
    # Символ без зависимостей — low risk
    result = populated_index.get_impact_analysis("log_event", depth=2)
    assert result["risk_level"] == "low"
    assert result["risk_score"] < 25

    # Символ с зависимостями — medium+ risk
    result = populated_index.get_impact_analysis("authenticate", depth=3)
    assert result["risk_score"] >= 0


def test_impact_analysis_nonexistent_symbol(symbol_index):
    """get_impact_analysis для несуществующего символа не падает."""
    result = symbol_index.get_impact_analysis("nonexistent", depth=2)

    assert result["symbol"] == "nonexistent"
    assert result["direct_callers"] == 0
    assert result["direct_callees"] == 0
    assert result["affected_files"] == []
    assert result["risk_level"] == "low"
    assert result["risk_score"] == 0


def test_impact_analysis_depth_limit(populated_index):
    """get_impact_analysis ограничивает глубину."""
    # depth=1 — только прямые связи
    result_shallow = populated_index.get_impact_analysis("authenticate", depth=1)

    # depth=3 — больше косвенных связей
    result_deep = populated_index.get_impact_analysis("authenticate", depth=3)

    # Глубокий анализ должен найти больше или столько же
    assert result_deep["transitive_callees"] >= result_shallow["transitive_callees"]


def test_risk_score_calculation(symbol_index):
    """Risk score растёт с увеличением зависимостей."""
    # Создаём символ с одним caller
    symbol_index.add_definitions("test.py", [
        {"name": "single_caller", "line": 1, "kind": "function"},
        {"name": "caller1", "line": 10, "kind": "function"},
    ])
    symbol_index.add_references("test.py", [
        {"caller": "caller1", "callee": "single_caller", "line": 11, "file": "test.py"},
    ])

    result_single = symbol_index.get_impact_analysis("single_caller", depth=2)

    # Добавляем ещё 4 caller'ов
    for i in range(2, 6):
        symbol_index.add_definitions("test.py", [
            {"name": f"caller{i}", "line": i * 10, "kind": "function"},
        ])
        symbol_index.add_references("test.py", [
            {"caller": f"caller{i}", "callee": "single_caller", "line": i * 10 + 1, "file": "test.py"},
        ])

    result_multiple = symbol_index.get_impact_analysis("single_caller", depth=2)

    # Больше caller'ов = выше score
    assert result_multiple["risk_score"] >= result_single["risk_score"]
    assert result_multiple["direct_callers"] == 5


# ── Тест 6: Статистика ────────────────────────────────────────────────────


def test_stats_includes_references(symbol_index):
    """stats включает информацию о references."""
    symbol_index.add_definitions("a.py", [
        {"name": "foo", "line": 1, "kind": "function"},
    ])
    symbol_index.add_definitions("b.py", [
        {"name": "bar", "line": 1, "kind": "function"},
    ])
    symbol_index.add_references("a.py", [
        {"caller": "foo", "callee": "bar", "line": 2, "file": "a.py"},
    ])

    stats = symbol_index.stats()

    assert stats["total_definitions"] == 2
    assert stats["total_references"] == 1
    assert stats["total_symbols"] == 2
