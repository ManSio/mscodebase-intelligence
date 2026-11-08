"""The vector schema and the query vector must agree on the dimension.

Measured 2026-11-08: `.env` had `EMBEDDING_MODEL=embeddinggemma-2` while the
vector column was 384 (the config default from e5-small). Enabling dense then
raised `lance error: query dim(768) doesn't match the column vector dim(384)`
and the search kept going half-broken, so the failure was invisible unless the
logs were read.
"""
from __future__ import annotations

from src.providers.embedder.remote_embedder import model_dimension


def test_dimension_comes_from_the_model_name():
    assert model_dimension("embeddinggemma-2", 384) == 768
    assert model_dimension("multilingual-e5-small", 384) == 384
    assert model_dimension("bge-m3", 384) == 1024


def test_unknown_model_keeps_the_configured_default():
    assert model_dimension("some-new-model", 384) == 384


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSION", "512")
    assert model_dimension("embeddinggemma-2", 384) == 512


def test_empty_env_does_not_override(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSION", "")
    assert model_dimension("embeddinggemma-2", 384) == 768
