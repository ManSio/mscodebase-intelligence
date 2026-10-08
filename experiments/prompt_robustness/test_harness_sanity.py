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
    assert ru == pytest.approx(29 / 30, abs=1e-4), f"ru={ru} — падение не локализовано"
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
            # Именно PlantedBreakTransport.ask: super(PlantedBreakTransport, self)
            # перепрыгивал бы сам класс и попал в базовый Transport → NotImplementedError.
            return PlantedBreakTransport.ask(self, prompt, model, workdir)

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


# ── C2c: контрольная рука обязана выносить вердикт ───────────────────────────
def test_planted_control_now_produces_a_verdict_not_na():
    """Раньше decide() отдавал N/A для не-cli рук, и посадка поломки в 1/30
    (=0.9667 > порога 0.90) давала exit 0: контроль не мог сообщить, что
    гейт не заметил бы и более широкую поломку. Теперь — CONTROL_OK/CONTROL_FAIL."""
    data = load_dataset()
    from run_experiment import run_model

    target = data["aggregate"][0].prompts["ru"]["paraphrases"][0]
    tr = PlantedBreakTransport(data["cases"], break_prompt=target)
    rep = run_model(tr, "ctl/planted", data, base_repeats=2)

    dec = decide(rep)
    assert dec["arm"] == "planted"
    assert dec["verdict"] == "CONTROL_OK", dec
    assert dec["injected_hits"] == 1
    assert dec["disagreeing_rows"] == 1


def test_planted_control_fails_when_break_was_never_injected():
    """Fail-closed: если поломка не внесена, контроль ПРОВАЛЕН, а не «неприменим».
    Наличие поломки и её обнаружение — разные утверждения (§19 P-016)."""
    data = load_dataset()
    from run_experiment import run_model

    tr = PlantedBreakTransport(data["cases"], break_prompt="<никогда не спросят>")
    rep = run_model(tr, "ctl/planted", data, base_repeats=2)

    dec = decide(rep)
    assert dec["verdict"] == "CONTROL_FAIL", dec
    assert any("never injected" in r for r in dec["reasons"]), dec


def test_planted_control_fails_when_gate_is_blind_to_the_break():
    """Поломка внесена, но гейт её не увидел (инвариантность 1.0) → CONTROL_FAIL.
    Это тот сценарий, ради которого контроль и существует."""
    from run_experiment import decide_control

    rep = {
        "transport": "planted_break",
        "control": {"kind": "planted_break", "injected_hits": 1},
        "per_lang": {"ru": {"invariance_given_base_correct": 1.0,
                            "invariance_given_base_correct_den": 30}},
        "rows": [{"case": "c", "lang": "ru", "which": "p0",
                  "agrees_with_base": True}],
    }
    dec = decide_control(rep)
    assert dec["verdict"] == "CONTROL_FAIL", dec
    assert any("blind" in r for r in dec["reasons"]), dec


def test_oracle_control_detects_perfect_invariant_arm():
    data = load_dataset()
    from run_experiment import run_model, OracleTransport

    rep = run_model(OracleTransport(data["cases"]), "ctl/oracle", data, base_repeats=2)
    dec = decide(rep)
    assert dec["arm"] == "oracle"
    assert dec["verdict"] == "CONTROL_OK", dec


def test_oracle_control_fails_when_an_arm_is_broken():
    from run_experiment import decide_control

    rep = {
        "transport": "oracle",
        "control": {"kind": "oracle"},
        "per_lang": {"ru": {"invariance_given_base_correct": 0.9,
                            "invariance_given_base_correct_den": 30}},
        "rows": [],
    }
    assert decide_control(rep)["verdict"] == "CONTROL_FAIL"


# ── C5: структурные правила обязаны различать контекст ──────────────────────
def test_structured_rule_separates_boiling_from_freezing():
    """Одно и то же число «100 градусов» — верный ответ про кипение и неверный
    про замерзание. Наивный any_of по числу считал бы оба верными."""
    from run_experiment import extract_fact

    fact = {"rule": {"kind": "value_context",
                     "anchor": ["100"], "require": ["кип", "boil"],
                     "reject": ["замерз", "freeze"]}}
    assert extract_fact("Вода кипит при 100 градусов Цельсия.", fact) is True
    assert extract_fact("Water boils at 100 degrees Celsius.", fact) is True
    assert extract_fact("Вода замерзает при 100 градусах Цельсия.", fact) is False
    assert extract_fact("Water freezes at 100 degrees Celsius.", fact) is False
    assert extract_fact("Вода кипит при 90 градусах Цельсия.", fact) is False


def test_subject_value_rule_rejects_unrelated_year_context():
    """Год «1991» встречается и в ответе про Python, и в постороннем контексте.
    Требование близости предмета — единственное, что их различает."""
    from run_experiment import extract_fact

    fact = {"rule": {"kind": "subject_value", "subject": ["python"],
                     "value_regex": [r"\b1991\b"], "bare": True,
                     "bare_values": ["1991"], "window": 80}}
    assert extract_fact("Первый релиз Python вышел в 1991 году.", fact) is True
    assert extract_fact("В 1991 году был выпущен первый релиз Python.", fact) is True
    assert extract_fact("1991.", fact) is True, "голый год — тоже верный ответ"
    assert extract_fact("В 1991 году вышел первый релиз Ruby.", fact) is False
    assert extract_fact("In 1991, the Titanic sank.", fact) is False
    assert extract_fact("Первый релиз Python вышел в 1990 году.", fact) is False


def test_last_mention_rule_handles_hedged_then_corrected_answer():
    """Модель называет направление, потом оговаривает: «Против градиента
    двигаться нельзя, поэтому шаг по градиенту». Первое слово — не ответ,
    решение даёт последнее упоминание."""
    from run_experiment import extract_fact

    fact = {"rule": {"kind": "last_mention",
                     "accept": ["против градиента", "downhill"],
                     "reject": ["по градиенту", "along the gradient"]}}
    assert extract_fact("Против градиента.", fact) is True
    assert extract_fact("It moves downhill.", fact) is True
    assert extract_fact("По градиенту.", fact) is False
    assert extract_fact("Along the gradient.", fact) is False
    assert extract_fact("Против градиента двигаться нельзя, поэтому шаг делается "
                        "по градиенту.", fact) is False
    assert extract_fact("The negative gradient direction is unavailable, so it "
                        "moves along the gradient.", fact) is False


def test_numeric_anchor_respects_word_boundaries():
    """Якорь «2» не должен ловиться внутри «2000» — иначе smallest_prime
    начнёт «видеть» факт в любом четырёхзначном числе."""
    from run_experiment import extract_fact

    fact = {"rule": {"kind": "value_context", "anchor": ["2"],
                     "require": ["прост", "prime"], "bare": True}}
    assert extract_fact("2", fact) is True
    assert extract_fact("Наименьшее простое число — 2.", fact) is True
    assert extract_fact("The year 2000 is prime in this text.", fact) is False


def test_yo_normalization_is_consistent_across_matcher_paths():
    """Legacy-путь (any_of) и структурный путь обязаны нормализовать «ё» одинаково.
    Иначе «не нашёл» не находится алиасом «не нашел» — молчаливый FN."""
    from run_experiment import extract_fact

    legacy = {"any_of": ["не нашел"]}
    assert extract_fact("Сервер не нашёл запрошенный ресурс.", legacy) is True
    structured = {"rule": {"kind": "value_context", "anchor": ["нашел"],
                           "require": ["сервер"]}}
    assert extract_fact("Сервер не нашёл запрошенный ресурс.", structured) is True


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
    # Граница порога: ровно 0.90 — ещё не провал, но и не строгая устойчивость.
    assert decide(_fake(THRESHOLD))["verdict"] == "CONDITIONAL_PASS"
    assert decide(_fake(THRESHOLD - 0.01))["verdict"] == "FAIL"


def test_strict_vs_conditional_pass():
    """СТРОГО (1.0) и С УСЛОВИЕМ (>=0.90, но не 1.0) — разные утверждения.
    Раньше обе строки сводились к PASS, и «почти устойчива» читалась как «устойчива»."""
    strict = decide(_fake(1.0))
    assert strict["verdict"] == "STRICT_PASS"
    cond = decide(_fake(0.95))
    assert cond["verdict"] == "CONDITIONAL_PASS"
    assert cond["needs_manual_review"] is True
    assert "review_rows" in cond, "CONDITIONAL_PASS обязан называть строки для разбора"


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
    """Уровень процесса: exit 2, а не rc=0 с «0% устойчивости» (T10).

    Прежняя версия создавала битый файл, но НЕ передавала его харнессу и
    утверждала `returncode in (0,1,2)` — то есть проходила всегда (вакуумный тест).
    Теперь битый датасет действительно подкладывается и код проверяется точно."""
    bad = tmp_path / "broken.json"
    bad.write_text(json.dumps({"schema_version": "x", "cases": []}), encoding="utf-8")
    p = _run_harness("--transport", "oracle", "--dataset", str(bad))
    assert p.returncode == 2, (
        f"битый/пустой датасет → ровно 2, получено {p.returncode}: {p.stderr[:200]}"
    )

    ok = _run_harness("--transport", "oracle", "--out", str(tmp_path / "ctl_ok.json"))
    assert ok.returncode == 0, (
        f"корректный датасет + контрольная рука → 0, получено {ok.returncode}"
    )


# ── A1–A5: регрессии, найденные на ЖИВОМ пилоте 2026-10-02 ────────────────────
# Каждая из этих правок закрывает баг, который дал бы ложно-зелёный отчёт.


def test_rows_contain_both_languages_and_base_cells():
    """rows — единственный источник истины. Нет base-строк или только один
    язык в отчёте → метрики недоказуемы, число нельзя перевывести из сырья."""
    data = load_dataset()
    from run_experiment import OracleTransport, run_model

    rep = run_model(OracleTransport(data["cases"]), "ctl/oracle", data, base_repeats=3)
    assert {r["lang"] for r in rep["rows"]} == {"ru", "en"}, "в rows не обе языковые руки"
    whichs = {r["which"] for r in rep["rows"]}
    assert {"base0", "base1", "base2"} <= whichs, f"нет base-повторов: {sorted(whichs)}"
    assert {"p0", "p1", "p2"} <= whichs, f"нет парафраз: {sorted(whichs)}"
    assert len(rep["rows"]) == 10 * 6 * 2, f"строк {len(rep['rows'])}, ожидалось 120"


def test_seed_stability_is_consistency_not_correctness():
    """Стабильно-неверная модель: base_accuracy = 0.0, но seed_stability = 1.0.
    Прежний код считал долю верных и путал две разные величины (A3)."""
    data = load_dataset()
    from run_experiment import Reply, run_model

    class AlwaysWrong:
        name = "wrong"

        def ask(self, prompt, model, workdir):
            return Reply("Atlantis — столица Франции.", self.name, "ok")

    rep = run_model(AlwaysWrong(), "ctl/wrong", data, base_repeats=3)
    for lang, m in rep["per_lang"].items():
        assert m["base_accuracy"] == 0.0, f"{lang}: base_acc должен быть 0.0"
        assert m["seed_stability"] == 1.0, (
            f"{lang}: стабильно-неверная модель обязана давать seed_stability=1.0, "
            f"получено {m['seed_stability']}"
        )


def test_seed_stability_detects_real_instability():
    data = load_dataset()
    from run_experiment import Reply, run_model

    class Flaky:
        name = "flaky"

        def __init__(self):
            self.n = 0

        def ask(self, prompt, model, workdir):
            self.n += 1
            return Reply("???" if self.n % 3 == 0 else "Paris.", self.name, "ok")

    rep = run_model(Flaky(), "ctl/flaky", data, base_repeats=3)
    seeds = [m["seed_stability"] for m in rep["per_lang"].values()]
    assert min(seeds) < 1.0, f"нестабильность не поймана: {seeds}"


def test_base_accuracy_counts_correctness_not_validity():
    """Прежний код делал base_correct += int(valid_base), то есть СЧИТАЛ ВАЛИДНОСТЬ
    и объявлял base_accuracy=1.0 у модели, которая не ответила ни на один вопрос."""
    data = load_dataset()
    from run_experiment import Reply, run_model

    class AllValidAllWrong:
        name = "wrong2"

        def ask(self, prompt, model, workdir):
            return Reply("здесь нет никакого ответа", self.name, "ok")

    rep = run_model(AllValidAllWrong(), "ctl/w2", data, base_repeats=3)
    for lang, m in rep["per_lang"].items():
        assert m["responses_total"] > 0, f"{lang}: ответы не учтены"
        assert m["base_accuracy"] == 0.0, f"{lang}: base_acc={m['base_accuracy']} — считается валидность"


def test_row_text_is_not_truncated():
    """Обрезка text[:400] прятала отличие длинных ответов от коротких — а это
    ровно тот случай, где устойчивость к формулировке и проявляется."""
    data = load_dataset()
    from run_experiment import Reply, run_model

    long_text = "A" * 1500

    class Long:
        name = "long"

        def ask(self, prompt, model, workdir):
            return Reply(long_text, self.name, "ok")

    rep = run_model(Long(), "ctl/long", data, base_repeats=2)
    # Только ПАРАФРАЗЫ: base-строки пишутся из r.text напрямую и не обрезаются,
    # поэтому max() по всем строкам остался бы 1500 даже при обрезанных парафразах.
    texts = [r["text"] for r in rep["rows"]
             if r["text"] and str(r.get("which", "")).startswith("p")]
    assert texts, "в rows нет текстов парафраз"
    assert max(len(t) for t in texts) == len(long_text), (
        f"текст парафразы обрезан: максимум {max(len(t) for t in texts)} "
        f"вместо {len(long_text)}"
    )


def test_decide_fails_when_one_language_is_below_threshold():
    """Усреднение маскировало RU-провал идеальным EN: mean(0.89, 1.0) = 0.945 → PASS,
    и вердикт противоречил собственному reasons (A1)."""
    report = {
        "transport": "cli",
        "per_lang": {
            "ru": {"invariance_given_base_correct": 0.89,
                   "invariance_given_base_correct_den": 30},
            "en": {"invariance_given_base_correct": 1.0,
                   "invariance_given_base_correct_den": 30},
        },
    }
    dec = decide(report)
    assert dec["verdict"] == "FAIL", f"вердикт {dec}"
    assert dec["failed_langs"] == ["ru"], dec
    assert "mean_invariance_descriptive" in dec, "среднее остаётся лишь описательной величиной"


def _run_harness(*args: str) -> subprocess.CompletedProcess:
    """Дочерний процесс печатает кириллицу в OEM-кодировку консоли Windows, поэтому
    кодировку вывода надо задавать явно, иначе декодирование падает UnicodeDecodeError."""
    import os

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(HERE / "run_experiment.py"), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env, errors="replace")


def test_exit_code_3_for_unknown_and_2_only_for_population(tmp_path):
    """UNKNOWN («не смогли измерить») не должен делить код 2 с ошибкой входа (A4),
    а провал контрольной руки — это провал (1), а не «не применимо» (0).

    Раньше контрольные руки давали N/A → exit 0, и посадка поломки 1/30 при пороге
    0.90 была неотличима от успеха: гейт не мог сообщить о собственной слепоте."""
    from run_experiment import exit_code_for

    assert exit_code_for(["FAIL"]) == 1
    assert exit_code_for(["CONTROL_FAIL"]) == 1, "провал контроля — провал, не успех"
    assert exit_code_for(["STRICT_PASS"]) == 0
    assert exit_code_for(["CONDITIONAL_PASS"]) == 0
    assert exit_code_for(["CONTROL_OK"]) == 0
    assert exit_code_for(["CONTROL_OK", "CONTROL_FAIL"]) == 1
    assert exit_code_for(["UNKNOWN"]) == 3, "не смогли измерить → 3"
    assert exit_code_for(["STRICT_PASS", "UNKNOWN"]) == 3
    assert exit_code_for(["CONDITIONAL_PASS", "FAIL"]) == 1
    assert exit_code_for(["FAIL", "UNKNOWN"]) == 1, "пвал важнее «не измерили»"

    # UNKNOWN действительно возникает при малом знаменателе на cli-отчёте.
    tiny = {
        "transport": "cli",
        "per_lang": {"ru": {"invariance_given_base_correct": None,
                            "invariance_given_base_correct_den": 3}},
    }
    assert decide(tiny)["verdict"] == "UNKNOWN"
    assert exit_code_for([decide(tiny)["verdict"]]) == 3

    # Уровень процесса: пустой датасет → ровно 2.
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"schema_version": "2.0", "cases": []}), encoding="utf-8")
    r = _run_harness("--transport", "oracle", "--dataset", str(empty))
    assert r.returncode == 2, (
        f"пустой датасет → 2, получено {r.returncode}: {r.stderr[:200]}"
    )


def test_control_arm_exit_code_is_zero(tmp_path):
    """Контрольная рука обязана ВЫНОСИТЬ ВЕРДИКТ, а не отдавать N/A.

    N/A был не «нейтрально», а маскировкой: посадка поломки в 1/30 (=0.967) при
    пороге 0.90 давала N/A → exit 0, то есть контроль физически не мог сообщить,
    что гейт не заметил бы и 2/30. Теперь oracle → CONTROL_OK → 0."""
    out = tmp_path / "ctl.json"
    r = _run_harness("--transport", "oracle", "--out", str(out))
    assert r.returncode == 0, f"контрольная рука → 0, получено {r.returncode}: {r.stderr[:300]}"
    payload = json.loads(out.read_text(encoding="utf-8"))
    verdict = payload["repeats"][0]["decision"]["verdict"]
    assert verdict == "CONTROL_OK", f"ожидался CONTROL_OK, получено {verdict}"


def test_planted_control_arm_exit_code_is_zero_when_break_is_caught(tmp_path):
    """Посаженная поломка, пойманная гейтом, — успех КОНТРОЛЯ (0),
    и она обязана быть видна в отчёте как найденная, а не как «неприменимо»."""
    out = tmp_path / "ctl_planted.json"
    r = _run_harness("--transport", "planted", "--out", str(out))
    assert r.returncode == 0, f"пойманная поломка → 0, получено {r.returncode}: {r.stderr[:300]}"
    payload = json.loads(out.read_text(encoding="utf-8"))
    dec = payload["repeats"][0]["decision"]
    assert dec["verdict"] == "CONTROL_OK", dec
    assert dec["injected_hits"] >= 1, "поломка должна быть реально внесена"


# ── разбор потоков CLI: ответ в stdout, баннер в stderr ──────────────────────
# Зафиксировано на РЕАЛЬНОМ вызове 2026-10-02 (opencode-go/longcat-2.0).
# Регрессия: харнесс склеивал stdout+stderr и вырезал «всё после баннера».
# Баннер идёт в stderr, поэтому «после баннера» — пусто, и ответ терялся:
# все 12 вызовов пилота пришли со статусом 'empty'.
OBSERVED_STDOUT = b"Venus comes directly after Mercury in the solar system.\n"
OBSERVED_STDERR_PLAIN = b"\n> build \xc2\xb7 longcat-2.0\n\x1b[0m\n"
OBSERVED_STDERR_PSWRAP = (
    b"opencode.cmd : \x1b[0m\r\nNativeCommandError\r\n\r\n"
    b"> build \xc2\xb7 longcat-2.0\r\n\x1b[0m\r\n"
)


def test_banner_is_not_in_stdout():
    from run_experiment import BUILD_MODEL
    assert not BUILD_MODEL.search(OBSERVED_STDOUT.decode("utf-8")), \
        "в ответе модели не должно быть служебного баннера"


def test_served_model_detected_from_stderr():
    from run_experiment import BUILD_MODEL
    for raw in (OBSERVED_STDERR_PLAIN, OBSERVED_STDERR_PSWRAP):
        m = BUILD_MODEL.search(raw.decode("utf-8", errors="replace"))
        assert m and m.group(1) == "longcat-2.0", f"баннер не распознан: {raw!r}"


def test_body_extraction_keeps_answer_when_banner_is_on_stderr():
    """Настоящий баг: тело бралось из склейки out+err, где баннер идёт ПОСЛЕ ответа."""
    from run_experiment import CliTransport

    strip = CliTransport._strip_banner
    merged = OBSERVED_STDOUT.decode() + "\n" + OBSERVED_STDERR_PLAIN.decode()
    assert "Venus" not in strip(merged), \
        "склейка out+err обязана ПОТЕРЯТЬ ответ — это и был баг"
    assert strip(OBSERVED_STDOUT.decode()).strip() == \
        "Venus comes directly after Mercury in the solar system.", \
        "из stdout ответ должен извлекаться целиком"


def test_powershell_wrapped_stderr_does_not_hide_the_answer():
    from run_experiment import CliTransport

    got = CliTransport._strip_banner(OBSERVED_STDERR_PSWRAP.decode("utf-8", errors="replace"))
    assert "build" not in got, f"баннер не вырезан: {got!r}"


def test_body_is_taken_from_stdout_not_from_merged_streams():
    """Структурный guard: тело обязано извлекаться из stdout, а диагноз 'empty'
    нести оба потока — иначе сбой неотличим от «модель промолчала»."""
    import inspect

    from run_experiment import CliTransport
    src = inspect.getsource(CliTransport.ask)
    assert "self._strip_banner(out_text)" in src, \
        "тело обязано извлекаться из stdout (баннер живёт в stderr)"
    assert "stdout=" in src and "stderr=" in src, \
        "диагноз 'empty' должен включать оба потока"


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
