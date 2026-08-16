#!/usr/bin/env python3
"""summarize_1L_categories.py — per-category метрики Exp 1-L (ответ на ревью Part 4).

Exp 1-L измеряет вердикты ЖИВОЙ модели по 50 фактам 1-V (25 true / 25 false).
Глобальные метрики harness (false_accept/true_accept/unknown — от N=50) не отвечают
на вопрос ревью: «не резала ли модель вместе с ложью и правдивую память?».
Этот скрипт считает разбивку по категориям ground truth из progress-файлов:

  real      (25):  recall = принято_true / 25;  false-отвергнуто; unknown
  absent    (16):  FA — принято ложное
  trap      (6):   FA (present-trap: токен есть, субъект другой)
  silent    (3):   FA (внешние системы, код молчит)

Плюс precision = true-принято / (true-принято + false-принято) и F1.
Precision без raw-чисел вводит в заблуждение (0 принятых → 1.0) — рядом всегда
принято/отвергнуто/unknown.

Usage:
  python scripts/summarize_1L_categories.py                    # все live_arm_1L_progress_*.json
  python scripts/summarize_1L_categories.py --tag v2_en        # только тег
  python scripts/summarize_1L_categories.py --tag v3_cot --markdown
  python scripts/summarize_1L_categories.py --glob "premium_v2_*"
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "experiments" / "1V_memory_contamination" / "memory_contamination_facts_v4_rep.json"

# Маппинг kind (в датасете) → человекочитаемая метка (в отчёте).
# Если датасет поменяет kind — скрипт предупредит, а не замолчит.
KIND_LABELS = {
    "real": "real",
    "mutation_absent": "absent",
    "mutation_present": "trap",
    "silent": "silent",
}
# Ожидаемый размер категорий (для WARN при неполных данных)
EXPECTED = {"real": 25, "absent": 16, "trap": 6, "silent": 3}

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — смена кодировки опциональна
        pass


def _default_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    return base / "mscodebase" / "projects" / "bfe9644b" / "experiments"


def _load_facts(facts_path: Path = FACTS) -> tuple[dict, dict, dict]:
    data = json.loads(facts_path.read_text(encoding="utf-8"))
    facts = data["facts"]
    kind_by_id = {}
    truth_by_id = {}
    unknown_kinds = set()
    for f in facts:
        kind = f.get("kind", "?")
        label = KIND_LABELS.get(kind)
        if label is None:
            unknown_kinds.add(kind)
        kind_by_id[f["id"]] = label if label else kind
        truth_by_id[f["id"]] = f.get("truth")
    if unknown_kinds:
        print(f"WARN: неизвестные kind в датасете (показаны как есть): {sorted(unknown_kinds)}",
              file=sys.stderr)
    return kind_by_id, truth_by_id, data.get("_meta", {})


def _breakdown(results: list, kind_by_id: dict) -> dict:
    """per-category счёт: {label: {true: n, false: n, unknown: n}} по ВЕРДИКТАМ."""
    b = defaultdict(lambda: defaultdict(int))
    for r in results:
        label = kind_by_id.get(r.get("id"), "?")
        b[label][r.get("verdict", "unknown")] += 1
    return b


def _breakdown_corrected(results: list, kind_by_id: dict, truth_by_id: dict) -> dict:
    """Truth-based пересчёт (RED TEAM 2026-08-16): verdict из progress + truth из corrected.

    {label: {n, n_true, acc_true, rej_true, unk_true, fa, miss_true}} где
    fa = verdict true на truth=false (настоящие false-accepts),
    miss_true = verdict != true на truth=true (потерянные истинные).
    Факты с truth=None (ambiguous: R44) — исключены из счёта.
    """
    b = defaultdict(lambda: {"n": 0, "n_true": 0, "acc_true": 0,
                             "rej_true": 0, "unk_true": 0, "fa": 0, "miss_true": 0})
    for r in results:
        fid = r.get("id")
        label = kind_by_id.get(fid, "?")
        truth = truth_by_id.get(fid)
        verdict = r.get("verdict", "unknown")
        cell = b[label]
        cell["n"] += 1
        if truth is True:
            cell["n_true"] += 1
            if verdict == "true":
                cell["acc_true"] += 1
            elif verdict == "false":
                cell["rej_true"] += 1
            else:
                cell["unk_true"] += 1
            if verdict != "true":
                cell["miss_true"] += 1
        elif truth is False:
            if verdict == "true":
                cell["fa"] += 1
    return {k: dict(v) for k, v in b.items()}


def _metrics(b: dict, label: str) -> dict:
    """Метрики категории: принято/отвергнуто/unknown + (для real) recall/precision/F1."""
    v = b.get(label, {})
    acc, rej, unk = v.get("true", 0), v.get("false", 0), v.get("unknown", 0)
    n = acc + rej + unk
    m = {"accepted": acc, "rejected": rej, "unknown": unk, "n": n}
    if label == "real":
        m["recall"] = acc / EXPECTED["real"] if EXPECTED["real"] else 0.0
        fa = sum(b.get(k, {}).get("true", 0) for k in ("absent", "trap", "silent"))
        prec = acc / (acc + fa) if (acc + fa) else 1.0
        m["precision"] = prec
        m["f1"] = 2 * prec * m["recall"] / (prec + m["recall"]) if (prec + m["recall"]) else 0.0
        m["false_accepted_total"] = fa
    return m


def _summarize_file(path: Path, kind_by_id: dict, truth_by_id: dict | None = None) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    out = {
        "file": path.name,
        "model": report.get("model", path.stem),
        "tag": path.stem.replace("live_arm_1L_progress_", ""),
        "arms": {},
    }
    cfg = report.get("config", {})
    out["config"] = {k: cfg.get(k) for k in (
        "prompt_version", "prompt_lang", "max_tokens", "seed",
        "reasoning_enabled", "facts_sha256")}
    for arm, s in report.get("arms", {}).items():
        results = [r for r in s.get("results", []) if not r.get("error")]
        errors = len(s.get("results", [])) - len(results)
        if truth_by_id is not None:
            b = _breakdown_corrected(results, kind_by_id, truth_by_id)
            out["arms"][arm] = {
                "n": len(results), "errors": errors, "corrected": True, "cats": b,
                "decided": sum(1 for r in results if r.get("verdict") in ("true", "false")),
                "unknown": sum(1 for r in results if r.get("verdict") == "unknown"),
            }
            continue
        b = _breakdown(results, kind_by_id)
        real = _metrics(b, "real")
        fa = {k: b.get(k, {}).get("true", 0) for k in ("absent", "trap", "silent")}
        out["arms"][arm] = {
            "n": len(results), "errors": errors,
            "real": real,
            "fa": fa,
            "decided": sum(1 for r in results if r.get("verdict") in ("true", "false")),
            "unknown": sum(1 for r in results if r.get("verdict") == "unknown"),
        }
    return out


def _fmt_table_corrected(items: list[dict], markdown: bool = False) -> str:
    """Corrected-режим: truth-based метрики (verdict из progress + truth из corrected)."""
    if markdown:
        lines = [
            "| файл | модель | arm | n | real acc/rej/unk | recall(real) | "
            "FA absent | FA trap | FA silent | trap miss_true |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for it in items:
            for arm, m in it["arms"].items():
                r = m["cats"].get("real", {})
                a = m["cats"].get("absent", {})
                t = m["cats"].get("trap", {})
                s = m["cats"].get("silent", {})
                recall = r.get("acc_true", 0) / r["n_true"] if r.get("n_true") else 0.0
                lines.append(
                    f"| {it['file']} | {it['model']} | {arm} | {m['n']} "
                    f"| {r.get('acc_true', 0)}/{r.get('rej_true', 0)}/{r.get('unk_true', 0)} "
                    f"| {recall:.2f} "
                    f"| {a.get('fa', 0)} | {t.get('fa', 0)} | {s.get('fa', 0)} "
                    f"| {t.get('miss_true', 0)} |"
                )
        return "\n".join(lines)
    lines = []
    for it in items:
        lines.append(f"=== {it['file']} (tag={it['tag']}) model={it['model']} CORRECTED")
        for arm, m in it["arms"].items():
            r = m["cats"].get("real", {})
            a = m["cats"].get("absent", {})
            t = m["cats"].get("trap", {})
            s = m["cats"].get("silent", {})
            recall = r.get("acc_true", 0) / r["n_true"] if r.get("n_true") else 0.0
            lines.append(
                f"  {arm:>12} | n={m['n']} real(acc={r.get('acc_true', 0)},rej={r.get('rej_true', 0)},"
                f"unk={r.get('unk_true', 0)}) | recall={recall:.2f} | "
                f"FA absent={a.get('fa', 0)} trap={t.get('fa', 0)} silent={s.get('fa', 0)} | "
                f"trap miss_true={t.get('miss_true', 0)}"
            )
    return "\n".join(lines)


# ─── Corrected-режим: truth из corrected-датасета (RED TEAM 2026-08-16) ────
def _fmt_table(items: list[dict], markdown: bool = False) -> str:
    if any(m.get("corrected") for it in items for m in it["arms"].values()):
        return _fmt_table_corrected(items, markdown)
    if markdown:
        lines = [
            "| файл | модель | arm | n | real acc/rej/unk | recall(real) | precision | F1 | "
            "FA absent/16 | FA trap/6 | FA silent/3 |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for it in items:
            for arm, m in it["arms"].items():
                r = m["real"]
                lines.append(
                    f"| {it['file']} | {it['model']} | {arm} | {m['n']} "
                    f"| {r['accepted']}/{r['rejected']}/{r['unknown']} "
                    f"| {r.get('recall', 0.0):.2f} | {r.get('precision', 1.0):.2f} "
                    f"| {r.get('f1', 0.0):.2f} "
                    f"| {m['fa']['absent']}/16 | {m['fa']['trap']}/6 | {m['fa']['silent']}/3 |"
                )
        return "\n".join(lines)
    lines = []
    for it in items:
        cfg = it["config"]
        lines.append(f"=== {it['file']} (tag={it['tag']}) model={it['model']}")
        lines.append(f"    config: {cfg}")
        for arm, m in it["arms"].items():
            r = m["real"]
            warn = []
            if m["n"] != 50:
                warn.append(f"n={m['n']}≠50")
            if m["errors"]:
                warn.append(f"errors={m['errors']}")
            lines.append(
                f"  {arm:>12} | n={m['n']} real(acc={r['accepted']},rej={r['rejected']},"
                f"unk={r['unknown']}) | recall={r.get('recall', 0.0):.2f} "
                f"precision={r.get('precision', 1.0):.2f} F1={r.get('f1', 0.0):.2f} | "
                f"FA absent={m['fa']['absent']}/16 trap={m['fa']['trap']}/6 "
                f"silent={m['fa']['silent']}/3"
                + (f" | ⚠️ {', '.join(warn)}" if warn else "")
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="папка с progress-файлами (по умолч. %%LOCALAPPDATA%%/mscodebase/"
                             "projects/bfe9644b/experiments)")
    parser.add_argument("--glob", default="live_arm_1L_progress_*.json",
                        help="glob для progress-файлов (по умолч. live_arm_1L_progress_*.json)")
    parser.add_argument("--tag", default="",
                        help="фильтр по тегу в имени файла (v2_en, v3_cot…) — пусто = все")
    parser.add_argument("--markdown", action="store_true", help="вывод в markdown-таблицу")
    parser.add_argument("--facts", type=Path, default=None,
                        help="файл фактов (по умолч. memory_contamination_facts_v4_rep.json). "
                             "Укажите corrected (memory_contamination_facts_v4_rep_corrected.json, "
                             "fp e5f7373d50a3e640) для truth-based пересчёта: verdict из старых "
                             "progress + truth из corrected (RED TEAM 2026-08-16)")
    args = parser.parse_args()

    data_dir = args.data_dir or _default_data_dir()
    if not data_dir.exists():
        print(f"ERROR: {data_dir} не найден. Укажите --data-dir "
              "(путь: python -c \"from src.core.artifact_paths import get_project_dir; ...\")",
              file=sys.stderr)
        return 2

    kind_by_id, truth_by_id, _meta = _load_facts(args.facts or FACTS)
    files = sorted(glob.glob(str(data_dir / args.glob)))
    if not files:
        print(f"ERROR: по glob '{args.glob}' в {data_dir} ничего не найдено", file=sys.stderr)
        return 2

    items = []
    for fp in files:
        if args.tag:
            # Точный фильтр по тегу: сверяем с config.tag из самого отчёта, а не с именем
            # файла (имя `v3_cot` является префиксом имени `v3_cot_run2` — подстрока ловит чужое).
            try:
                raw = json.loads(Path(fp).read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001 — битый файл не блокирует
                print(f"WARN: {Path(fp).name} пропущен ({e})", file=sys.stderr)
                continue
            if raw.get("config", {}).get("tag") != args.tag:
                continue
        try:
            # truth_by_id передаётся ТОЛЬКО при явном --facts (corrected-пересчёт),
            # иначе старое поведение (kind-вердиктная статистика) сохраняется
            items.append(_summarize_file(Path(fp), kind_by_id,
                                         truth_by_id if args.facts else None))
        except Exception as e:  # noqa: BLE001 — битый файл не блокирует остальные
            print(f"WARN: {Path(fp).name} пропущен ({e})", file=sys.stderr)

    print(_fmt_table(items, markdown=args.markdown))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 — диагностика по §5.11
        import traceback
        traceback.print_exc()
        sys.exit(1)
