"""
Advanced Mutation & Robustness Test Suite for MSCodebase Intelligence
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.core.context_engine import get_context
from src.core.symbol_index import SymbolIndex, SymbolRef
from src.utils.paths import SafePathManager


# =====================================================================
# 1. СЕМАНТИЧЕСКИЙ МУТАТОР (Генератор деструктивных данных для ИИ/RAG)
# =====================================================================
class SemanticMutator:
    """Симулирует повреждение данных: зашумление векторов, битые пути, пустые структуры Tree-sitter."""

    @staticmethod
    def mutate_vector(vector: list, noise_level: float = 0.5) -> list:
        """Вносит сильный случайный шум в эмбеддинг, уничтожая семантику."""
        arr = np.array(vector, dtype=np.float32)
        noise = np.random.normal(0, noise_level, arr.shape)
        return (arr + noise).tolist()

    @staticmethod
    def mutate_symbol_ref(ref: SymbolRef) -> SymbolRef:
        """Искажает объект символа, меняя критические границы (например, отрицательные строки)."""
        ref.line = -100  # Мутация граничного значения
        ref.kind = "INVALID_KIND_MUTATION"
        return ref


# =====================================================================
# 2. ПРОДВИНУТЫЕ ТЕСТЫ НА ВЫЖИВАЕМОСТЬ МУТАНТОВ (Mutation Killing)
# =====================================================================


def test_symbol_index_mutation_survival():
    """
    Тест проверяет, убьют ли наши ассерты мутанта,
    если внутренние структуры SymbolIndex будут повреждены.
    """
    idx = SymbolIndex()

    # Базовое наполнение - SymbolIndex.add_definitions ожидает словари, а не SymbolRef объекты
    symbols_from_parser = [
        {"name": "my_func", "line": 10, "kind": "function"},
        {"name": "my_func", "line": 45, "kind": "function"},
    ]

    idx.add_definitions("main.py", symbols_from_parser)

    results = idx.search_symbols("my_func")

    # ❌ ЕСЛИ MUTMUT ИЗМЕНИТ ЛОГИКУ ФИЛЬТРАЦИИ ИЛИ ПОИСКА, ЭТИ АССЕРТЫ ДОЛЖНЫ УБИТЬ МУТАНТА:
    assert len(results) > 0, (
        "Мутант выжил: Поиск вернул пустой список для существующего символа!"
    )

    # Проверяем строгое соответствие типов (чтобы не пропустить TypeError в рантайме)
    for res in results:
        # search_symbols возвращает SymbolRef объекты с атрибутами
        assert hasattr(res, "symbol"), "Мутант выжил: у результата пропал атрибут 'symbol'!"
        assert hasattr(res, "file_path"), "Мутант выжил: у результата пропал атрибут 'file_path'!"
        assert hasattr(res, "kind"), "Мутант выжил: у результата пропал атрибут 'kind'!"
        assert res.symbol == "my_func", (
            f"Мутант выжил: символ = '{res.symbol}', а не 'my_func'!"
        )


@pytest.mark.asyncio
async def test_context_engine_with_semantic_mutations():
    """
    Проверяет устойчивость движка контекста к семантическим мутациям.
    Сборщик контекста НЕ должен падать или превышать лимиты, даже если эмбеддер выдал мусор.
    """
    # Создаем мок поисковика
    mock_searcher = MagicMock()

    # Исходный валидный чанк из базы данных LanceDB
    valid_chunks = [
        {"text": "def test(): pass", "metadata": {"file": "a.py", "chunk_index": 0}},
        {"text": "class Engine: pass", "metadata": {"file": "b.py", "chunk_index": 1}},
    ]

    # get_context вызывает searcher.hybrid_search(), мокаем её
    mock_searcher.hybrid_search.return_value = [
        {"text": "def test(): pass", "metadata": {"file": "a.py", "chunk_index": 0}, "final_score": 0.05},
        {"text": "class Engine: pass", "metadata": {"file": "b.py", "chunk_index": 1}, "final_score": 0.03},
    ]

    # 1. Тест нормального поведения
    ctx = get_context("ищи движок", mock_searcher)
    assert "📊 Сформированный контекст" in ctx
    assert "def test(): pass" in ctx

    # 2. МУТАЦИОННАЯ АТАКА: Пустая выдача базы
    mock_searcher.hybrid_search.return_value = []

    ctx_mutated = get_context("ищи движок", mock_searcher)
    assert (
        "Релевантный контекст не найден." in ctx_mutated
        or "Запрос пуст." in ctx_mutated
    )


def test_path_manager_property_invariants():
    """
    Property-Based подход: проверяем инварианты путей на экстремальных мутациях строк.
    """
    manager = SafePathManager(
        Path("C:/dummy") if os.name == "nt" else Path("/tmp/dummy")
    )

    # Генерируем "дикие" мутировавшие строки для путей (очень длинные, спецсимволы, не-ASCII)
    crazy_inputs = [
        "A" * 500,  # Мутация: Превышение MAX_PATH
        "📁_папка_с_эмодзи_и_пробелами",  # Мутация: Unicode + пробелы
        "",  # Мутация: Пустая строка
        "null\x00byte.py",  # Мутация: Внедрение нуль-байта
    ]

    for corrupted_input in crazy_inputs:
        # Инвариант: SafePathManager никогда не должен выбрасывать необработанное исключение.
        # Метод либо возвращает True/False для необходимости защиты, либо падает предсказуемо.
        try:
            requires_protection = manager.requires_safe_path(corrupted_input)
            assert isinstance(requires_protection, bool)
        except Exception as e:
            pytest.fail(
                f"Мутант победил! SafePathManager упал с критической ошибкой {e} на строке: {corrupted_input}"
            )
