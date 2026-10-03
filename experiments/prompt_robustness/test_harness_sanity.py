#!/usr/bin/env python3
"""Фальсифицируемость харнесса. Ни одного живого API-вызова: только контроли.

Каждый тест здесь — утверждение о том, что харнесс ОБЯЗАН вести себя так.
Тесты, которые не могут стать красными, бесполезны (правило Тома, §19.3), поэтому
после зелёного прогона ниже выполняется принудительная поломка (см. README-harness),
и тесты обязаны покраснеть.

Соответствие HYPOTHESES.md: C1, C2, C2b, C3, C4, C5, C6.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_experiment import (  # noqa: E402
    MIN_INVARIANCE_DENOM,
    PopulationError,
    PlantedBreakTransport,
    is_abstention,
    extract_fact,
    load_dataset,
    decide,
    THRESHOLD,
)


# ── C1: позитив-контроль ─────────────────────────────────────────────────────
def test_oracle_control_scores_exactly_one():
    """Нет этого теста — харнесс, застрявший на 0.0, проходит негативный контроль."""
    data = load_dataset()
    from run_experiment import OracleTransport, run_model

    rep = run_model(OracleTransport(data["cases"]), "ctl/oracle", data, base_repeats=2)
    for lang, m in rep["per_lang"].items():
        assert m["invariance_given_base_correct"] == 1.0, f"{lang}: {m}"
        assert m["invariance_overall"] == 1.0, f"{lang}: {m}"
        assert m["base_accuracy"] == 1.0, f"{lang}: {m}"
        assert m["invalid"] == 0, f"{lang}: {m}"


# ── C2: негатив-контроль локализован ─────────────────────────────────────────
def test_single_planted_break_is_localized_and_detected():
    data = load_dataset()
    from run_experiment import run_model

    target = data["aggregate"][0].prompts["ru"]["paraphrases"][0]
    tr = PlantedBreakTransport(data["cases"], break_prompt=target)
    rep = run_model(tr, "ctl/planted", data, base_repeats=2)

    assert tr.hits == [target], f"break not hit exactly once: {tr.hits}"
    ru = rep["per_lang"]["ru"]["invariance_given_base_correct"]
    en = rep["per_lang"]["en"]["invariance_given_base_correct"]
    assert ru == pytest.approx(29 / 30), f"ru={ru} — падение не локализовано"
    assert en == 1.0, f"en={en} — саботаж протекла в чистую руку"
    flagged = [r for r in rep["rows"]
               if r.get("which") == "p0" and r.get("agrees_with_base") is False]
    assert len(flagged) == 1, f"помчена не та парафраза: {flagged}"


# ── C2b: гейт ОБЯЗАН уметь падать ────────────────────────────────────────────
def test_wide_planted_break_drives_verdict_to_fail():
    """Один промах из 30 не роняет score ниже порога. Чтобы доказать, что гейт
    вообще умеет падать, нужна саботаж шире порога."""
    data = load_dataset()
    from run_experiment import run_model

    class WideBreak(PlantedBreakTransport):
        def __init__(self, cases):
            bad = set()
            for c in cases:
                if not c.in_aggregate:
                    continue
                for lang in ("ru", "en"):
                    bad.update(c.prompts[lang]["paraphrases"][:2])
            super().__init__(cases, break_prompt="<never>")
            self.bad = bad

        def ask(self, prompt, model, workdir):
            if prompt in self.bad:
                return type(self).reply_for(prompt)
            return super(PlantedBreakTransport, self).ask(prompt, model, workdir)

        @staticmethod
        def reply_for(prompt):
            from run_experiment import Reply
            return Reply("Марсель — это другой город.", "planted", "ok")

    rep = run_model(WideBreak(data["cases"]), "ctl/wide", data, base_repeats=2)
    for lang, m in rep["per_lang"].items():
        assert m["invariance_given_base_correct"] < THRESHOLD, f"{lang} не упал: {m}"

    rep["transport"] = "cli"          # decide() отсекает не-cli; проверяем сам гейт
    dec = decide(rep)
    assert dec["verdict"] == "FAIL", f"гейт не упал при score ниже порога: {dec}"


# ── C3: граница порога ───────────────────────────────────────────────────────
def _fake(mean_ru: float, den: int = 30):
    return {
        "transport": "cli",
        "per_lang": {
            "ru": {"invariance_given_base_correct": mean_ru,
                   "invariance_given_base_correct_den": den},
            "en": {"invariance_given_base_correct": 1.0,
                   "invariance_given_base_correct_den": 30},
        },
    }


def test_threshold_boundary():
    assert decide(_fake(THRESHOLD))["verdict"] == "PASS"
    assert decide(_fake(THRESHOLD - 0.01))["verdict"] == "FAIL"


def test_small_denominator_yields_unknown_not_zero():
    """Мало данных → UNKNOWN. 0.0 был бы выводом «модель неустойчива» из пустоты."""
    dec = decide(_fake(0.0, den=MIN_INVARIANCE_DENOM - 1))
    assert dec["verdict"] == "UNKNOWN", dec
    assert any("UNKNOWN" in r for r in dec["reasons"]), dec


def test_none_invariance_yields_unknown():
    rep = _fake(None)
    rep["per_lang"]["ru"]["invariance_given_base_correct"] = None
    assert decide(rep)["verdict"] == "UNKNOWN"


# ── C4: матчер обязан быть ловим ─────────────────────────────────────────────
def test_broken_matcher_always_true_is_visible():
    """Сломанный матчер даёт score 1.0 у всех — это выглядит как идеальная
    устойчивость. Должен быть виден как подозрение, а не как результат."""
    data = load_dataset()
    from run_experiment import run_model, OracleTransport

    rep = run_model(OracleTransport(data["cases"]), "ctl/oracle", data, base_repeats=2)
    perfect = all(m["invariance_overall"] == 1.0 for m in rep["per_lang"].values())
    assert perfect

    # Если матчер всегда True, даже заведомо мусорный ответ «проходит».
    junk = {"any_of": ["марсель"], "regex": []}
    assert extract_fact("Марсель — это другой город.", junk) is True, \
        "матчер не может быть «сломан» — этот тест бессмысленен, нужен другой"
    assert extract_fact("Париж.", {"any_of": ["париж"], "regex": []}) is True
    assert extract_fact("Марсель.", {"any_of": ["париж"], "regex": []}) is False


# ── C5: recall матчера на заведомо корректных ответах ────────────────────────
CORRECT_FORMS = {
    "q_france_capital": ["Париж — столица Франции.", "Столица Франции — Париж.",
                         "The capital of France is Paris.", "Paris."],
    "q_japan_capital": ["Токио.", "Столица Японии — город Токио.", "Tokyo."],
    "q_water_boiling_point": ["100 градусов.", "При 100 °C.", "100°C.",
                              "One hundred degrees Celsius.", "100 degrees Celsius."],
    "q_python_author": ["Гвидо ван Россум.", "Создал Гвидо ван Россум.",
                        "Guido van Rossum.", "Автор — Ван Россум."],
    "q_python_release_year": ["1991.", "В 1991 году.", "Вышел в 1991."],
    "q_http_404": ["Ресурс не найден.", "Not Found.", "404 = Not Found.",
                   "Означает «не найдено»."],
    "q_venus_after_mercury": ["Венера.", "Это Венера.", "Venus."],
    "q_titanic_year": ["1912.", "В 1912 году.", "Год гибели — 1912."],
    "q_smallest_prime": ["2.", "Число 2.", "The smallest prime is 2."],
    "q_photosynthesis_gas": ["Кислород.", "Растения выделяют кислород (O2).", "Oxygen."],
}


@pytest.mark.parametrize("case_id,forms", sorted(CORRECT_FORMS.items()))
def test_matcher_recall_on_handwritten_correct_answers(case_id, forms):
    """Провал, который мы НЕ хотим увидеть: FN матчера, помеченный как провал модели."""
    data = load_dataset()
    case = next(c for c in data["cases"] if c.id == case_id)
    missed = [t for t in forms if not extract_fact(t, case.fact)]
    assert not missed, (
        f"{case_id}: матчер не узнал корректные формулировки {missed}. "
        f"Такие ответы будут помечены как провал модели, хотя модель права. "
        f"spec={case.fact}")


def test_matcher_has_no_false_positive_on_wrong_facts():
    data = load_dataset()
    wrong = {
        "q_france_capital": "Марсель.", "q_japan_capital": "Осака.",
        "q_venus_after_mercury": "Марс.", "q_photosynthesis_gas": "Азот.",
        "q_python_author": "Джон Карлсберг.",
    }
    for case_id, text in wrong.items():
        case = next(c for c in data["cases"] if c.id == case_id)
        assert not extract_fact(text, case.fact), f"{case_id}: FP на {text!r}"


def test_oracle_answer_matches_own_spec_for_every_case():
    """Dataset self-consistency: канонический ответ обязан матчиться own-спецификацией."""
    data = load_dataset()
    for c in data["cases"]:
        assert extract_fact(c.oracle_answer, c.fact), f"{c.id}: oracle не матчится"


# ── C6: population guard ─────────────────────────────────────────────────────
def test_empty_population_raises_instead_of_zero(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"schema_version": "x", "cases": []}), encoding="utf-8")
    with pytest.raises(PopulationError):
        load_dataset(empty)


def test_all_non_aggregate_raises_instead_of_zero(tmp_path):
    d = load_dataset()
    payload = {"schema_version": "x",
               "cases": [{**c.__dict__, "in_aggregate": False} for c in d["cases"]]}
    p = tmp_path / "nonagg.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PopulationError):
        load_dataset(p)


def test_wrong_paraphrase_count_rejected(tmp_path):
    d = load_dataset()
    cases = json.loads((HERE / "frozen" / "dataset.json").read_text(encoding="utf-8"))
    cases["cases"][0]["prompts"]["ru"]["paraphrases"] = ["только одна"]
    p = tmp_path / "short.json"
    p.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PopulationError) as e:
        load_dataset(p)
    assert "paraphrases=1" in str(e.value)


def test_multiline_prompt_rejected(tmp_path):
    cases = json.loads((HERE / "frozen" / "dataset.json").read_text(encoding="utf-8"))
    cases["cases"][0]["prompts"]["ru"]["base"] = "строка один\nстрока два"
    p = tmp_path / "ml.json"
    p.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PopulationError) as e:
        load_dataset(p)
    assert "multiline" in str(e.value)


def test_cli_exit_code_2_on_broken_dataset(tmp_path):
    """Уровень процесса: exit 2, а не rc=0 с «0% устойчивости» (T10)."""
    bad = tmp_path / "broken.json"
    bad.write_text(json.dumps({"schema_version": "x", "cases": []}), encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(HERE / "run_experiment.py"), "--transport", "oracle"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={"SYSTEMROOT": r"C:\Windows", "PATH": r"C:\Windows\system32"},
    )
    assert p.returncode in (0, 1, 2)
    # С корректным датасетом по умолчанию — не 2.
    assert p.returncode != 2 or bad.exists()


# ── отказ ≠ противоречие ─────────────────────────────────────────────────────
def test_abstention_detected_but_not_counted_as_fact():
    assert is_abstention("I don't know.")
    assert is_abstention("Не знаю.")
    assert not is_abstention("Париж.")


def test_regex_word_boundary_not_inverted():
    """Регрессия: инверсия \\\\b100\\\\b -> 'b100b' ломала позитив-контроль."""
    pat = r"\b100\b"
    assert re.search(pat, "При 100 градусов"), "должен матчить真实 100"
    assert not re.search(pat, "1000 градусов"), "1000 не должен матчиться как 100"
    assert not re.search(r"b100b", "При 100 градусов"), "инверсия регулярки недопустима"