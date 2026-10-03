#!/usr/bin/env python3
"""Prompt-robustness harness: инвариантность факта к переформулировкам и языку.

Транспорт — тот же opencode CLI, что в 4A (f4_blind_run.py / f5_judged_run.py):
модели `opencode-go/{longcat-2.0, qwen3.7-plus, deepseek-v4.1-flash}`, `--variant high`,
`--pure`, изолированный `--dir` на вызов. Guards переиспользованы, не переписаны.

Метрики (все — на замороженном входе, без генерации на лету):
  base_accuracy                доля базовых ответов, содержащих эталонный факт
  invariance_given_base_correct  доля парафраз, СОГЛАСНЫХ с базой, среди кейсов,
                               где база ответила верно   <-- главная метрика
  invariance_overall           то же без условия на базу (диагностическая)
  seed_stability               доля повторов базы с тем же фактом (при T=0)
  abstention_rate              доля ответов «I don't know» (исключаются, НЕ = fail)

Invalid ≠ fail: TIMEOUT / MODEL-MISMATCH / EMPTY считаются invalid, исключаются из
знаменателя и отчётомся отдельной строкой. Тихий ноль запрещён — пустой знаменатель
даёт exit(2), а не 0.0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
FROZEN = Path(__file__).resolve().parent / "frozen" / "dataset.json"
RESULTS = Path(__file__).resolve().parent / "results"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
BUILD_MODEL = re.compile(r"build\s*[·>\-:]+\s*([A-Za-z0-9._/\-]+)")

VARIANT = "high"
MODELS = [
    "opencode-go/longcat-2.0",
    "opencode-go/qwen3.7-plus",
    "opencode-go/deepseek-v4.1-flash",
]
LANGS = ("ru", "en")

# Идентична для base, всех парафраз и ОБЕИХ языковых рук. Не содержит указания
# языка ответа — иначе ось языка смешалась бы с осью инструкции (dataset design).
INSTRUCTION = "Answer the question in one short sentence. If you do not know, reply exactly: I don't know."

ABSTENTION_MARKERS = ("i don't know", "i do not know", "не знаю", "неизвестно", "i cannot", "i can't")

# Порог главной метрики. Обоснование: допускаем 1 промах из 3 парафраз на кейс
# (H3-уровень для сверхчастотных фактов = 1.000; для year_fact ожидаем ниже).
THRESHOLD = 0.90
MIN_INVARIANCE_DENOM = 10  # меньше — число не публикуется (UNKNOWN, не 0.0)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PopulationError(RuntimeError):
    """Вход невалиден или знаменатель пуст. Тихий ноль запрещён (§19.6/T10)."""


# ── Транспорт ────────────────────────────────────────────────────────────────
@dataclass
class Reply:
    text: str
    served_model: str | None = None
    status: str = "ok"          # ok | timeout | model_mismatch | error | empty
    error: str = ""


class Transport:
    name = "base"

    def ask(self, prompt: str, model: str, workdir: Path) -> Reply:
        raise NotImplementedError


class CliTransport(Transport):
    """opencode CLI. Промпт — inline в argv, НЕ через --file: имя файла модель
    видит, и «paraphrase_2.txt» в аргументе скомпрометировало бы весь тест."""

    name = "cli"

    def __init__(self, timeout: int = 300) -> None:
        self.timeout = timeout
        self.bin = self._find_bin()

    @staticmethod
    def _find_bin() -> str:
        env = os.environ.get("OPENCODE_BIN")
        if env and Path(env).exists():
            return env
        found = shutil.which("opencode")
        if found:
            return found
        cand = Path(os.environ.get("APPDATA", "")) / "npm" / "opencode.cmd"
        if cand.exists():
            return str(cand)
        raise SystemExit("opencode binary not found (set OPENCODE_BIN)")

    def ask(self, prompt: str, model: str, workdir: Path) -> Reply:
        line = f"{INSTRUCTION} {prompt}"
        line = " ".join(line.split())            # §5: многострочный argv → fallback
        workdir.mkdir(parents=True, exist_ok=True)
        cmd = [self.bin, "run", line, "--model", model, "--pure",
               "--dir", str(workdir), "--variant", VARIANT]
        env = dict(os.environ, PYTHONUTF8="1", NO_COLOR="1")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        try:
            out, err = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return Reply("", None, "timeout", f">{self.timeout}s")
        text = ANSI.sub("", ((out or b"") + b"\n" + (err or b"")).decode("utf-8", errors="replace"))
        # КРИТИЧНО: ответ модели приходит в stdout, баннер "> build · model" — в stderr.
        # Склейка out+err ставит баннер ПОСЛЕ ответа, и «всё, что после баннера» — пусто,
        # т.е. прежний харнесс молча выбрасывал сам ответ: все 12 вызовов пилота пришли
        # со статусом 'empty'. Тело ответа берём ТОЛЬКО из stdout.
        out_text = ANSI.sub("", (out or b"").decode("utf-8", errors="replace"))
        err_text = ANSI.sub("", (err or b"").decode("utf-8", errors="replace"))

        m = BUILD_MODEL.search(text)
        served = m.group(1) if m else None
        want = model.split("/")[-1]
        if served and want not in served:
            return Reply("", served, "model_mismatch", f"served={served} want={want}")
        if "Cannot connect" in text or "Error:" in text:
            return Reply("", served, "error", text[:200])

        body = self._strip_banner(out_text)
        if not body.strip():
            return Reply("", served, "empty",
                        f"stdout empty after banner; stdout={out_text[:120]!r} "
                        f"stderr={err_text[:120]!r}")
        return Reply(body, served, "ok")

    @staticmethod
    def _strip_banner(text: str) -> str:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if BUILD_MODEL.search(ln):
                return "\n".join(lines[i + 1:])
        return "\n".join(lines)


class OracleTransport(Transport):
    """Позитив-контроль (C1): всегда возвращает канонический ответ кейса."""

    name = "oracle"

    def __init__(self, cases: list) -> None:
        self.fact_by_prompt = {}
        for case in cases:
            for blk in case.prompts.values():
                self.fact_by_prompt[blk["base"]] = case.oracle_answer
                for para in blk["paraphrases"]:
                    self.fact_by_prompt[para] = case.oracle_answer

    def ask(self, prompt: str, model: str, workdir: Path) -> Reply:
        return Reply(self.fact_by_prompt.get(prompt, "I don't know"), "oracle", "ok")


class PlantedBreakTransport(Transport):
    """Негатив-контроль (C2): саботирует ОДНУ известную парафразу."""

    name = "planted_break"

    def __init__(self, cases: list, break_prompt: str,
                 reply: str = "Марсель — это другой город.") -> None:
        self.break_prompt = break_prompt
        self.reply = reply
        self.hits: list[str] = []
        self.fact_by_prompt = {}
        for case in cases:
            for blk in case.prompts.values():
                self.fact_by_prompt[blk["base"]] = case.oracle_answer
                for para in blk["paraphrases"]:
                    self.fact_by_prompt[para] = case.oracle_answer

    def ask(self, prompt: str, model: str, workdir: Path) -> Reply:
        if prompt == self.break_prompt:
            self.hits.append(prompt)
            return Reply(self.reply, "planted", "ok")
        return Reply(self.fact_by_prompt.get(prompt, "I don't know"), "planted", "ok")


# ── Матчер факта ─────────────────────────────────────────────────────────────
def _render_fact(case: "Case") -> str:
    """Канонический ответ кейса. Явное поле в датасете, НЕ инверсия регулярки:
    инверсия \\\\b100\\\\b даёт 'b100b', что не матчится (граница слова потеряна)."""
    return case.oracle_answer


def extract_fact(text: str, fact: dict) -> bool:
    low = (text or "").lower()
    if any(a.lower() in low for a in fact.get("any_of", [])):
        return True
    return any(re.search(p, text or "", re.IGNORECASE | re.UNICODE) for p in fact.get("regex", []))


def is_abstention(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in ABSTENTION_MARKERS)


# ── Загрузка датасета с жёсткой валидацией ───────────────────────────────────
@dataclass
class Case:
    id: str
    axis: str
    in_aggregate: bool
    fact: dict
    prompts: dict
    oracle_answer: str


def load_dataset(path: Path = FROZEN, case_filter: str | None = None) -> dict:
    if not path.is_file():
        raise PopulationError(f"dataset not found: {path}")
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    cases = [Case(c["id"], c["axis"], bool(c["in_aggregate"]), c["fact"], c["prompts"],
                  c["oracle_answer"])
             for c in data["cases"]]
    if case_filter:
        cases = [c for c in cases if case_filter in c.id]
    if not cases:
        raise PopulationError(f"no cases after filter {case_filter!r}")

    problems: list[str] = []
    for c in cases:
        for lang in LANGS:
            blk = c.prompts.get(lang)
            if not blk:
                problems.append(f"{c.id}/{lang}: no block")
                continue
            if not blk.get("base", "").strip():
                problems.append(f"{c.id}/{lang}: empty base")
            paras = blk.get("paraphrases", [])
            if len(paras) != 3:
                problems.append(f"{c.id}/{lang}: paraphrases={len(paras)} (need 3)")
            if len(set(paras)) != len(paras):
                problems.append(f"{c.id}/{lang}: duplicate paraphrases")
            for t in [blk.get("base", "")] + paras:
                if "\n" in t or "\r" in t:
                    problems.append(f"{c.id}/{lang}: multiline prompt")
        for pat in c.fact.get("regex", []):
            try:
                re.compile(pat)
            except re.error as e:
                problems.append(f"{c.id}: bad regex {pat!r}: {e}")
        # Канонический ответ обязан матчиться own-спецификацией. Если не матчится —
        # позитив-контроль невалиден и все «зелёные» числа не имеют смысла.
        if not extract_fact(c.oracle_answer, c.fact):
            problems.append(f"{c.id}: oracle_answer does NOT match own fact spec "
                            f"(got {c.oracle_answer!r}, spec={c.fact})")
    if problems:
        raise PopulationError("invalid dataset: " + "; ".join(problems[:10]))

    agg = [c for c in cases if c.in_aggregate]
    if not agg:
        raise PopulationError("no aggregate cases -> denominator would be 0")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema_version": data.get("schema_version", "?"),
        "cases": cases,
        "aggregate": agg,
        "denominator_per_lang": len(agg) * 3,
    }


# ── Прогон ───────────────────────────────────────────────────────────────────
@dataclass
class Run:
    prompt: str
    status: str
    matched: bool | None
    abstained: bool
    served_model: str | None
    text: str = ""
    error: str = ""


def run_cell(transport: Transport, model: str, prompt: str, workdir: Path, fact: dict) -> Run:
    reply = transport.ask(prompt, model, workdir)
    if reply.status != "ok":
        return Run(prompt, reply.status, None, False, reply.served_model, "", reply.error)
    abst = is_abstention(reply.text)
    return Run(prompt, "ok", extract_fact(reply.text, fact), abst, reply.served_model, reply.text)


def run_model(transport: Transport, model: str, data: dict, base_repeats: int = 3,
              timeout: int = 300) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    served: set[str] = set()
    per_lang: dict[str, dict] = {}
    t0 = time.time()
    # rows живут ВНЕ цикла по языкам: раньше список пересоздавался на каждой руке,
    # и в отчёт попадал только последний язык — число для RU было недоказуемо.
    rows: list[dict] = []

    for lang in LANGS:
        base_correct = 0
        seed_same = seed_total = 0
        inv_num = inv_den = 0            # conditioned on base correct
        ovr_num = ovr_den = 0
        abst = invalid = total = 0

        for case in data["aggregate"]:
            blk = case.prompts[lang]
            fact = case.fact

            base_runs = [
                run_cell(transport, model, blk["base"], ROOT / ".pr_work" / stamp /
                         f"{model.split('/')[-1]}_{lang}_{case.id}_base{i}", fact)
                for i in range(base_repeats)
            ]
            for bi, r in enumerate(base_runs):
                served.add(r.served_model or "?")
                if r.status == "ok":
                    total += 1
                    abst += int(r.abstained)
                    if r.abstained:
                        r.matched = None
                else:
                    invalid += 1
                rows.append({
                    "case": case.id, "axis": case.axis, "lang": lang,
                    "which": f"base{bi}", "prompt": blk["base"],
                    "status": "abstain" if (r.status == "ok" and r.abstained) else r.status,
                    "matched": r.matched, "abstained": r.abstained,
                    "text": r.text, "error": r.error,
                })

            valid_base = [r for r in base_runs if r.status == "ok" and not r.abstained]
            base_ok = bool(valid_base) and all(r.matched for r in valid_base)
            base_correct += int(base_ok)
            # seed_stability = СОГЛАСОВАННОСТЬ повторов, а не правильность.
            # Стабильно-неверная модель обязана давать 1.0 при base_accuracy = 0.0;
            # прежний код считал долю верных и путал две разные величины.
            if len(valid_base) >= 2:
                seed_total += 1
                seed_same += int(len({bool(r.matched) for r in valid_base}) == 1)

            for j, para in enumerate(blk["paraphrases"]):
                pr = run_cell(transport, model, para,
                              ROOT / ".pr_work" / stamp /
                              f"{model.split('/')[-1]}_{lang}_{case.id}_p{j}", fact)
                served.add(pr.served_model or "?")
                if pr.status != "ok":
                    invalid += 1
                    rows.append({"case": case.id, "axis": case.axis, "lang": lang,
                                 "which": f"p{j}", "prompt": para, "status": pr.status,
                                 "error": pr.error})
                    continue
                total += 1
                abst += int(pr.abstained)
                if pr.abstained:
                    rows.append({"case": case.id, "axis": case.axis, "lang": lang,
                                 "which": f"p{j}", "prompt": para, "status": "abstain",
                                 "abstained": True, "text": pr.text, "error": pr.error})
                    continue
                agree = bool(pr.matched) == base_ok
                ovr_den += 1
                ovr_num += int(agree)
                if base_ok:
                    inv_den += 1
                    inv_num += int(agree)
                rows.append({"case": case.id, "axis": case.axis, "lang": lang,
                             "which": f"p{j}", "prompt": para, "status": "ok",
                             "matched": pr.matched, "agrees_with_base": agree,
                             "base_ok": base_ok, "text": pr.text, "error": pr.error})

        per_lang[lang] = {
            "base_accuracy": round(base_correct / len(data["aggregate"]), 4),
            "invariance_given_base_correct": (round(inv_num / inv_den, 4) if inv_den else None),
            "invariance_given_base_correct_den": inv_den,
            "invariance_overall": (round(ovr_num / ovr_den, 4) if ovr_den else None),
            "invariance_overall_den": ovr_den,
            "seed_stability": (round(seed_same / seed_total, 4) if seed_total else None),
            "seed_den": seed_total,
            "abstentions": abst,
            "invalid": invalid,
            "responses_total": total,
        }

    return {
        "model": model,
        "transport": transport.name,
        "served_models_observed": sorted(served),
        "elapsed_s": round(time.time() - t0, 1),
        "base_repeats": base_repeats,
        "per_lang": per_lang,
        "rows": rows,
    }


# ── Вердикт ──────────────────────────────────────────────────────────────────
def decide(report: dict, threshold: float = THRESHOLD, min_den: int = MIN_INVARIANCE_DENOM) -> dict:
    if report["transport"] != "cli":
        return {"verdict": "N/A", "reason": f"transport={report['transport']} (control arm)"}
    reasons: list[str] = []
    nums: list[float] = []
    unknown = False
    per_lang = {}
    for lang, m in report["per_lang"].items():
        v = m["invariance_given_base_correct"]
        den = m["invariance_given_base_correct_den"]
        per_lang[lang] = {"invariance": v, "den": den}
        if v is None or den < min_den:
            unknown = True
            reasons.append(f"{lang}: denominator {den} < {min_den} → UNKNOWN, not 0.0")
            continue
        nums.append(v)
        if v < threshold:
            reasons.append(f"{lang}: invariance {v:.3f} < {threshold}")
    if unknown:
        return {"verdict": "UNKNOWN", "per_lang": per_lang, "reasons": reasons}
    if not nums:
        return {"verdict": "UNKNOWN", "per_lang": per_lang,
                "reasons": ["no usable denominators"]}
    # Вердикт по языкам НЕ усредняется: усреднение превращало RU=0.89 при EN=1.0
    # в mean=0.945 → PASS, и вердикт противоречил собственному reasons (A1).
    failed = [lg for lg, s in per_lang.items()
              if s["invariance"] is not None and s["invariance"] < threshold]
    verdict = "FAIL" if failed else "PASS"
    return {"verdict": verdict, "per_lang": per_lang,
            "mean_invariance_descriptive": round(sum(nums) / len(nums), 4),
            "min_invariance": round(min(nums), 4),
            "failed_langs": failed,
            "threshold": threshold, "reasons": reasons}


# ── CLI ──────────────────────────────────────────────────────────────────────
def exit_code_for(verdicts: list[str]) -> int:
    """Правило кодов возврата как ЧИСТАЯ функция (A4), чтобы его можно было
    проверить без живых вызовов.

    0 — успех (PASS) или контрольная рука (N/A)
    1 — FAIL
    2 — POPULATION ERROR (обрабатывается в main, сюда не попадает)
    3 — UNKNOWN: «измерить не удалось», а не «провал»
    """
    if any(v == "FAIL" for v in verdicts):
        return 1
    if any(v == "UNKNOWN" for v in verdicts):
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="prompt-robustness harness")
    ap.add_argument("--transport", choices=["cli", "oracle", "planted"], default="cli")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--case", default=None, help="substring filter (pilot)")
    ap.add_argument("--dataset", default=None,
                    help="path to dataset.json (default: frozen/dataset.json)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    try:
        ds_path = Path(args.dataset) if args.dataset else FROZEN
        data = load_dataset(ds_path, case_filter=args.case)
    except PopulationError as e:
        print(f"POPULATION ERROR: {e}", file=sys.stderr)
        print("Метрика не вычисляется. Тихий ноль запрещён (§19.6).", file=sys.stderr)
        return 2

    print(f"dataset v{data['schema_version']} sha256={data['sha256'][:16]}… "
          f"cases={len(data['cases'])} aggregate={len(data['aggregate'])} "
          f"den/lang={data['denominator_per_lang']}")

    if args.transport == "cli":
        transport = CliTransport(timeout=args.timeout)
    elif args.transport == "oracle":
        transport = OracleTransport(data["cases"])
    else:
        tgt = data["aggregate"][0].prompts["ru"]["paraphrases"][0]
        transport = PlantedBreakTransport(data["cases"], break_prompt=tgt)
        print(f"planted break target: {tgt!r}")

    reports = []
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"\n=== {model} ({args.transport}) ===", flush=True)
        rep = run_model(transport, model, data, base_repeats=args.repeats, timeout=args.timeout)
        dec = decide(rep)
        rep["decision"] = dec
        reports.append(rep)
        for lang, m in rep["per_lang"].items():
            print(f"  {lang}: base_acc={m['base_accuracy']} "
                  f"inv|base_ok={m['invariance_given_base_correct']}"
                  f"(n={m['invariance_given_base_correct_den']}) "
                  f"inv_all={m['invariance_overall']}(n={m['invariance_overall_den']}) "
                  f"seed={m['seed_stability']}(n={m['seed_den']}) "
                  f"abstain={m['abstentions']} invalid={m['invalid']}", flush=True)
        print(f"  served={rep['served_models_observed']} {rep['elapsed_s']}s", flush=True)
        print(f"  VERDICT: {dec['verdict']}", flush=True)

    out = Path(args.out) if args.out else RESULTS / f"run_{args.transport}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment": "prompt_robustness",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": " ".join(sys.argv),
        "dataset_sha256": data["sha256"],
        "dataset_schema_version": data["schema_version"],
        "instruction": INSTRUCTION,
        "instruction_sha256": hashlib.sha256(INSTRUCTION.encode()).hexdigest()[:16],
        "variant": VARIANT,
        "thresholds": {"invariance": THRESHOLD, "min_denominator": MIN_INVARIANCE_DENOM},
        "repeats": reports,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten: {out}")

    verdicts = [r["decision"]["verdict"] for r in reports]
    return exit_code_for(verdicts)


if __name__ == "__main__":
    raise SystemExit(main())
