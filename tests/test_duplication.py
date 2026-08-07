"""Тесты find_duplicates (AST-нормализованные отпечатки + minhash-LSH) — B1."""

from src.core.duplication import find_duplicates

DUPE = '''def process_data(items):
    """Normalize incoming values."""
    result = []
    for item in items:
        value = item.get("value", 0)
        result.append(value if value > 0 else 0)
    return result
'''

# Близкий дубль: другие имена переменных + доп. вызов sorted()
NEAR = '''def process_values(records):
    """Normalize incoming values."""
    output = []
    for record in records:
        score = record.get("value", 0)
        output.append(score if score > 0 else -1)
    return sorted(output)
'''


def test_exact_duplicates(tmp_path):
    (tmp_path / "a.py").write_text(DUPE, encoding="utf-8")
    (tmp_path / "b.py").write_text(DUPE, encoding="utf-8")
    res = find_duplicates(tmp_path, min_tokens=10)
    assert res["status"] == "ok"
    assert res["exact_count"] >= 1
    assert any(len(g["symbols"]) == 2 for g in res["exact_groups"])


def test_near_duplicates(tmp_path):
    (tmp_path / "a.py").write_text(DUPE, encoding="utf-8")
    (tmp_path / "b.py").write_text(NEAR, encoding="utf-8")
    res = find_duplicates(tmp_path, threshold=0.7, min_tokens=10)
    pairs = {(p["a"]["name"], p["b"]["name"]) for p in res["near_duplicates"]}
    assert ("process_data", "process_values") in pairs or (
        "process_values",
        "process_data",
    ) in pairs


def test_high_threshold_no_near(tmp_path):
    (tmp_path / "a.py").write_text(DUPE, encoding="utf-8")
    (tmp_path / "b.py").write_text(NEAR, encoding="utf-8")
    res = find_duplicates(tmp_path, threshold=0.99, min_tokens=10)
    assert res["near_count"] == 0


def test_min_tokens_filter(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    res = find_duplicates(tmp_path, min_tokens=50)
    assert res["status"] == "ok"
    assert res["symbols_scanned"] == 0


def test_threshold_clamped(tmp_path):
    (tmp_path / "a.py").write_text(DUPE, encoding="utf-8")
    res = find_duplicates(tmp_path, threshold=5.0, min_tokens=10)
    assert res["threshold"] == 1.0
