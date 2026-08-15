"""Unit-тесты harness 1-L live arm (scripts/run_1L_live_arm.py).

Проверяют методологическую честность: leak-guard промптов, устойчивый парсинг
вердиктов, нормализацию, статистику (Wilson CI) и целостность датасета.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "run_1L_live_arm", ROOT / "scripts" / "run_1L_live_arm.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # noqa: E402


# ─── Leak-guard: ground truth не должен попадать в промпт ───────────────────
def _facts():
    return json.loads((_mod.FACTS).read_text(encoding="utf-8"))["facts"]


def test_prompt_no_truth_leak_both_arms():
    """Промпт обеих рук не содержит ground truth ни в каком виде."""
    for fact in _facts()[:10]:
        for arm in ("memory_first", "code_first"):
            prompt = _mod._prompt(fact, arm)
            assert "truth" not in prompt, f"LEAK в {fact['id']}/{arm}: {prompt}"
            _mod._assert_no_truth_leak(fact, prompt)  # не должен бросить


def test_prompt_memory_first_shows_only_claim():
    """memory_first: claim виден, якоря НЕ видны (чистая память)."""
    fact = _facts()[0]
    prompt = _mod._prompt(fact, "memory_first")
    assert fact["claim"] in prompt
    for pat in fact.get("support_patterns", []):
        assert pat not in prompt, f"memory_first не должен показывать якорь {pat}"


def test_prompt_code_first_shows_anchors():
    """code_first: claim + support_patterns + section видны."""
    fact = _facts()[0]
    prompt = _mod._prompt(fact, "code_first")
    assert fact["claim"] in prompt
    for pat in fact.get("support_patterns", []):
        assert pat in prompt
    assert fact.get("section", "?") in prompt


def test_prompt_v2_neutral_no_leading_question():
    """Red Team fix: V2 не задаёт наводящий вопрос (митигация сикофантии)."""
    fact = _facts()[0]
    p1 = _mod._prompt(fact, "code_first", version="v1")
    p2 = _mod._prompt(fact, "code_first", version="v2")
    assert p1 != p2
    assert "Does the claim appear supported" in p1      # v1 — наводящий
    assert "Does the claim appear supported" not in p2  # v2 — нейтральный
    assert "Return true ONLY if" in p2
    assert "truth" not in p2
    _mod._assert_no_truth_leak(fact, p2)


def test_prompt_v1_unchanged_for_comparability():
    """V1 дословно совпадает с Day 1 (сопоставимость) — защита от дрейфа."""
    fact = _facts()[0]
    p = _mod._prompt(fact, "code_first", version="v1")
    assert p.endswith("Does the claim appear supported by these anchors?")


def test_prompt_ru_no_leak_and_contains_claim():
    """RU-инструкция (контроль языка): leak-guard + claim на месте."""
    fact = _facts()[0]
    for arm in ("memory_first", "code_first"):
        p = _mod._prompt(fact, arm, version="v2", lang="ru")
        assert fact["claim"] in p
        assert "truth" not in p
        _mod._assert_no_truth_leak(fact, p)
    # память без кода — RU-формулировка
    assert "Память содержит это утверждение" in _mod._prompt(fact, "memory_first", lang="ru")
    # v2 нейтральное правило — RU
    assert "Возвращайте true ТОЛЬКО если" in _mod._prompt(fact, "code_first", version="v2", lang="ru")


def test_prompt_ru_v1_leading_question():
    """RU v1 тоже наводящий (зеркало EN) — контраст с v2."""
    fact = _facts()[0]
    assert "Подтверждают ли эти якоря" in _mod._prompt(fact, "code_first", version="v1", lang="ru")


def test_progress_path_tag_distinct():
    """--tag v2 не должен затирать v1-прогресс (разные файлы)."""
    assert _mod._progress_path("qwen/qwen3.7-flash") != _mod._progress_path("qwen/qwen3.7-flash", "v2_en")
    assert str(_mod._progress_path("qwen/qwen3.7-flash", "v2_en")).endswith("live_arm_1L_progress_v2_en_qwen_qwen3.7-flash.json")


# ─── Нормализация и парсинг вердиктов ───────────────────────────────────────
def test_normalize_verdict_valid_and_invalid():
    assert _mod._normalize_verdict({"verdict": "true"}) == "true"
    assert _mod._normalize_verdict({"verdict": "false"}) == "false"
    assert _mod._normalize_verdict({"verdict": "unknown"}) == "unknown"
    assert _mod._normalize_verdict({"verdict": "maybe"}) == "unknown"
    assert _mod._normalize_verdict({}) == "unknown"
    assert _mod._normalize_verdict(None) == "unknown"


def test_normalize_verdict_case_and_bool():
    """Red Team fix: True/TRUE (case) и true (JSON boolean) — валидные вердикты."""
    assert _mod._normalize_verdict({"verdict": "True"}) == "true"
    assert _mod._normalize_verdict({"verdict": "TRUE"}) == "true"
    assert _mod._normalize_verdict({"verdict": "False"}) == "false"
    assert _mod._normalize_verdict({"verdict": True}) == "true"   # JSON boolean
    assert _mod._normalize_verdict({"verdict": False}) == "false"
    assert _mod._normalize_verdict({"verdict": " unknown "}) == "unknown"  # пробелы


def test_extract_verdict_json_plain():
    assert _mod._extract_verdict_json('{"verdict": "true"}') == {"verdict": "true"}


def test_extract_verdict_json_capitalized():
    """Red Team fix: заглавные True/False не должны теряться как unknown."""
    assert _mod._extract_verdict_json('{"verdict": "True"}') == {"verdict": "true"}
    assert _mod._extract_verdict_json('{"verdict": "FALSE"}') == {"verdict": "false"}


def test_extract_verdict_json_boolean():
    """Red Team fix: JSON-булев verdict (без кавычек) парсится."""
    assert _mod._extract_verdict_json('{"verdict": true}') == {"verdict": "true"}
    assert _mod._extract_verdict_json('The answer is "verdict": false.') == {"verdict": "false"}


def test_extract_verdict_json_markdown_fence():
    content = 'Here is the answer:\n```json\n{"verdict": "false"}\n```\nDone.'
    assert _mod._extract_verdict_json(content) == {"verdict": "false"}


def test_extract_verdict_json_regex_fallback():
    content = 'Sure! The verdict is "verdict": "unknown" — no tools used.'
    assert _mod._extract_verdict_json(content) == {"verdict": "unknown"}


def test_extract_verdict_json_garbage():
    assert _mod._extract_verdict_json("no json here at all") is None
    assert _mod._extract_verdict_json("") is None


# ─── Статистика: Wilson CI ──────────────────────────────────────────────────
def test_wilson_ci_zero_n():
    assert _mod._wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_ci_n50_p50():
    # Точное значение Wilson 95% CI для 25/50: [0.3664, 0.6336]
    lo, hi = _mod._wilson_ci(25, 50)
    assert lo > 0.36 and hi < 0.64, f"Wilson CI для 25/50 должен быть ≈[0.366,0.634], получили [{lo},{hi}]"


def test_rate_fields():
    r = _mod._rate(5, 50)
    assert r["k"] == 5 and r["n"] == 50 and r["rate"] == 0.1
    assert len(r["ci95"]) == 2 and 0.0 <= r["ci95"][0] <= r["ci95"][1] <= 1.0


def test_summarize_empty():
    s = _mod._summarize([], "memory_first", "openrouter", "qwen/qwen3.7-flash")
    assert s["n"] == 0
    assert s["adoption"]["rate"] == 0.0
    assert s["usage"]["calls"] == 0


def test_summarize_known_math():
    """Синтетический набор из 50 вердиктов: проверка всех метрик вручную."""
    results = []
    # 10 truth=true, verdict=true  → true_accept
    # 5  truth=false, verdict=true → false_accept
    # 30 truth=false, verdict=false → correct (decided)
    # 5  verdict=unknown
    for i, (truth, verdict) in enumerate([
        *[(True, "true")] * 10, *[(False, "true")] * 5,
        *[(False, "false")] * 30, *[(True, "unknown")] * 5,
    ]):
        results.append({"id": f"R{i:02d}", "truth": truth, "verdict": verdict,
                        "error": "", "prompt_tokens": 200, "completion_tokens": 50})
    s = _mod._summarize(results, "code_first", "openrouter", "deepseek/deepseek-v4-flash")
    assert s["n"] == 50
    assert s["adoption"]["k"] == 15 and s["adoption"]["rate"] == pytest.approx(0.3)
    assert s["false_accept"]["k"] == 5 and s["false_accept"]["rate"] == pytest.approx(0.1)
    assert s["true_accept"]["k"] == 10
    assert s["unknown_rate"]["k"] == 5 and s["unknown_rate"]["rate"] == pytest.approx(0.1)
    # decided = 45 (10 true + 35 false-verdict), correct = 10 + 30 = 40
    assert s["accuracy_decided"]["k"] == 40 and s["accuracy_decided"]["n"] == 45
    assert s["accuracy_decided"]["rate"] == pytest.approx(40 / 45)
    assert s["false_accept_ids"] == ["R10", "R11", "R12", "R13", "R14"]
    assert s["usage"]["prompt_tokens"] == 50 * 200
    assert s["usage"]["completion_tokens"] == 50 * 50
    # deepseek-v4-flash: 0.14/0.28 $/1M → 10k pt + 2.5k ct
    assert s["usage"]["est_cost_usd"] == pytest.approx(0.14 * 10000 / 1e6 + 0.28 * 2500 / 1e6)


def test_summarize_unknown_model_cost_none():
    results = [{"id": "R01", "truth": True, "verdict": "true", "error": "",
                "prompt_tokens": 10, "completion_tokens": 5}]
    s = _mod._summarize(results, "memory_first", "api", "big-pickle")
    assert s["usage"]["est_cost_usd"] is None  # нет цены → честное n/a


def test_summarize_counts_truncation():
    """Red Team fix: finish_reason=length учитывается отдельно от честного unknown."""
    results = [
        {"id": "R01", "truth": True, "verdict": "unknown", "error": "",
         "prompt_tokens": 10, "completion_tokens": 5, "finish_reason": "length"},
        {"id": "R02", "truth": True, "verdict": "unknown", "error": "",
         "prompt_tokens": 10, "completion_tokens": 5, "finish_reason": "stop"},
    ]
    s = _mod._summarize(results, "memory_first", "openrouter", "qwen/qwen3.7-flash")
    assert s["truncated"] == 1
    assert s["unknown_rate"]["k"] == 2  # оба unknown, но truncation видна отдельно


def test_summarize_usage_cache_and_reasoning():
    """Cache/reasoning/actual-cost фиксируются (аудит цены и reasoning-параметра)."""
    results = [
        {"id": "R01", "truth": True, "verdict": "true", "error": "",
         "prompt_tokens": 100, "completion_tokens": 8, "finish_reason": "stop",
         "cost": 1.18e-05, "cached_tokens": 95, "reasoning_tokens": 0},
        {"id": "R02", "truth": False, "verdict": "unknown", "error": "",
         "prompt_tokens": 100, "completion_tokens": 8, "finish_reason": "stop",
         "cost": 4.56e-06, "cached_tokens": 100, "reasoning_tokens": 0},
    ]
    s = _mod._summarize(results, "code_first", "openrouter", "z-ai/glm-4.7-flash")
    u = s["usage"]
    assert u["cached_tokens"] == 195
    assert u["reasoning_tokens"] == 0
    assert u["actual_cost_usd"] == round(1.18e-05 + 4.56e-06, 6)
    assert u["est_cost_usd"] is not None  # оценочная цена тоже есть (fallback)
    assert s["truncated"] == 0


# ─── Целостность датасета (академическая воспроизводимость) ────────────────
def test_facts_dataset_n50_and_ids():
    data = json.loads(_mod.FACTS.read_text(encoding="utf-8"))
    facts = data["facts"]
    assert len(facts) == 50
    ids = [f["id"] for f in facts]
    assert ids == [f"R{i:02d}" for i in range(1, 51)]
    assert data["_meta"]["mix"]["n_total"] == 50


def test_facts_fingerprint_stable():
    data = json.loads(_mod.FACTS.read_text(encoding="utf-8"))
    assert _mod._facts_fingerprint(data) == _mod._facts_fingerprint(data)


def test_pricing_has_qwen_37_flash():
    """Защита от дрейфа: модель по умолчанию обязана быть в прайс-таблице."""
    assert "qwen/qwen3.7-flash" in _mod.PRICING_PER_1M
    assert _mod.DEFAULT_OPENROUTER_MODEL == "qwen/qwen3.7-flash"


# ─── Reasoning-флаг (V3/CoT-рука, Part 5) ──────────────────────────────────
def test_reasoning_flag_sets_body(monkeypatch):
    """--reasoning → reasoning.enabled=true в body; --no-reasoning → false; оба off → нет ключа."""
    import httpx

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json

        class R:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": '{"verdict":"true"}'},
                                      "finish_reason": "stop"}], "usage": {}}

        return R()

    monkeypatch.setattr(httpx, "post", fake_post)

    # явное включение (CoT-рука)
    r = _mod._api_verdict("p", "k", "m", "https://x", 500, 42, False, "en", reasoning=True)
    assert r["verdict"] == "true"
    assert captured["body"]["reasoning"] == {"enabled": True}
    assert captured["body"]["max_tokens"] == 500

    # отключение (zero-shot, каноническая рука)
    _mod._api_verdict("p", "k", "m", "https://x", 100, 42, True, "en", reasoning=False)
    assert captured["body"]["reasoning"] == {"enabled": False}

    # ни один флаг — параметр не передаётся (дефолт модели)
    _mod._api_verdict("p", "k", "m", "https://x", 100, 42, False, "en")
    assert "reasoning" not in captured["body"]


def test_new_report_reasoning_mode():
    """Конфиг различает три режима reasoning: off / on / default (аудит CoT-руки)."""
    import argparse

    facts = _facts()[:50]
    for no_reasoning, reasoning, expected in [(True, False, "off"), (False, True, "on"), (False, False, "default")]:
        args = argparse.Namespace(
            provider="openrouter", arm="both", max_tokens=500, seed=42,
            no_reasoning=no_reasoning, reasoning=reasoning,
            prompt_version="v2", prompt_lang="en", tag="v3_cot")
        cfg = _mod._new_report(args, "https://openrouter.ai/api/v1",
                               "qwen/qwen3.7-flash", facts, "abc")["config"]
        assert cfg["reasoning_mode"] == expected
        assert cfg["reasoning_enabled"] is (not no_reasoning)


# ─── Конфигурация эксперимента ──────────────────────────────────────────────
def test_config_fingerprint_fields():
    """Отчёт обязан нести fingerprint конфига — иначе результат невоспроизводим."""
    import argparse

    args = argparse.Namespace(
        provider="openrouter", arm="both", max_tokens=100, seed=42,
        no_reasoning=True, prompt_version="v1", prompt_lang="en", tag="")
    facts = _facts()[:50]
    report = _mod._new_report(args, "https://openrouter.ai/api/v1",
                              "qwen/qwen3.7-flash", facts, "abc123")
    cfg = report["config"]
    for field in ("temperature", "seed", "max_tokens", "response_format",
                  "reasoning_enabled", "prompt_version", "arms",
                  "facts_source", "facts_sha256", "facts_count"):
        assert field in cfg
    assert cfg["max_tokens"] == 100
    assert cfg["reasoning_enabled"] is False
    assert cfg["facts_count"] == 50
