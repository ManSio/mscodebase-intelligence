from src.core.search.query_plan import apply_plan_boosts, build_plan, normalize_list


def test_build_plan_identifiers():
    plan = build_plan(
        "Почему в ограничителе скорости используется threading.Lock, а не asyncio.Lock?"
    )
    assert "threading.Lock" in plan["must_include"]
    assert "asyncio.Lock" in plan["must_include"]
    assert plan["primary"]
    assert "скорости" in plan["primary"].lower()


def test_build_plan_symbols():
    plan = build_plan("Fix RemoteEmbedder cache path")
    assert "RemoteEmbedder" in plan["must_include"]
    assert "RemoteEmbedder" in plan["symbols"]
    assert "cache" in plan["concepts"]


def test_normalize_list():
    assert normalize_list("a, b; c") == ["a", "b", "c"]
    assert normalize_list(["a", " b "]) == ["a", "b"]
    assert normalize_list(None) == []


def test_apply_plan_boosts():
    results = [
        {"metadata": {"symbol_name": "foo", "file": "a.py"}, "text": "x", "final_score": 1.0},
        {"metadata": {"symbol_name": "RemoteEmbedder", "file": "b.py"}, "text": "remote", "final_score": 1.0},
    ]
    out = apply_plan_boosts(results, must_include=["RemoteEmbedder"], symbols=[])
    assert out[0]["metadata"]["symbol_name"] == "RemoteEmbedder"
    assert out[0]["_plan_score"] == 2.0

def test_russian_docs_intent():
    from src.core.search.scoring import auto_detect_intent

    assert auto_detect_intent("Как устроена архитектура поискового конвейера?") == "docs"
    assert auto_detect_intent("Что описано в README про установку?") == "docs"
    assert auto_detect_intent("Где проходит граница доверия и что означает trust boundary?") == "docs"
    assert auto_detect_intent("Почему в ACTIVE-узлы памяти не проверяются verify-on-read?") == "docs"
    assert auto_detect_intent("Почему парсер .gitignore использует формат gitignore?") != "docs"
