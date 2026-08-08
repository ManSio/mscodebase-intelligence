"""Late Enrichment (WS3): обогащение результатов метаданными чанка."""

import json

import pytest

from src.config.settings import get_config, reload_config
from src.core.search.engine import Searcher


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    """Сохраняем/восстанавливаем конфиг после тестов с env-переменными."""
    saved = __import__("os").environ.get("MSCODEBASE_LATE_ENRICHMENT")
    yield
    if saved is None:
        monkeypatch.delenv("MSCODEBASE_LATE_ENRICHMENT", raising=False)
    else:
        monkeypatch.setenv("MSCODEBASE_LATE_ENRICHMENT", saved)
    reload_config()


def _make_searcher(monkeypatch, late_enrichment: bool):
    """Searcher с управляемым флагом (без indexer/embedder — не нужны для метода)."""
    monkeypatch.setenv("MSCODEBASE_LATE_ENRICHMENT", "true" if late_enrichment else "false")
    return Searcher(indexer=None, embedder=None)


def _sample_result(text: str = "def foo():\n    return 1\n", file: str = "src/core/x.py"):
    return {
        "text": text,
        "final_score": 0.9,
        "metadata": {
            "file": file,
            "chunk_index": 0,
            "layer": "core",
            "imports": json.dumps(["os", "sys"]),
        },
    }


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_LATE_ENRICHMENT", raising=False)
    reload_config()
    assert get_config().search.late_enrichment is False
    searcher = Searcher(indexer=None, embedder=None)
    assert searcher._late_enrichment is False


def test_flag_on_when_env_set(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_LATE_ENRICHMENT", "true")
    reload_config()
    assert get_config().search.late_enrichment is True
    searcher = Searcher(indexer=None, embedder=None)
    assert searcher._late_enrichment is True


def test_enrichment_adds_context(monkeypatch):
    searcher = _make_searcher(monkeypatch, late_enrichment=True)
    result = _sample_result()
    enriched = searcher._late_enrich_results([result], "query")
    extra = enriched[0]["metadata"].get("context_extra", {})
    assert extra.get("module") == "x"
    assert extra.get("parent_symbol") == "foo"
    assert extra.get("imports") == ["os", "sys"]
    assert extra.get("chunk_headline") == "def foo():"
    assert enriched[0]["metadata"].get("enrichment_tokens", 0) > 0


def test_enrichment_does_not_change_score_or_text(monkeypatch):
    searcher = _make_searcher(monkeypatch, late_enrichment=True)
    result = _sample_result()
    text_before = result["text"]
    score_before = result["final_score"]
    enriched = searcher._late_enrich_results([result], "query")
    assert enriched[0]["text"] == text_before
    assert enriched[0]["final_score"] == score_before


def test_enrichment_empty_results(monkeypatch):
    searcher = _make_searcher(monkeypatch, late_enrichment=True)
    assert searcher._late_enrich_results([], "query") == []


def test_enrichment_bad_metadata_ignored(monkeypatch):
    searcher = _make_searcher(monkeypatch, late_enrichment=True)
    result = {"text": "x", "metadata": None}
    enriched = searcher._late_enrich_results([result], "query")
    assert enriched[0]["metadata"] is None


def test_enrichment_tracks_only_top10(monkeypatch):
    searcher = _make_searcher(monkeypatch, late_enrichment=True)
    results = [_sample_result(text=f"def fn{i}():\n    pass\n") for i in range(15)]
    enriched = searcher._late_enrich_results(results, "query")
    with_extra = [
        r for r in enriched if r.get("metadata", {}).get("context_extra")
    ]
    assert len(with_extra) == 10
