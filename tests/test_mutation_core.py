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
        # search_symbols возвращает словари, а не SymbolRef объекты
        assert isinstance(res, dict), "Мутант выжил: search_symbols вернул не словарь!"
        assert "symbol" in res, "Мутант выжил: у результата пропал ключ 'symbol'!"
        assert "defined_in" in res, (
            "Мутант выжил: у результата пропал ключ 'defined_in'!"
        )
        assert isinstance(res["defined_in"], list), (
            "Мутант выжил: defined_in не список!"
        )
        assert all(isinstance(d, dict) and "line" in d for d in res["defined_in"]), (
            "Мутант выжил: структура defined_in повреждена!"
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

    mock_searcher.embedder.embed.return_value = [0.1, 0.2, 0.3]
    mock_searcher.vector_search.return_value = valid_chunks

    # 1. Тест нормального поведения
    ctx = get_context("ищи движок", mock_searcher)
    assert "📊 Сформированный контекст проекта" in ctx
    assert "def test(): pass" in ctx

    # 2. МУТАЦИОННАЯ АТАКА: Подсовываем уничтоженный эмбеддинг и пустую выдачу базы
    mutated_vector = SemanticMutator.mutate_vector([0.1, 0.2, 0.3], noise_level=2.0)
    mock_searcher.embedder.embed.return_value = mutated_vector
    mock_searcher.vector_search.return_value = []  # База ничего не нашла из-за шума

    ctx_mutated = get_context("ищи движок", mock_searcher)
    # Тест должен убить мутанта (падение), если движок контекста не умеет обрабатывать пустые результаты
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
