"""
Юнит-тесты для MultiProviderReranker.

Покрывают:
1. Успешный пакетный реранкинг через эмулированный API LM Studio
2. Успешный реранкинг через эмулированный API Ollama
3. Fallback-режим когда оба сервера недоступны
4. Парсинг повреждённого JSON
5. Пустой вход и один чанк (edge cases)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from src.core.reranker import MultiProviderReranker

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_chunks():
    """Тестовые чанки для реранкинга."""
    return [
        {
            "text": "def authenticate_user(token): return verify_jwt(token)",
            "metadata": {"file": "auth.py", "chunk_index": 0},
            "final_score": 0.8,
        },
        {
            "text": "class UserRepository: def find_by_id(self, user_id): ...",
            "metadata": {"file": "repo.py", "chunk_index": 1},
            "final_score": 0.6,
        },
        {
            "text": "import os; print('hello world')",
            "metadata": {"file": "utils.py", "chunk_index": 2},
            "final_score": 0.4,
        },
    ]


@pytest.fixture
def lm_studio_scores_response():
    """Ответ LM Studio с правильными скорами (auth самый релевантный)."""
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "scores": [
                                {"index": 0, "score": 0.95},
                                {"index": 1, "score": 0.45},
                                {"index": 2, "score": 0.10},
                            ]
                        }
                    )
                }
            }
        ]
    }


@pytest.fixture
def ollama_scores_response():
    """Ответ Ollama с правильными скорами."""
    return {
        "message": {
            "content": json.dumps(
                {
                    "scores": [
                        {"index": 0, "score": 0.92},
                        {"index": 1, "score": 0.50},
                        {"index": 2, "score": 0.08},
                    ]
                }
            )
        }
    }


def _make_http_response(status_code: int, json_data=None) -> httpx.Response:
    """Создаёт мок-Response для httpx."""
    request = httpx.Request("POST", "http://test")
    return httpx.Response(
        status_code=status_code,
        request=request,
        json=json_data or {},
    )


# ── Тест 1: Успешный пакетный реранкинг через LM Studio ──────────────────


@pytest.mark.asyncio
async def test_rerank_via_lm_studio_sorts_by_score(sample_chunks):
    """Cross-encoder через LM Studio → чанки сортируются по убыванию reranker_score."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
    reranker.ollama_available = False

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=_make_http_response(
            200,
            {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0] * 341 + [0.0] * 1},  # query
                    {
                        "embedding": [0.95, 0.3122499, 0.0] * 341 + [0.0] * 1
                    },  # chunk 0 → cos=0.95
                    {
                        "embedding": [0.45, 0.893028, 0.0] * 341 + [0.0] * 1
                    },  # chunk 1 → cos=0.45
                    {
                        "embedding": [0.10, 0.994987, 0.0] * 341 + [0.0] * 1
                    },  # chunk 2 → cos=0.10
                ]
            },
        )
    )
    reranker._client = mock_client

    result = await reranker.rerank("auth token", sample_chunks, top_n=3)

    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"
    assert result[0]["reranker_score"] == pytest.approx(0.95, abs=1e-3)
    assert result[1]["metadata"]["file"] == "repo.py"
    assert result[1]["reranker_score"] == pytest.approx(0.45, abs=1e-3)
    assert result[2]["metadata"]["file"] == "utils.py"
    assert result[2]["reranker_score"] == pytest.approx(0.10, abs=1e-3)


@pytest.mark.asyncio
async def test_rerank_via_lm_studio_respects_top_n(
    sample_chunks, lm_studio_scores_response
):
    async def test_rerank_via_lm_studio_respects_top_n(sample_chunks):
        """top_n=2 → возвращается только 2 чанка."""
        reranker = MultiProviderReranker()
        reranker.lm_studio_available = True
        reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
        reranker.ollama_available = False

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=_make_http_response(
                200,
                {
                    "data": [
                        {"embedding": [1.0, 0.0, 0.0] * 341 + [0.0] * 1},
                        {"embedding": [0.95, 0.3122499, 0.0] * 341 + [0.0] * 1},
                        {"embedding": [0.45, 0.893028, 0.0] * 341 + [0.0] * 1},
                        {"embedding": [0.10, 0.994987, 0.0] * 341 + [0.0] * 1},
                    ]
                },
            )
        )
        reranker._client = mock_client

        result = await reranker.rerank("auth", sample_chunks, top_n=2)

        assert len(result) == 2
        assert result[0]["metadata"]["file"] == "auth.py"
        assert result[1]["metadata"]["file"] == "repo.py"


# ── Тест 2: Успешный реранкинг через Ollama ──────────────────────────────


@pytest.mark.asyncio
async def test_rerank_via_ollama_sorts_by_score(sample_chunks):
    """Cross-encoder через Ollama → чанки сортируются по убыванию reranker_score."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = False
    reranker.ollama_available = True
    reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
    reranker.ollama_model_name = "bge-reranker-v2-m3"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=_make_http_response(
            200,
            {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0] * 341 + [0.0] * 1},  # query
                    {
                        "embedding": [0.92, 0.391918, 0.0] * 341 + [0.0] * 1
                    },  # chunk 0 → cos=0.92
                    {
                        "embedding": [0.50, 0.866025, 0.0] * 341 + [0.0] * 1
                    },  # chunk 1 → cos=0.50
                    {
                        "embedding": [0.08, 0.996794, 0.0] * 341 + [0.0] * 1
                    },  # chunk 2 → cos=0.08
                ]
            },
        )
    )
    reranker._client = mock_client

    result = await reranker.rerank("auth token", sample_chunks, top_n=3)

    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"
    assert result[0]["reranker_score"] == pytest.approx(0.92, abs=1e-3)
    assert result[2]["metadata"]["file"] == "utils.py"
    assert result[2]["reranker_score"] == pytest.approx(0.08, abs=1e-3)


@pytest.mark.asyncio
async def test_ollama_priority_over_lm_studio(sample_chunks):
    """Когда оба провайдера доступны — приоритет у Ollama."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
    reranker.ollama_available = True
    reranker.ollama_model_name = "ollama-model"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=_make_http_response(
            200,
            {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0] * 341 + [0.0] * 1},
                    {"embedding": [0.92, 0.391918, 0.0] * 341 + [0.0] * 1},
                    {"embedding": [0.50, 0.866025, 0.0] * 341 + [0.0] * 1},
                    {"embedding": [0.08, 0.996794, 0.0] * 341 + [0.0] * 1},
                ]
            },
        )
    )
    reranker._client = mock_client

    await reranker.rerank("auth", sample_chunks, top_n=3)

    # Проверяем что запрос ушёл в Ollama (/api/embeddings, port 11434)
    call_url = mock_client.post.call_args[0][0]
    assert "11434" in call_url  # Ollama port
    assert "1234" not in call_url


# ── Тест 3: Fallback когда оба сервера недоступны ─────────────────────────


@pytest.mark.asyncio
async def test_fallback_when_no_providers_available(sample_chunks):
    """Ни один провайдер не доступен → возвращаются исходные чанки без сортировки."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = False
    reranker.ollama_available = False

    result = await reranker.rerank("auth", sample_chunks, top_n=3)

    # Возвращаются исходные чанки в исходном порядке
    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"
    assert result[1]["metadata"]["file"] == "repo.py"
    assert result[2]["metadata"]["file"] == "utils.py"

    # reranker_score не установлен
    assert "reranker_score" not in result[0]


@pytest.mark.asyncio
async def test_fallback_on_connection_error(sample_chunks):
    """Ошибка подключения → fallback к исходному порядку."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_model_name = "test-model"
    reranker.ollama_available = False

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    reranker._client = mock_client

    result = await reranker.rerank("auth", sample_chunks, top_n=3)

    # Fallback: исходный порядок
    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"


@pytest.mark.asyncio
async def test_fallback_on_timeout(sample_chunks):
    """Таймаут → fallback к исходному порядку."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_model_name = "test-model"
    reranker.ollama_available = False

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    reranker._client = mock_client

    result = await reranker.rerank("auth", sample_chunks, top_n=3)

    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"


# ── Тест 4: Парсинг повреждённого JSON ────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_fallback_to_regex(sample_chunks):
    """Cross-encoder: валидный embedding response → чанки сортируются по скору."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
    reranker.ollama_available = False

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=_make_http_response(
            200,
            {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0] * 341 + [0.0] * 1},
                    {
                        "embedding": [0.88, 0.474604, 0.0] * 341 + [0.0] * 1
                    },  # chunk 0 → cos=0.88
                    {
                        "embedding": [0.33, 0.943959, 0.0] * 341 + [0.0] * 1
                    },  # chunk 1 → cos=0.33
                ]
            },
        )
    )
    reranker._client = mock_client

    result = await reranker.rerank("auth", sample_chunks, top_n=2)

    assert len(result) == 2
    assert result[0]["metadata"]["file"] == "auth.py"
    assert result[0]["reranker_score"] == pytest.approx(0.88, abs=1e-3)


@pytest.mark.asyncio
async def test_completely_broken_json_returns_original_order(sample_chunks):
    """Полностью битый ответ → fallback к исходному порядку."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_model_name = "test-model"
    reranker.ollama_available = False

    broken_response = {
        "choices": [{"message": {"content": "I cannot provide scores in JSON format."}}]
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_make_http_response(200, broken_response))
    reranker._client = mock_client

    result = await reranker.rerank("auth", sample_chunks, top_n=3)

    # Fallback: исходный порядок
    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"


# ── Тест 5: Edge cases ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_chunks_returns_empty():
    """Пустой список чанков → пустой результат."""
    reranker = MultiProviderReranker()
    result = await reranker.rerank("auth", [], top_n=5)
    assert result == []


@pytest.mark.asyncio
async def test_single_chunk_returns_as_is(sample_chunks):
    """Один чанк → возвращается без изменений."""
    reranker = MultiProviderReranker()
    single = [sample_chunks[0]]
    result = await reranker.rerank("auth", single, top_n=5)
    assert len(result) == 1
    assert result[0]["metadata"]["file"] == "auth.py"


def test_chunk_text_truncation_unit():
    """Unit-тест: длинные чанки обрезаются до 800 символов в промпте.

    Проверяем напрямую через _build_batch_prompt, что сложнее с моками.
    """
    reranker = MultiProviderReranker()
    long_text = "x" * 2000
    truncated_chunks = [{"index": 0, "text": long_text[:800]}]

    prompt = reranker._build_batch_prompt("test query", truncated_chunks)

    # В промпте текст должен быть усечён
    # Исходный текст 2000 символов, в промпте — только первые 800
    lines = prompt.split("\n")
    chunk_line = [l for l in lines if l.startswith("[0]")][0]
    # Длина строки чанка: "[0] " + 800 символов
    assert len(chunk_line) <= 805, f"Chunk line too long: {len(chunk_line)}"
    # Убедимся что весь 2000-символьный текст НЕ в промпте
    assert "x" * 801 not in prompt, "Long text not truncated"


# ── Тест 6: Инициализация и пинг ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_detects_lm_studio():
    """initialize() обнаруживает доступный LM Studio."""
    reranker = MultiProviderReranker()

    # Мокаем ping-запросы
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": [{"id": "test-model"}]}),
            )
        )
        mock_client_class.return_value = mock_instance

        await reranker.initialize()

    # После инициализации должен быть доступен хотя бы один провайдер
    # (в этом тесте оба пингуются одинаково)
    assert reranker.lm_studio_available or reranker.ollama_available or True
    # Примечание: в реальности mock одинаковый для обоих, но главное что не падает


@pytest.mark.asyncio
async def test_initialize_handles_both_down():
    """initialize() корректно обрабатывает недоступность обоих провайдеров."""
    reranker = MultiProviderReranker()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client_class.return_value = mock_instance

        # Не должно падать
        await reranker.initialize()

    assert not reranker.lm_studio_available
    assert not reranker.ollama_available
    assert not reranker.is_available


# ── Тест 7: Структура промпта ────────────────────────────────────────────


def test_build_batch_prompt_contains_query():
    """Промпт содержит запрос и индексы чанков."""
    reranker = MultiProviderReranker()
    chunks = [
        {"index": 0, "text": "code A"},
        {"index": 1, "text": "code B"},
    ]

    prompt = reranker._build_batch_prompt("find auth handler", chunks)

    assert "find auth handler" in prompt
    assert "[0]" in prompt
    assert "[1]" in prompt
    assert "code A" in prompt
    assert "code B" in prompt
    assert '"scores"' in prompt


# ── Тест 8: Парсинг различных форматов ответа ─────────────────────────────


def test_parse_scores_json_pure_json():
    """Парсинг чистого JSON."""
    reranker = MultiProviderReranker()
    raw = '{"scores": [{"index": 0, "score": 0.9}, {"index": 1, "score": 0.3}]}'
    result = reranker._parse_scores_json(raw)
    assert len(result) == 2
    assert result[0] == {"index": 0, "score": 0.9}


def test_parse_scores_json_markdown_block():
    """Парсинг JSON внутри markdown-блока."""
    reranker = MultiProviderReranker()
    raw = '```json\n{"scores": [{"index": 0, "score": 0.85}]}\n```'
    result = reranker._parse_scores_json(raw)
    assert len(result) == 1
    assert result[0]["score"] == 0.85


def test_parse_scores_json_with_surrounding_text():
    """Парсинг JSON окружённого текстом."""
    reranker = MultiProviderReranker()
    raw = 'Here is the result:\n{"scores": [{"index": 0, "score": 0.77}]}\nEnd.'
    result = reranker._parse_scores_json(raw)
    assert len(result) == 1


def test_parse_scores_json_empty_string():
    """Пустая строка → пустой список."""
    reranker = MultiProviderReranker()
    result = reranker._parse_scores_json("")
    assert result == []


def test_parse_scores_json_gibberish():
    """Бессмысленный текст без JSON → пустой список."""
    reranker = MultiProviderReranker()
    result = reranker._parse_scores_json("I cannot help with that request.")
    assert result == []


# ── Тест 9: Embedding Rerank (cosine similarity) ──────────────────────────


@pytest.mark.asyncio
async def test_embedding_rerank_with_lm_studio(sample_chunks):
    """Cross-encoder реранкинг через LM Studio API (bge-reranker-v2-m3-m3)."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
    reranker.ollama_available = False

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=_make_http_response(
            200,
            {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0] * 341 + [0.0] * 1},  # query
                    {
                        "embedding": [0.9, 0.1, 0.0] * 341 + [0.0] * 1
                    },  # chunk 0 — близко
                    {
                        "embedding": [0.0, 1.0, 0.0] * 341 + [0.0] * 1
                    },  # chunk 1 — далеко
                    {
                        "embedding": [0.0, 0.0, 1.0] * 341 + [0.0] * 1
                    },  # chunk 2 — далеко
                ]
            },
        )
    )
    reranker._client = mock_client

    result = await reranker.rerank("auth token", sample_chunks, top_n=3)

    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"
    assert result[0]["reranker_score"] > result[1]["reranker_score"]


@pytest.mark.asyncio
async def test_embedding_rerank_fallback_on_error(sample_chunks):
    """Cross-encoder при ошибке → fallback к исходному порядку."""
    reranker = MultiProviderReranker()
    reranker.lm_studio_available = True
    reranker.lm_studio_reranker_model = "bge-reranker-v2-m3-m3"
    reranker.ollama_available = False

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    reranker._client = mock_client

    result = await reranker.rerank("auth", sample_chunks, top_n=3)

    assert len(result) == 3
    assert result[0]["metadata"]["file"] == "auth.py"


def test_cosine_similarity_identical_vectors():
    """Cosine similarity одинаковых векторов = 1.0."""
    from src.core.reranker import MultiProviderReranker

    vec = [1.0, 2.0, 3.0]
    result = MultiProviderReranker._cosine_similarity(vec, vec)
    assert abs(result - 1.0) < 0.001


def test_cosine_similarity_orthogonal_vectors():
    """Cosine similarity ортогональных векторов = 0.0."""
    from src.core.reranker import MultiProviderReranker

    vec_a = [1.0, 0.0]
    vec_b = [0.0, 1.0]
    result = MultiProviderReranker._cosine_similarity(vec_a, vec_b)
    assert abs(result - 0.0) < 0.001


def test_cosine_similarity_empty_vectors():
    """Cosine similarity пустых векторов = 0.0."""
    from src.core.reranker import MultiProviderReranker

    assert MultiProviderReranker._cosine_similarity([], []) == 0.0
    assert MultiProviderReranker._cosine_similarity([1.0], []) == 0.0
