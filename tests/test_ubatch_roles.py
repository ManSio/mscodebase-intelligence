"""
Юнит-тесты для роль-специфичного ubatch (2026-09-20).

Покрывают:
1. resolve_ubatch: роли embed/rerank, округление вверх до 128
2. Жёсткий env-override LLAMA_UBATCH_SIZE обеих ролей
3. Кастомные лимиты LLAMA_EMBED_MAX_TOKENS / LLAMA_RERANK_MAX_TOKENS
4. Клиентский трим пары _truncate_rerank_pair (query+passage <= ubatch)
"""

from __future__ import annotations

import pytest

from src.providers.reranker.llama_install import (
    LLAMA_EMBED_MAX_TOKENS,
    LLAMA_RERANK_MAX_TOKENS,
    resolve_ubatch,
)
from src.providers.reranker.multi_provider import _truncate_rerank_pair


def test_resolve_ubatch_default_roles():
    """Дефолтные лимиты: embed 480 -> 512, rerank 1000 -> 1024."""
    assert resolve_ubatch("embed") == 512
    assert resolve_ubatch("rerank") == 1024
    # role по умолчанию = embed
    assert resolve_ubatch() == resolve_ubatch("embed")


def test_resolve_ubatch_rounds_up_to_128():
    """Всегда кратно 128 и покрывает лимит входа."""
    for role, limit in (("embed", LLAMA_EMBED_MAX_TOKENS), ("rerank", LLAMA_RERANK_MAX_TOKENS)):
        ub = resolve_ubatch(role)
        assert ub % 128 == 0
        assert ub >= limit
        assert ub - limit < 128  # без избыточного запаса


@pytest.mark.parametrize(
    "env_value,expected",
    [(128, 128), (256, 256), (512, 512), (2048, 2048)],
)
def test_resolve_ubatch_env_override(monkeypatch, env_value, expected):
    """LLAMA_UBATCH_SIZE — жёсткий override для обеих ролей."""
    monkeypatch.setattr("src.providers.reranker.llama_install.LLAMA_UBATCH_SIZE", env_value)
    assert resolve_ubatch("embed") == expected
    assert resolve_ubatch("rerank") == expected


def test_resolve_ubatch_custom_limits(monkeypatch):
    """Кастомные лимиты ролей пересчитывают ubatch."""
    monkeypatch.setattr("src.providers.reranker.llama_install.LLAMA_EMBED_MAX_TOKENS", 600)
    monkeypatch.setattr("src.providers.reranker.llama_install.LLAMA_RERANK_MAX_TOKENS", 1500)
    assert resolve_ubatch("embed") == 640   # ceil(600/128)*128
    assert resolve_ubatch("rerank") == 1536  # ceil(1500/128)*128


class TestTruncateRerankPair:
    def test_short_pair_unchanged(self):
        query = "как работает auth"
        passages = ["def authenticate_user(token): return verify_jwt(token)"]
        assert _truncate_rerank_pair(query, passages) == query

    def test_long_query_trimmed_to_limit(self):
        query = "x" * 3000
        passages = ["p" * 800]
        # лимит: 1000 токенов * 2 симв = 2000; на passage уходит 800 -> query <= 1200
        out = _truncate_rerank_pair(query, passages)
        assert len(out) <= 1200
        assert out == query[:1200]

    def test_empty_passages(self):
        query = "запрос"
        assert _truncate_rerank_pair(query, []) == query

    def test_preserves_short_query_with_long_passage(self):
        query = "краткий запрос"
        passages = ["y" * 800]
        assert _truncate_rerank_pair(query, passages) == query

    def test_custom_max_tokens(self):
        query = "q" * 500
        passages = ["p" * 400]
        out = _truncate_rerank_pair(query, passages, max_tokens=512)
        # лимит 512*2=1024; passage 400 -> query <= 624
        assert len(out) <= 624
