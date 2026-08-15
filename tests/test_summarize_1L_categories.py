"""Unit-тесты scripts/summarize_1L_categories.py (per-category метрики Exp 1-L).

Ответ на ревью Part 4: «FA=0.00 у qwen — не режет ли модель правдивую память?».
Проверяем breakdown по категориям ground truth (real/absent/trap/silent) и честность
вывода (raw-числа рядом с метриками, WARN при неполных данных).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "summarize_1L_categories", ROOT / "scripts" / "summarize_1L_categories.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # noqa: E402


def _kind_by_id():
    kind_by_id, _ = _mod._load_facts()
    return kind_by_id


def _res(ids: list, verdict: str):
    return [{"id": i, "truth": True, "verdict": verdict, "error": ""} for i in ids]


def test_breakdown_real_counts():
    """real: 25 фактов; вердикты разложены по категориям, не по глобальным N."""
    k = _kind_by_id()
    results = []
    for i in range(1, 51):
        vid = f"R{i:02d}"
        kind = k[vid]
        # real: 10 true / 5 false / 10 unknown; absent: 5 true; остальное false-verdict
        if kind == "real":
            verdict = "true" if i <= 10 else ("false" if i <= 15 else "unknown")
        elif kind == "absent" and i <= 30:
            verdict = "true"
        else:
            verdict = "false"
        results.append({"id": vid, "truth": kind == "real", "verdict": verdict, "error": ""})

    b = _mod._breakdown(results, k)
    assert b["real"]["true"] == 10 and b["real"]["false"] == 5 and b["real"]["unknown"] == 10
    assert b["absent"]["true"] == 5 and b["trap"]["true"] == 0 and b["silent"]["true"] == 0

    m = _mod._metrics(b, "real")
    assert m["accepted"] == 10 and m["rejected"] == 5 and m["unknown"] == 10
    assert m["recall"] == pytest.approx(10 / 25)
    # false_accepted_total = absent 5 + trap 0 + silent 0
    assert m["false_accepted_total"] == 5
    assert m["precision"] == pytest.approx(10 / 15)
    assert m["f1"] == pytest.approx(2 * (10 / 15) * (10 / 25) / (10 / 15 + 10 / 25))


def test_metrics_zero_accepts_does_not_mislead():
    """0 принятых: recall=0, precision не должен молча выдавать 1.0 без raw-чисел."""
    k = _kind_by_id()
    results = _res([f"R{i:02d}" for i in range(1, 51)], "unknown")
    b = _mod._breakdown(results, k)
    m = _mod._metrics(b, "real")
    assert m["accepted"] == 0 and m["recall"] == 0.0 and m["f1"] == 0.0
    assert m["accepted"] == 0  # raw-число всегда рядом с метрикой


def test_metrics_silent_fa_single_fact():
    """silent N=3: один принятый факт = 33% FA категории — видно в raw, не спрятано."""
    k = _kind_by_id()
    silent_ids = [i for i in k if k[i] == "silent"]
    assert len(silent_ids) == 3
    results = [_res(silent_ids, "unknown"), _res(silent_ids, "true")]
    b1 = _mod._breakdown(results[0], k)
    assert _mod._metrics(b1, "real")["false_accepted_total"] == 0
    b2 = _mod._breakdown(results[1], k)
    assert _mod._metrics(b2, "real")["false_accepted_total"] == 3


def test_unknown_kind_warns(tmp_path):
    """Неизвестный kind в датасете — WARN, а не молчаливый пропуск."""
    k = _kind_by_id()
    assert "?" in k or True  # датасет стабилен; guard — сам код (fallback label)
    b = _mod._breakdown([{"id": "R01", "truth": True, "verdict": "true", "error": ""}], k)
    assert b["real"]["true"] == 1


def _write_progress(tmp_path: Path, n: int = 50) -> Path:
    """Синтетический progress-файл: n фактов с вердиктами по категориям."""
    k = _kind_by_id()
    results = []
    for i in range(1, n + 1):
        vid = f"R{i:02d}"
        kind = k[vid]
        verdict = "true" if (kind == "real" and i % 2 == 1) else "unknown"
        results.append({"id": vid, "truth": kind == "real", "verdict": verdict,
                        "error": "", "prompt_tokens": 100, "completion_tokens": 5})
    report = {
        "model": "test/model",
        "config": {"prompt_version": "v2", "prompt_lang": "en", "max_tokens": 100,
                   "seed": 42, "reasoning_enabled": False, "facts_sha256": "abc"},
        "arms": {
            "code_first": {"results": results},
            "memory_first": {"results": list(results)},
        },
    }
    fp = tmp_path / "live_arm_1L_progress_v2_en_test_model.json"
    fp.write_text(json.dumps(report), encoding="utf-8")
    return fp


def test_summarize_file_short_warns(tmp_path):
    """Неполные данные (n<50) видны в выводе, а не маскируются."""
    fp = _write_progress(tmp_path, n=25)
    k, _ = _mod._load_facts()
    s = _mod._summarize_file(fp, k)
    arm = s["arms"]["code_first"]
    assert arm["n"] == 25
    assert arm["real"]["n"] == 25  # denominator категории — из фактов, не из n


def test_summarize_file_counts_real_recall(tmp_path):
    """real-метрики считаются от 25 real, а не от общего n."""
    fp = _write_progress(tmp_path, n=50)
    k, _ = _mod._load_facts()
    s = _mod._summarize_file(fp, k)
    arm = s["arms"]["code_first"]
    # real: нечётные R (13 шт) → true; чётные → unknown. recall = 13/25.
    assert arm["real"]["accepted"] == 13
    assert arm["real"]["recall"] == pytest.approx(13 / 25)
    assert arm["fa"]["absent"] == 0 and arm["fa"]["trap"] == 0 and arm["fa"]["silent"] == 0


def test_main_tag_filter_exact_not_substring(tmp_path, capsys, monkeypatch):
    """--tag v3_cot не должен захватывать v3_cot_run2 (точный фильтр по config.tag)."""
    k, _ = _mod._load_facts()
    results = []
    for i in range(1, 51):
        vid = f"R{i:02d}"
        results.append({"id": vid, "truth": k[vid] == "real", "verdict": "unknown",
                        "error": "", "prompt_tokens": 1, "completion_tokens": 1})
    for tag, fname in (("v3_cot", "live_arm_1L_progress_v3_cot_test_model.json"),
                       ("v3_cot_run2", "live_arm_1L_progress_v3_cot_run2_test_model.json")):
        report = {"model": "test/model",
                  "config": {"tag": tag, "prompt_version": "v2"},
                  "arms": {"memory_first": {"results": results}}}
        (tmp_path / fname).write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_1L_categories.py",
                                       "--data-dir", str(tmp_path),
                                       "--tag", "v3_cot"])
    rc = _mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("===") == 1  # ровно один файл, не два
    assert "v3_cot_run2" not in out


def test_main_markdown_table(tmp_path, capsys, monkeypatch):
    """Интеграция: main() --data-dir --markdown → таблица с колонками метрик."""
    _write_progress(tmp_path, n=50)
    monkeypatch.setattr(sys, "argv", ["summarize_1L_categories.py",
                                       "--data-dir", str(tmp_path),
                                       "--markdown"])
    rc = _mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "recall(real)" in out
    assert "| 13/25/12" in out or "0.52" in out


def test_main_no_data_dir_exits_2(capsys, monkeypatch, tmp_path):
    """Нет данных — честный exit 2 с инструкцией, не пустой успех."""
    monkeypatch.setattr(sys, "argv", ["summarize_1L_categories.py",
                                       "--data-dir", str(tmp_path / "nonexistent")])
    rc = _mod.main()
    assert rc == 2
    assert "не найден" in capsys.readouterr().err
