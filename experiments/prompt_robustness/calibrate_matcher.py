"""Калибровка текстового матчера: recall на заведомо верных ответах и FP на заведомо неверных.

Зачем: инвариантность измеряется матчером, а не только моделью. Если matcher даёт
false negative, «неустойчивость» — артефакт измерения. Если matcher даёт false positive,
он прячет настоящую ошибку модели. Ни то, ни другое нельзя публиковать без измерения.

Правила (совпадают с run_experiment.py):
  exit 0 — recall == 1.0 и FP == 0
  exit 1 — есть FN или FP
  exit 2 — пустая выборка (тихий «0» запрещён)

Запуск:
  python experiments/prompt_robustness/calibrate_matcher.py
  python experiments/prompt_robustness/calibrate_matcher.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
DATASET = HERE / "frozen" / "dataset.json"
CALIBRATION = HERE / "frozen" / "matcher_calibration.json"

sys.path.insert(0, str(HERE))
from run_experiment import extract_fact  # noqa: E402  (нужен реальный код-путь матчера)


class PopulationError(RuntimeError):
    """Calibration set is empty or does not describe the dataset under test."""


def load_facts(dataset_path: Path) -> dict[str, dict]:
    data = json.loads(dataset_path.read_bytes().decode("utf-8"))
    return {c["id"]: c["fact"] for c in data["cases"]}


def load_items(calibration_path: Path) -> list[dict]:
    doc = json.loads(calibration_path.read_bytes().decode("utf-8"))
    items = doc.get("items") or []
    if not items:
        raise PopulationError(f"calibration set is empty: {calibration_path}")
    if not any(i["expect"] == "match" for i in items):
        raise PopulationError("calibration set has no positives — recall is undefined")
    if not any(i["expect"] == "no_match" for i in items):
        raise PopulationError("calibration set has no negatives — FP is undefined")
    return items


def split_items(items: list[dict], split: str) -> list[dict]:
    """Детерминированное разбиение calibrate/tune vs heldout.

    Алиасы подгоняются ТОЛЬКО на tune. heldout не смотрится до фиксации фактов,
    иначе «recall=1.0» будет результатом подгонки, а не измерения (§18).
    Чёт/нечёт по индексу в каноническом порядке — детерминированно между прогонами.
    """
    if split == "all":
        return list(items)
    if split not in ("tune", "heldout"):
        raise PopulationError(f"unknown split {split!r}")
    want_even = split == "tune"
    return [it for i, it in enumerate(items) if (i % 2 == 0) is want_even]


def calibrate(dataset_path: Path, calibration_path: Path, match_fn=extract_fact,
              split: str = "all") -> dict:
    facts = load_facts(dataset_path)
    items = load_items(calibration_path)
    all_items = len(items)
    items = split_items(items, split)

    unknown = sorted({i["case"] for i in items} - set(facts))
    if unknown:
        raise PopulationError(f"calibration references cases absent from dataset: {unknown}")

    per_case: dict[str, dict] = {}
    false_neg: list[dict] = []
    false_pos: list[dict] = []
    for item in items:
        cid = item["case"]
        slot = per_case.setdefault(
            cid, {"pos": 0, "pos_hit": 0, "neg": 0, "neg_hit": 0, "axis": None}
        )
        got = bool(match_fn(item["text"], facts[cid]))
        want = item["expect"] == "match"
        if want:
            slot["pos"] += 1
            slot["pos_hit"] += int(got)
            if not got:
                false_neg.append(item)
        else:
            slot["neg"] += 1
            slot["neg_hit"] += int(got)
            if got:
                false_pos.append(item)

    total_pos = sum(s["pos"] for s in per_case.values())
    total_pos_hit = sum(s["pos_hit"] for s in per_case.values())
    total_neg = sum(s["neg"] for s in per_case.values())
    total_neg_hit = sum(s["neg_hit"] for s in per_case.values())

    for cid, slot in per_case.items():
        slot["recall"] = round(slot["pos_hit"] / slot["pos"], 4) if slot["pos"] else None
        slot["fp_rate"] = round(slot["neg_hit"] / slot["neg"], 4) if slot["neg"] else None
        slot["ok"] = slot["pos_hit"] == slot["pos"] and slot["neg_hit"] == 0

    recall = round(total_pos_hit / total_pos, 4) if total_pos else None
    fp_rate = round(total_neg_hit / total_neg, 4) if total_neg else None
    return {
        "split": split,
        "items_in_split": len(items),
        "items_total": all_items,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "calibration_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
        "positives": total_pos,
        "negatives": total_neg,
        "positives_matched": total_pos_hit,
        "negatives_matched": total_neg_hit,
        "recall": recall,
        "fp_rate": fp_rate,
        "false_negatives": false_neg,
        "false_positives": false_pos,
        "per_case": per_case,
        "verdict": "OK" if recall == 1.0 and fp_rate == 0.0 else "NOT_CALIBRATED",
    }


def report(rep: dict, show_items: int = 6) -> None:
    print(f"dataset       {rep['dataset_sha256'][:16]}")
    print(f"calibration   {rep['calibration_sha256'][:16]}")
    print(f"split         {rep['split']} ({rep['items_in_split']}/{rep['items_total']} items)")
    print(f"positives     {rep['positives_matched']}/{rep['positives']} matched")
    print(f"negatives     {rep['negatives_matched']}/{rep['negatives']} wrongly matched")
    print(f"recall        {rep['recall']}")
    print(f"fp_rate       {rep['fp_rate']}")
    print()
    print(f"{'case':<28} {'pos':>7} {'neg':>5} {'recall':>7} {'fp':>5}")
    for cid, s in rep["per_case"].items():
        flag = " " if s["ok"] else "!"
        print(f"{flag}{cid:<27} {s['pos_hit']}/{s['pos']:<5} {s['neg_hit']}/{s['neg']:<3} "
              f"{s['recall']:>7} {s['fp_rate']:>5}")
    for label, rows in (("FALSE NEGATIVE", rep["false_negatives"]),
                        ("FALSE POSITIVE", rep["false_positives"])):
        if not rows:
            continue
        print(f"\n{label} ({len(rows)}):")
        for r in rows[:show_items]:
            print(f"  [{r['case']}/{r['lang']}] {r['text']}")
        if len(rows) > show_items:
            print(f"  … ещё {len(rows) - show_items}")


def selftest() -> int:
    """Негативный контроль гейта: сломанный матчер ОБЯЗАН пойматься (exit 1).

    Без этой проверки «recall=1.0» нельзя отличить от сломанной проверки.
    """
    failures = []

    def always_true(text: str, fact: dict) -> bool:
        return True

    rep = calibrate(DATASET, CALIBRATION, match_fn=always_true)
    if rep["verdict"] == "OK":
        failures.append("always_true matcher was accepted — FP gate does not fire")
    if rep["fp_rate"] != 1.0:
        failures.append(f"always_true fp_rate={rep['fp_rate']}, expected 1.0")

    def always_false(text: str, fact: dict) -> bool:
        return False

    rep2 = calibrate(DATASET, CALIBRATION, match_fn=always_false)
    if rep2["verdict"] == "OK":
        failures.append("always_false matcher was accepted — recall gate does not fire")
    if rep2["recall"] != 0.0:
        failures.append(f"always_false recall={rep2['recall']}, expected 0.0")

    empty = HERE / "frozen" / "_selftest_empty.json"
    empty.write_text(json.dumps({"items": []}), encoding="utf-8")
    try:
        calibrate(DATASET, empty)
    except PopulationError:
        pass
    else:
        failures.append("empty calibration did not raise PopulationError (silent zero)")
    finally:
        empty.unlink(missing_ok=True)

    if failures:
        print("SELFTEST FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST OK: FN-gate, FP-gate и пустая выборка — все три умеют падать")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--calibration", type=Path, default=CALIBRATION)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--split", choices=("all", "tune", "heldout"), default="all",
                    help="all: полная выборка; tune: подгонка алиасов; heldout: проверка")
    ap.add_argument("--out", type=Path, default=None,
                    help="сохранить отчёт в JSON (артефакт измерения)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    try:
        rep = calibrate(args.dataset, args.calibration, split=args.split)
    except PopulationError as exc:
        print(f"POPULATION ERROR: {exc}", file=sys.stderr)
        return 2
    report(rep)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\nsaved: {args.out}")
    print()
    print(f"VERDICT: {rep['verdict']}")
    return 0 if rep["verdict"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
