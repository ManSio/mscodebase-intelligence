# -*- coding: utf-8 -*-
"""Эксперимент: перенос evalmut-подхода (mutation testing for graders)
на детерминированный градер MSCodeBase — validate_scores/parse_scores_json
из src/providers/reranker/reranker_scoring.py.

Методика (evalmut):
  - "дыра" объявляется ТОЛЬКО из (вывод доказанно неверен AND градер пропустил),
    полюсность мутанта устанавливается против ground truth (контракт градера),
    а не из переворота вердикта.
  - Decline вместо guess: где полюсность установить нельзя — N/A.
  - Corroboration: два структурно непересекающихся мусорных входа.

Контракт validate_scores (ground truth):
  - index: int, порядковый номер чанка (0..N-1)
  - score: float в [0, 1]; вне диапазона — нормализуется clamp'ом (by design)
  - NaN/Infinity: НЕ число в [0,1] — дефект (против контракта "float score")
  - float index (2.7): не валидный порядковый номер — дефект
  - пустой/мусорный ответ: [] (SANITY — градер не vacuous)
"""
from __future__ import annotations

import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "src")

from providers.reranker.reranker_scoring import parse_scores_json, validate_scores

CAUGHT = "CAUGHT   "      # дефект отброшен — проверка сработала
MISSED = "MISSED   "      # дефект прошёл — BLIND SPOT (дыра)
OK = "OK       "          # мутант эквивалентен (не дефект) — градер прав
N_A = "N/A      "         # полюсность не установлена — decline

rows = []


def probe(name: str, raw: str, defect: bool, note: str = "") -> None:
    """Проба: если defect=True, ожидаем, что градер НЕ вернёт валидный скор."""
    try:
        result = parse_scores_json(raw)
    except Exception as exc:  # noqa: BLE001 — probe
        rows.append((name, f"EXC      {type(exc).__name__}: {exc}"))
        return
    if defect:
        status = MISSED if result else CAUGHT
    else:
        status = OK if result else N_A
    rows.append((name, f"{status} {note} -> {result}"))


def probe_scores(name: str, scores, defect: bool, note: str = "") -> None:
    try:
        result = validate_scores(scores)
    except Exception as exc:  # noqa: BLE001
        rows.append((name, f"EXC      {type(exc).__name__}: {exc}"))
        return
    if defect:
        status = MISSED if result else CAUGHT
    else:
        status = OK if result else N_A
    rows.append((name, f"{status} {note} -> {result}"))


print("=" * 78)
print("ЭКСПЕРИМЕНТ 1: мутационный скор validate_scores/parse_scores_json")
print("=" * 78)

# --- Каталог мутаций (адаптация операторов evalmut) ---

# json_value_type_flip: score строкой (evalmut: type flip)
probe_scores("type_flip_score_str", [{"index": 0, "score": "0.95"}],
             defect=True, note="score='0.95' (string)")
# json_value_corruption: NaN (Python json.loads принимает NaN!)
probe_scores("nan_score", [{"index": 0, "score": float("nan")}],
             defect=True, note="score=NaN")
# Infinity
probe_scores("inf_score", [{"index": 0, "score": float("inf")}],
             defect=True, note="score=Infinity")
# -infinity
probe_scores("neg_inf_score", [{"index": 0, "score": float("-inf")}],
             defect=True, note="score=-Infinity")
# index float — тихая порча int(2.7)=2
probe_scores("float_index", [{"index": 2.7, "score": 0.9}],
             defect=True, note="index=2.7 -> int()")
# index отрицательный
probe_scores("negative_index", [{"index": -1, "score": 0.9}],
             defect=True, note="index=-1")
# index вне диапазона (нет такого чанка) — парсер не знает N чанков:
# полюсность не устанавливается на этом слое (N/A-класс), guard — warning
# в apply_scores (см. ниже). Прямой вызов валидатора: вне контракта.
probe_scores("index_out_of_range", [{"index": 99, "score": 0.9}],
             defect=False, note="вне контракта validate_scores (N неизвестен)")
# Реальный путь: обёртка с осиротевшим индексом — парсер пропускает (не знает
# N), apply_scores логирует warning (диагностика, не тихая потеря)
probe("index_out_of_range_via_parser",
      '{"scores": [{"index": 0, "score": 0.9}, {"index": 99, "score": 1.0}]}',
      defect=False, note="проходит парсер, warning в apply_scores")
# score вне [0,1] — clamp by design => эквивалентный мутант (не дыра)
probe_scores("score_out_of_range_clamp", [{"index": 0, "score": 2.5}],
             defect=False, note="score=2.5 -> clamp (by design)")
# дубликат индекса — тихая перезапись (coverage gap: нет проверки уникальности)
probe("duplicate_index_via_parser",
      '{"scores": [{"index": 0, "score": 0.9}, {"index": 0, "score": 0.1}]}',
      defect=True, note="обёртка: дубликат -> decline (пути 1-3)")
# NaN через полный JSON-путь (попытка 1)
probe("nan_via_json", '{"scores": [{"index": 0, "score": NaN}]}',
      defect=True, note="json.loads принимает NaN")
# Infinity через полный JSON-путь
probe("inf_via_json", '{"scores": [{"index": 0, "score": Infinity}]}',
      defect=True, note="json.loads принимает Infinity")
# Неконсистентность путей: regex-путь (попытка 4) БЕЗ clamp'а
probe("regex_path_no_clamp", 'text {"index": 0, "score": 99.0} more text',
      defect=True, note="regex-path: score=99.0 НЕ клампится")
# Пример-скора в тексте объяснения (regex-путь берёт пример как настоящий скор)
probe("example_in_explanation",
      'Here is an example of the format: {"index": 0, "score": 0.95}. '
      "My actual scores are below.", defect=True,
      note="пример формата принят как реальный скор")
# SANITY: мусор -> [] (не vacuous)
probe("garbage", "I cannot provide scores in JSON format.", defect=False,
      note="gibberish -> [] (SANITY OK)")
# SANITY: пустой -> []
probe("empty", "", defect=False, note="пусто -> []")
# SANITY: пустой scores-массив
probe("empty_scores", '{"scores": []}', defect=False, note='scores: [] -> []')

print(f"\n{'мутация':<34} {'вердикт':<10} примечание")
print("-" * 78)
for name, line in rows:
    print(f"{name:<34} {line}")

caught = sum(1 for _, ln in rows if ln.startswith(CAUGHT))
missed = sum(1 for _, ln in rows if ln.startswith(MISSED))
n_a = sum(1 for _, ln in rows if ln.startswith(N_A))
ok = sum(1 for _, ln in rows if ln.startswith(OK))
total = len(rows)
print("-" * 78)
print(f"mutation score: {caught}/{caught + missed} caught"
      f" ({caught / (caught + missed):.0%} если считать только с полюсностью)")
print(f"BLIND SPOTS (дыры): {missed}")
print(f"эквивалентные (OK): {ok}, N/A (decline): {n_a}")

# =============================================================================
print()
print("=" * 78)
print("ЭКСПЕРИМЕНТ 2: decline-дисциплина — false positive замер")
print("=" * 78)
print("""
Вопрос: наивный подход («градер не упал/не отбросил = проверка работает»)
заявил бы false positive на правильно-скоупленной проверке clamp'а.
evalmut-инвариант требует: полюсность мутанта против ОБЪЯВЛЕННОГО контракта.

  Кейс A: score=2.5 -> clamp к 1.0.
    Контракт: «вне [0,1] нормализуется» (by design, как у логитов).
    Наивный подход: «вне диапазона, пропущен -> ДЫРА» — FALSE POSITIVE.
    evalmut: 2.5 — ЭКВИВАЛЕНТНЫЙ мутант (проверка правильно скоуплена). OK.

  Кейс B: score=NaN -> 1.0.
    Контракт: «score — float в [0,1]». NaN — НЕ число, это не "больше 1".
    Это НЕ эквивалентный мутант: NaN -> 1.0 = максимальный скор чанку,
    который LLM вообще не оценил. Реальная дыра.
""")
# Демонстрация: как clamp обрабатывает NaN (механика дыры)
nan_result = validate_scores([{"index": 0, "score": float("nan")}])
inf_result = validate_scores([{"index": 0, "score": float("inf")}])
print(f"механика: min(1.0, NaN) = {min(1.0, float('nan'))!r}")
print(f"validate_scores([NaN])    -> {nan_result}   <-- NaN отброшен (фикс: isfinite)")
print(f"validate_scores([inf])    -> {inf_result}   <-- Infinity отброшен (фикс: isfinite)")

# =============================================================================
print()
print("=" * 78)
print("ЭКСПЕРИМЕНТ 3: corroboration — два непересекающихся мусорных входа")
print("=" * 78)
garbage_a = "I cannot help with that request."
garbage_b = "8H@ac3%o zxqfp wgbrtl mnkvd"  # структурно иной мусор
ra = parse_scores_json(garbage_a)
rb = parse_scores_json(garbage_b)
print(f"garbage A -> {ra}")
print(f"garbage B -> {rb}")
print(f"corroboration: {'OK (оба пустые — градер не vacuous)' if not ra and not rb else '!!! один из мусоров дал валидные скоры'}")

# Контрпример: мусор с примером формата (нужен corroboration, иначе false vacuous)
example_text = ('Here is an example: {"index": 0, "score": 0.95} '
                "but I have no real scores")
re_ = parse_scores_json(example_text)
print(f"мусор с примером формата -> {re_}  <-- decline (фикс: единичный объект)")

# =============================================================================
# CI-guard (evalmut-перенос): exit-code — открытые дыры > 0 => exit 1.
# Используется как страж контракта градера в CI (см. .github/workflows/ci.yml).
# =============================================================================
if missed > 0:
    print(f"\nEVALMUT PROBE: FAILED — {missed} дыр(ы) остались открытыми")
    sys.exit(1)
print("\nEVALMUT PROBE: PASSED — 0 дыр (grader contract intact)")
sys.exit(0)
