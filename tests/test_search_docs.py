from src.core.search.engine import Searcher


class _FakeStore:
    def search(self, query, limit=20):
        return [
            {"metadata": {"file": "src/a.py"}, "text": "code", "final_score": 3.0},
            {"metadata": {"file": "docs/a.md"}, "text": "doc a", "final_score": 2.0},
            {"metadata": {"file": "docs/a.md"}, "text": "doc a dup", "final_score": 1.9},
            {"metadata": {"file": "docs/b.md"}, "text": "doc b", "final_score": 1.0},
        ]


def test_search_docs_filters_and_dedupes():
    searcher = Searcher.__new__(Searcher)
    searcher._chunk_store = _FakeStore()
    out = searcher.search_docs("q", limit=2)
    assert [r["metadata"]["file"] for r in out] == ["docs/a.md", "docs/b.md"]
    assert all(r["source"] == "docs_fts" for r in out)


def test_search_docs_without_store():
    searcher = Searcher.__new__(Searcher)
    searcher._chunk_store = None
    assert searcher.search_docs("q") == []


class _LangStore:
    def search(self, query, limit=20):
        return [
            {"metadata": {"file": "docs/en/X.md"}, "text": "x en", "final_score": 4.0},
            {"metadata": {"file": "docs/ru/X.md"}, "text": "x ru", "final_score": 3.9},
            {"metadata": {"file": "docs/en/Y.md"}, "text": "y en", "final_score": 3.0},
            {"metadata": {"file": "docs/ru/Y.md"}, "text": "y ru", "final_score": 2.9},
        ]


def test_search_docs_collapses_language_variants():
    searcher = Searcher.__new__(Searcher)
    searcher._chunk_store = _LangStore()
    out = searcher.search_docs("русский запрос", limit=5)
    assert [r["metadata"]["file"] for r in out] == ["docs/ru/X.md", "docs/ru/Y.md"]


class _ScoreStore:
    def __init__(self, docs, code):
        self._rows = [
            {"metadata": {"file": "docs/a.md"}, "final_score": docs},
            {"metadata": {"file": "src/a.py"}, "final_score": code},
        ]

    def search(self, query, limit=20):
        return self._rows


def test_prefers_docs_margin():
    searcher = Searcher.__new__(Searcher)
    searcher._docs_margin = 4.0
    searcher._chunk_store = _ScoreStore(10.0, 5.0)
    assert searcher.prefers_docs("q") is True
    searcher._chunk_store = _ScoreStore(5.0, 10.0)
    assert searcher.prefers_docs("q") is False
    searcher._chunk_store = _ScoreStore(8.0, 4.5)
    assert searcher.prefers_docs("q") is False  # margin 3.5 < 4.0
