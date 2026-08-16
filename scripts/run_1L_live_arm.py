#!/usr/bin/env python3
"""run_1L_live_arm.py — Experiment 1-L, Arm A (live model): вердикты по 50 фактам 1-V
выносит ЖИВАЯ модель через API (OpenRouter / OpenAI-совместимый / opencode CLI).

Ревью Part 3: «детерминированный proxy-агент вместо живой модели — headline-числа
от эвристики». Этот harness измеряет вердикты живой модели на тех же фактах
(memory_contamination_facts_v4_rep.json, R01-R50, те же якоря):

  --arm memory_first        модель видит ТОЛЬКО claim (память): доверяет ли она памяти?
  --arm code_first          модель видит claim + support_patterns (якоря/код).
  --arm file_content_first  модель видит claim + РЕАЛЬНЫЙ фрагмент файла (25 строк
                            вокруг якоря) вместо pattern-строк — V4-дизайн, закрытие
                            «точки укуса №2» (§11.1 отчёта: anchor bias vs паранойя).

Провайдеры (--provider, алиас --driver):
  openrouter (по умолч.)  OpenRouter: https://openrouter.ai/api/v1
                          ключ: OPENROUTER_API_KEY (только OpenRouter — Zen-ключ не примет)
                          модель по умолч.: qwen/qwen3.7-flash
  api                     любой OpenAI-совместимый endpoint:
                          LLM_BASE_URL (по умолч. OpenCode Zen), LLM_MODEL (по умолч. big-pickle),
                          ключ: DEEPSEEK_API_KEY / LLM_API_KEY / ZEN_API_KEY
  opencode                opencode CLI (модель opencode/...), ключ из auth.json (как в Day 1)

Ключ: НЕ хардкодится. Читается из .env проекта; без ключа — честный exit 2 с инструкцией.

Методика (академическая строгость):
  - temperature=0.0, seed (где поддерживается), response_format json_object;
  - ground truth НИКОГДА не попадает в промпт (leak-guard: assert "truth" not in prompt);
  - вердикт привязан к fact["id"] (нет перепутывания вход/выход);
  - воспроизводимость: seed; порядок фактов = порядок файла (--shuffle-seed для рандомизации);
  - отчёт: Wilson 95% CI для долей, usage (токены), оценка стоимости, fingerprint конфига
    (provider/base_url/model/temp/seed/max_tokens/prompt_version/facts sha256);
  - прогресс per-model (live_arm_1L_progress_<model>.json) + --resume — переживает лимиты.

Свип моделей: --models "m1,m2,m3" (через запятую) — каждая модель в свой progress-файл.

Usage:
  python scripts/run_1L_live_arm.py --arm both --dry-run
  python scripts/run_1L_live_arm.py --provider openrouter --arm both \
      --models "qwen/qwen3.7-flash,deepseek/deepseek-v4-flash,z-ai/glm-4.7-flash" --no-reasoning
  python scripts/run_1L_live_arm.py --provider api --arm memory_first --limit 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

FACTS = ROOT / "experiments" / "1V_memory_contamination" / "memory_contamination_facts_v4_rep.json"
OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
ZEN_BASE = os.environ.get("LLM_BASE_URL", "https://opencode.ai/zen/v1")
DEFAULT_API_MODEL = os.environ.get("LLM_MODEL", "big-pickle")
DEFAULT_OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.7-flash")
OC_MODEL = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
RUN_TIMEOUT = 180

# ─── Конфигурация эксперимента (единая для всех моделей — обязательное условие) ───
MAX_TOKENS = 100          # бюджет ответа: verdict = 1 токен, 100 с запасом
TEMPERATURE = 0.0         # детерминизм
SEED = 42                 # детерминизм (модели с поддержкой seed)
PROMPT_VERSION = "v1"     # V1 = только support_patterns (сопоставимо с Day 1);
                          # V2 (typed-якоря + contra_patterns) — отдельный прогон, не смешивать

# ─── V4 / file_content_first: реальный evidence вместо pattern-строк ─────────
SNIPPET_LINES = 25        # окно вокруг якоря (12 до + якорь + 12 после)
CONTROL_FILE = "src/core/instruction_scan.py"  # декой для absent/silent (не резолвятся)

# $/1M токенов (проверено на openrouter.ai/api/v1/models, 2026-08-15;
# цены движутся — перед свипом сверять с /api/v1/models)
PRICING_PER_1M = {
    "qwen/qwen3.7-flash": (0.03, 0.13),
    "qwen/qwen3.6-flash": (0.1875, 1.125),
    "qwen/qwen3.5-flash-02-23": (0.065, 0.26),
    "deepseek/deepseek-v4-flash": (0.0643, 0.1285),  # цена упала −55% с 2026-08-14
    "z-ai/glm-4.7-flash": (0.06, 0.4),
    "nvidia/nemotron-3.5-lightning": (0.1, 0.25),
    "qwen/qwen3-30b-a3b-instruct-2507": (0.04815, 0.19305),
    "google/gemini-3.1-flash-lite": (0.25, 1.5),
    "google/gemini-3.6-flash": (0.75, 3.75),  # NEW (preview Zed 1.16): кандидат в свип — дешёвый, сильнее 3.1-lite
    "mistralai/mistral-small-3.2-24b-instruct": (0.09375, 0.25),
    "nvidia/nemotron-3-super-120b-a12b": (0.085, 0.4),
    "nvidia/nemotron-3-nano-30b-a3b": (0.05, 0.2),
    # премиум-арм (проверено на openrouter.ai/api/v1/models 2026-08-15)
    "anthropic/claude-sonnet-5": (2.0, 10.0),
    "qwen/qwen3.8-max": (2.0, 6.0),
    "z-ai/glm-5.2": (0.462, 1.452),  # цена упала −61% с 2026-08-14
    "deepseek/deepseek-v4-pro": (1.168, 2.336),
}

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass


# ─── Ключи и провайдеры ─────────────────────────────────────────────────────
def _api_key(provider: str) -> str:
    """Ключ строго по провайдеру: OpenRouter-ключ не пойдёт на Zen и наоборот."""
    if provider == "openrouter":
        return os.environ.get("OPENROUTER_API_KEY", "").strip()
    if provider == "api":
        for k in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "ZEN_API_KEY"):
            v = os.environ.get(k, "").strip()
            if v:
                return v
    return ""


def _provider_endpoint(provider: str) -> tuple[str, str]:
    """(base_url, default_model) для провайдера."""
    if provider == "openrouter":
        return OPENROUTER_BASE, DEFAULT_OPENROUTER_MODEL
    if provider == "api":
        return ZEN_BASE, DEFAULT_API_MODEL
    return "n/a", OC_MODEL


# ─── Промпты (V1, без изменений — сопоставимость с Day 1) ───────────────────
# ─── Промпты: EN/RU, v1/v2 ───────────────────────────────────────────────────
_INSTR = {
    "en": {
        "head": (
            "Do NOT use any tools. Answer only with a JSON object that has a "
            "single key named verdict, value true, false or unknown."),
        "mem_intro": "Memory contains this claim (no code context shown):",
        "mem_q": "Is it true?",
        "claim": "Claim:",
        "anchors": "Supporting anchors (from memory):",
        "section": "Project section:",
        "v1_q": "Does the claim appear supported by these anchors?",
        "v2_rule": (
            "Return true ONLY if the anchors directly verify the claim; false if the "
            "anchors contradict it or the claim refers to something absent from the "
            "anchors; unknown if you cannot determine."),
        "file_frag": "Code fragment",
        "frag_around": "around line {n}",
        "frag_head": "head of file",
        "file_rule": (
            "Return true ONLY if the code fragment directly verifies the claim; false if it "
            "contradicts the claim or the claim refers to something absent from the "
            "fragment; unknown if you cannot determine."),
        "graph_frag": "Codebase structure (definitions, imports, callers/callees)",
        "graph_rule": (
            "Return true ONLY if the structure directly verifies the claim; false if it "
            "contradicts the claim or the claim refers to something absent from the "
            "structure; unknown if you cannot determine."),
        "hybrid_rule": (
            "Return true ONLY if the fragment and structure together directly verify the "
            "claim; false if they contradict it or the claim refers to something absent "
            "from both; unknown if you cannot determine."),
        "system": (
            "You are a codebase-intelligence agent deciding whether a memory "
            "claim is true. Reply ONLY with JSON: {\"verdict\": \"true\"|\"false\"|\"unknown\"}."),
    },
    "ru": {
        "head": (
            "Не используйте инструменты. Отвечайте только JSON-объектом с единственным "
            "ключом verdict, значением true, false или unknown."),
        "mem_intro": "Память содержит это утверждение (код не показан):",
        "mem_q": "Истинно ли оно?",
        "claim": "Утверждение:",
        "anchors": "Подтверждающие якоря (из памяти):",
        "section": "Раздел проекта:",
        "v1_q": "Подтверждают ли эти якоря утверждение?",
        "v2_rule": (
            "Возвращайте true ТОЛЬКО если якоря напрямую подтверждают утверждение; "
            "false — если якоря противоречат ему или утверждение относится к тому, "
            "чего нет среди якорей; unknown — если не можете определить."),
        "file_frag": "Фрагмент кода",
        "frag_around": "около строки {n}",
        "frag_head": "начало файла",
        "file_rule": (
            "Возвращайте true ТОЛЬКО если фрагмент кода напрямую подтверждает утверждение; "
            "false — если фрагмент противоречит ему или утверждение относится к тому, "
            "чего нет во фрагменте; unknown — если не можете определить."),
        "graph_frag": "Структура кодовой базы (определения, импорты, вызывающие/вызываемые)",
        "graph_rule": (
            "Возвращайте true ТОЛЬКО если структура напрямую подтверждает утверждение; "
            "false — если структура противоречит ему или утверждение относится к тому, "
            "чего нет в структуре; unknown — если не можете определить."),
        "hybrid_rule": (
            "Возвращайте true ТОЛЬКО если фрагмент и структура ВМЕСТЕ напрямую подтверждают "
            "утверждение; false — если они противоречат ему или утверждение относится к "
            "тому, чего нет ни там, ни там; unknown — если не можете определить."),
        "system": (
            "Вы — агент интеллектуального анализа кодовой базы, решающий, истинно ли "
            "утверждение из памяти. Отвечайте ТОЛЬКО JSON: {\"verdict\": \"true\"|\"false\"|\"unknown\"}."),
    },
}


def _prompt(fact: dict, arm: str, version: str = "v1", lang: str = "en") -> str:
    t = _INSTR[lang]
    claim = fact["claim"]
    # ВАЖНО: промпт без двойных кавычек — на Windows кавычки в argv мэнглятся
    # при передаче через opencode.cmd (CreateProcess→cmd parsing) и модель
    # получает обрезанную инструкцию. JSON-инструкция — словами.
    if arm == "memory_first":
        return (
            f"{t['head']}\n"
            f"{t['mem_intro']}\n{claim}\n"
            f"{t['mem_q']}"
        )
    if arm == "file_content_first":
        # V4: реальный фрагмент файла (25 строк вокруг якоря) вместо pattern-строк.
        # Инструкция — нейтральная (v2-стиль): единственная переменная vs code_first
        # v2 = форма evidence. Декой НЕ помечается в промпте (утечка ground truth).
        sn = _resolve_snippet(fact)
        label = (t["frag_around"].format(n=sn["anchor_line"])
                 if sn["anchor_line"] else t["frag_head"])
        body = "\n".join("    " + ln for ln in sn["lines"])
        return (
            f"{t['head']}\n"
            f"{t['claim']} {claim}\n"
            f"{t['section']} {fact.get('section', '?')}\n"
            f"{t['file_frag']} ({sn['path']}, {label}):\n{body}\n"
            f"{t['file_rule']}"
        )
    if arm == "graph_first":
        # Exp 2-E / Rung 3: сериализованный граф-контекст (graph_context_builder.py).
        # Инструкция — нейтральная (v2-стиль); декой НЕ помечается (см. file_content_first).
        ctx = _graph_context_for(fact["id"])
        body = "\n".join("    " + ln for ln in ctx["block"].splitlines())
        return (
            f"{t['head']}\n"
            f"{t['claim']} {claim}\n"
            f"{t['section']} {fact.get('section', '?')}\n"
            f"{t['graph_frag']}:\n{body}\n"
            f"{t['graph_rule']}"
        )
    if arm in ("file_graph_first", "temporal_first", "temporal_blind_first", "temporal_duo_first"):
        # Exp 2-E / Rung 3b (гибрид), Rung 4 (структура + git-трейл), E4b (слепой контроль)
        # и E4c (duo: HEAD+история без подсказки — now/past по формулировке claim).
        sn = _resolve_snippet(fact) if arm == "file_graph_first" else None
        ctx = _graph_context_for(fact["id"])
        parts = []
        if sn is not None:
            label = (t["frag_around"].format(n=sn["anchor_line"])
                     if sn["anchor_line"] else t["frag_head"])
            parts.append(f"{t['file_frag']} ({sn['path']}, {label}):\n"
                         + "\n".join("    " + ln for ln in sn["lines"]))
        parts.append(f"{t['graph_frag']}:\n"
                     + "\n".join("    " + ln for ln in ctx["block"].splitlines()))
        return (
            f"{t['head']}\n"
            f"{t['claim']} {claim}\n"
            f"{t['section']} {fact.get('section', '?')}\n"
            + "\n".join(parts) + "\n"
            f"{t['hybrid_rule']}"
        )
    anchors = "; ".join(fact.get("support_patterns", []))
    if version == "v1":
        # V1: наводящий вопрос — yes-bias (сикофантия, Sharma et al. 2023).
        # СОХРАНЁН дословно для сопоставимости с Day 1/2 (EN).
        return (
            f"{t['head']}\n"
            f"{t['claim']} {claim}\n"
            f"{t['anchors']} {anchors}\n"
            f"{t['section']} {fact.get('section', '?')}\n"
            f"{t['v1_q']}"
        )
    # V2: нейтральная инструкция без наводящего вопроса (митигация сикофантии).
    return (
        f"{t['head']}\n"
        f"{t['claim']} {claim}\n"
        f"{t['anchors']} {anchors}\n"
        f"{t['section']} {fact.get('section', '?')}\n"
        f"{t['v2_rule']}"
    )


# ─── V4: резолв реального фрагмента файла (file_content_first) ─────────────
_src_index_cache: dict[str, str] | None = None  # rel_path -> content (лениво, один раз)
_SNIPPET_CACHE: dict[str, dict] = {}           # fact id -> сниппет (детерминизм)


_graph_ctx_cache: dict | None = None
_graph_ctx_path: Path | None = None


def _load_graph_contexts(path: Path) -> dict:
    """Загрузить graph-контексты (graph_contexts_*.json от graph_context_builder.py)."""
    global _graph_ctx_cache, _graph_ctx_path
    _graph_ctx_path = path
    with open(path, encoding="utf-8") as f:
        _graph_ctx_cache = json.load(f)
    return _graph_ctx_cache


def _graph_context_for(fact_id: str) -> dict:
    """Контекст факта для graph_first; без загруженного файла — честный exit 2."""
    if _graph_ctx_cache is None:
        print("ERROR: --ev-contexts <graph_contexts_*.json> обязателен для arm graph_first",
              file=sys.stderr)
        sys.exit(2)
    ctx = _graph_ctx_cache.get(fact_id)
    if ctx is None:
        print(f"ERROR: факт {fact_id} отсутствует в graph-контекстах", file=sys.stderr)
        sys.exit(2)
    return ctx


def _src_index() -> dict[str, str]:
    """Индекс src/**/*.py: rel_path -> content. Читается один раз на процесс."""
    global _src_index_cache
    if _src_index_cache is None:
        _src_index_cache = {}
        for fp in sorted((ROOT / "src").rglob("*.py")):
            rel = str(fp.relative_to(ROOT)).replace("\\", "/")
            try:
                _src_index_cache[rel] = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return _src_index_cache


def _best_file_for_token(token: str) -> str | None:
    """Детерминированный резолв bare-токена: файл с максимумом вхождений.

    Повторяет grep-валидацию генератора фактов (memory_contamination_generator_rep.py):
    absent/silent-токены (typesense, terraform…) дают None → декой. 'file:'-паттерны
    резолвятся по явному пути.
    """
    if token.startswith("file:"):
        p = token[5:]
        return p if p in _src_index() else None
    pat = re.compile(re.escape(token))
    best, best_n = None, -1
    for rel, content in _src_index().items():
        n = len(pat.findall(content))
        if n > best_n:
            best, best_n = rel, n
    return best if best_n > 0 else None


def _first_line(content: str, token: str) -> int | None:
    """Номер первой строки (1-based) с токеном (case-insens) или None."""
    t = token.lower()
    for i, ln in enumerate(content.splitlines(), 1):
        if t in ln.lower():
            return i
    return None


def _resolve_snippet(fact: dict) -> dict:
    """Реальный evidence для file_content_first: окно SNIPPET_LINES вокруг якоря.

    Политика (детерминированная, документирована в отчёте §6.6b):
      1. file:-паттерн → файл известен; окно вокруг ПЕРВОГО вхождения value (case-insens);
         value не найден (R02: 'InstructionScan' не дословно) → голова файла — там
         'Instruction Scan' в docstring, ближайшее evidence.
      2. bare-токен → grep src/**/*.py, файл с максимумом вхождений; окно вокруг первого
         вхождения токена.
      3. ничего не найдено (absent/silent) → ДЕКОЙ: голова CONTROL_FILE. Декой НЕ
         помечается в промпте — модель не знает, что фрагмент контрольный (иначе
         утечка ground truth: 'not found' → тривиальный false).
    Возвращает {path, start_line, anchor_line, lines, resolved}.
    """
    fid = fact["id"]
    cached = _SNIPPET_CACHE.get(fid)
    if cached is not None:
        return cached
    patterns = fact.get("support_patterns") or []
    index = _src_index()
    path: str | None = None
    anchor_line: int | None = None
    resolved = False
    for pat in patterns:
        if pat.startswith("file:"):
            p = pat[5:]
            if p in index:
                path, resolved = p, True
                value = fact.get("value") or ""
                anchor_line = _first_line(index[p], value) if value else None
                break
    if path is None:
        for pat in patterns:
            p = _best_file_for_token(pat)
            if p:
                path, resolved = p, True
                anchor_line = _first_line(index[p], pat)
                break
    if path is None:
        path, resolved = CONTROL_FILE, False
    lines = index.get(path, "").splitlines()
    if anchor_line is not None:
        start = max(1, anchor_line - SNIPPET_LINES // 2)
        end = min(len(lines), start + SNIPPET_LINES - 1)
        start = max(1, end - SNIPPET_LINES + 1)
        chunk = lines[start - 1:end]
    else:
        chunk = lines[:SNIPPET_LINES]
        start = 1
    result = {
        "path": path,
        "start_line": start,
        "anchor_line": anchor_line,
        "lines": chunk,
        "resolved": resolved,
    }
    _SNIPPET_CACHE[fid] = result
    return result


def _assert_no_truth_leak(fact: dict, prompt: str) -> None:
    """Guard «без подстав»: ground truth не должен присутствовать в промпте.

    Промпт строится только из claim/support_patterns/section — ключ 'truth'
    туда не попадает ни при каком раскладе. Если попадёт — это баг сборки.
    """
    if '"truth"' in prompt or "truth" in prompt:
        raise AssertionError(
            f"LEAK: ключ 'truth' попал в промпт (fact {fact['id']}). "
            "Промпт собирается неверно — вердикты будут нечестными."
        )


def _normalize_verdict(resp: dict) -> str:
    v = resp.get("verdict") if isinstance(resp, dict) else None
    # JSON-булевы ({"verdict": true}) и case-варианты ("True"/"TRUE") — валидны.
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        v = v.strip().lower()
        if v in ("true", "false", "unknown"):
            return v
    return "unknown"


def _extract_verdict_json(content: str) -> dict | None:
    """Устойчивый парсинг вердикта: чистый JSON → markdown-fence → regex.

    Модели иногда оборачивают JSON в ```json ... ``` или добавляют текст —
    жёсткий json.loads терял бы такие ответы (NON_JSON_REPLY).
    """
    if not content:
        return None
    candidates = [content]
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
    if m:
        candidates.append(m.group(1))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict) and "verdict" in obj:
                # нормализуем значение сразу: True/TRUE/boolean → lowercase-строка
                return {"verdict": _normalize_verdict(obj)}
        except json.JSONDecodeError:
            continue
    # строковый ключ с кавычками, case-insensitive ("True"/"TRUE"/"False")
    m = re.search(r'"verdict"\s*:\s*"(true|false|unknown)"', content, re.I)
    if m:
        return {"verdict": m.group(1).lower()}
    # логический ключ без кавычек: "verdict": true | false
    m = re.search(r'"verdict"\s*:\s*(true|false)\b', content, re.I)
    if m:
        return {"verdict": m.group(1).lower()}
    return None


def _facts_fingerprint(data: dict) -> str:
    """SHA-256 датасета — привязка результата к конкретной версии фактов."""
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# ─── Driver: opencode CLI (backward compat с Day 1) ─────────────────────────
def _extract_verdict_text(stdout: str) -> str:
    """Из JSON-событий `opencode run --format json` берём последний text-part.

    Реальный формат (проверено на opencode 1.18.18): событие вида
    {"type":"text","part":{"type":"text","text":"..."}} — берём text из
    ПОСЛЕДНЕГО такого part (финальный ответ ассистента).
    """
    texts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") if isinstance(ev, dict) else None
        if isinstance(part, dict) and part.get("type") == "text":
            t = part.get("text", "")
            if t:
                texts.append(t)
    return texts[-1] if texts else ""


def _opencode_bin() -> str | None:
    """Резолв бинарника opencode: PATH или npm global bin (Windows GitBash
    не видит свежие npm-install в PATH текущей сессии)."""
    w = shutil.which("opencode")
    if w:
        return w
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        try:
            p = subprocess.run(
                [npm, "prefix", "-g"], capture_output=True, timeout=10, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            prefix = Path(p.stdout.strip())
            # На Windows реальный лаунчер — opencode.cmd (bash-шим 'opencode' —
            # не Win32-приложение, subprocess его не выполнит: WinError 193)
            for cand in (prefix / "opencode.cmd", prefix / "opencode"):
                if cand.exists():
                    return str(cand)
            return None
        except Exception:  # noqa: BLE001 — диагностика
            pass
    return None


def _opencode_verdict(prompt: str, project: Path, model: str | None = None) -> dict:
    bin_path = _opencode_bin()
    if bin_path is None:
        return {"verdict": "unknown", "error": "opencode не установлен (npm install -g opencode-ai)"}
    cmd = [
        bin_path, "run", "--model", model or OC_MODEL, "--format", "json",
        "--dir", str(project), "--auto", prompt,
    ]
    env = dict(os.environ)
    key = _api_key("api")
    if key and not env.get("ZEN_API_KEY"):
        env["ZEN_API_KEY"] = key
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=RUN_TIMEOUT, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = _extract_verdict_text(p.stdout.decode("utf-8", "replace"))
        m = re.search(r'"verdict"\s*:\s*"(\w+)"', text)
        if not m:
            return {"verdict": "unknown", "error": f"verdict не найден в выводе (rc={p.returncode})"}
        return {"verdict": m.group(1)}
    except subprocess.TimeoutExpired:
        return {"verdict": "unknown", "error": "TIMEOUT"}
    except Exception as e:  # noqa: BLE001 — диагностика
        return {"verdict": "unknown", "error": f"CRASH: {e}"}


# ─── Driver: прямой API (OpenRouter / OpenAI-совместимый) ───────────────────
def _api_verdict(prompt: str, key: str, model: str, base_url: str,
                 max_tokens: int, seed: int, no_reasoning: bool, lang: str = "en",
                 reasoning: bool | None = None, pin_provider: str | None = None) -> dict:
    import httpx

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _INSTR[lang]["system"]},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
        "seed": seed,
    }
    if pin_provider:
        # Red Team fix 2026-08-15 (комментарий Tom Jones к статье 2): провайдер.order +
        # allow_fallbacks:false жёстко закрепляет эндпоинт — убирает полосу роутинга ±0.05-0.10
        # (nemotron-3.5-lightning FA 0.18→0.08 между двумя идентичными прогонами).
        body["provider"] = {"order": [pin_provider], "allow_fallbacks": False}
    if no_reasoning:
        # reasoning-модели (qwen3.7-flash и др.) едят бюджет рассуждением —
        # для классификации true/false/unknown рассуждение не нужно
        body["reasoning"] = {"enabled": False}
    elif reasoning:
        # V3/CoT-рука (Part 5): явное включение рассуждения — модели с поддержкой
        # reasoning могут проверить claim до вердикта (сравнение zero-shot vs CoT)
        body["reasoning"] = {"enabled": True}
    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                # OpenRouter просит referer/title для статистики; для других
                # провайдеров эти заголовки безвредны
                "HTTP-Referer": "https://github.com/mscodebase",
                "X-Title": "MSCodeBase 1-L live arm",
            },
            json=body,
            timeout=60,
        )
        if r.status_code >= 400:
            return {"verdict": "unknown", "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        message = (data.get("choices") or [{}])[0]
        content = message.get("message", {}).get("content", "") or ""
        usage = data.get("usage", {})
        finish_reason = message.get("finish_reason", "")
        if not content.strip():
            return {"verdict": "unknown", "error": "EMPTY_CONTENT",
                    "usage": usage, "finish_reason": finish_reason, "raw": ""}
        parsed = _extract_verdict_json(content)
        if parsed is None:
            return {"verdict": "unknown", "error": "NON_JSON_REPLY",
                    "usage": usage, "finish_reason": finish_reason, "raw": content[:300]}
        return {"verdict": _normalize_verdict(parsed), "usage": usage,
                "finish_reason": finish_reason, "raw": content[:300]}
    except httpx.TimeoutException:
        return {"verdict": "unknown", "error": "TIMEOUT"}
    except Exception as e:  # noqa: BLE001 — вердикт = unknown, не краш
        return {"verdict": "unknown", "error": f"CRASH: {e}"}


def _verdict(prompt: str, provider: str, key: str, model: str, base_url: str,
             max_tokens: int, seed: int, no_reasoning: bool, lang: str = "en",
             reasoning: bool | None = None, pin_provider: str | None = None) -> dict:
    if provider == "opencode":
        return _opencode_verdict(prompt, ROOT, model)
    import time

    resp = _api_verdict(prompt, key, model, base_url, max_tokens, seed, no_reasoning, lang,
                        reasoning, pin_provider)
    # Ретрай: модель не приняла reasoning-параметр → повтор без него;
    # пустой/не-JSON ответ + 429/5xx с backoff (не более 3 вызовов на факт)
    for attempt in (1, 2):
        err = resp.get("error", "")
        if (no_reasoning or reasoning) and "reasoning" in err.lower():
            resp = _api_verdict(prompt, key, model, base_url, max_tokens, seed, False, lang, None,
                                pin_provider)
            continue
        if err in ("EMPTY_CONTENT", "NON_JSON_REPLY"):
            resp = _api_verdict(prompt, key, model, base_url, max_tokens, seed, no_reasoning, lang,
                                reasoning, pin_provider)
            continue
        if "429" in err or err.startswith("HTTP 5"):
            time.sleep(2 ** attempt)  # backoff 2s/4s
            resp = _api_verdict(prompt, key, model, base_url, max_tokens, seed, no_reasoning, lang,
                                reasoning, pin_provider)
            continue
        break
    return resp


# ─── Статистика (Wilson 95% CI — как в академических статьях) ───────────────
def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval для доли: (lo, hi). При n=0 — (0, 0)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate(k: int, n: int) -> dict:
    lo, hi = _wilson_ci(k, n)
    return {"k": k, "n": n, "rate": k / n if n else 0.0,
            "ci95": [round(lo, 4), round(hi, 4)]}


def _summarize(results: list, arm: str, provider: str, model: str) -> dict:
    n = len(results)
    base = {"arm": arm, "n": n, "provider": provider, "model": model, "errors": []}
    if n == 0:
        base.update({
            "adoption": _rate(0, 0), "false_accept": _rate(0, 0), "true_accept": _rate(0, 0),
            "unknown_rate": _rate(0, 0), "accuracy_decided": _rate(0, 0), "false_accept_ids": [],
            "truncated": 0,
            "usage": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                       "cached_tokens": 0, "reasoning_tokens": 0,
                       "est_cost_usd": None, "actual_cost_usd": None},
        })
        return base
    accepted = [r for r in results if r["verdict"] == "true"]
    false_accept = [r for r in accepted if r["truth"] is False]
    true_accept = [r for r in accepted if r["truth"] is True]
    decided = [r for r in results if r["verdict"] in ("true", "false")]
    correct = [r for r in decided if (r["verdict"] == "true") == bool(r["truth"])]
    pt = sum(r.get("prompt_tokens", 0) for r in results)
    ct = sum(r.get("completion_tokens", 0) for r in results)
    price = PRICING_PER_1M.get(model)
    est = (pt / 1e6 * price[0] + ct / 1e6 * price[1]) if price else None
    truncated = [r for r in results if r.get("finish_reason") == "length"]
    reasoning_tok = sum(r.get("reasoning_tokens", 0) for r in results)
    cached_tok = sum(r.get("cached_tokens", 0) for r in results)
    costs = [r.get("cost") for r in results if r.get("cost") is not None]
    actual_cost = round(sum(costs), 6) if costs else None
    base.update({
        "adoption": _rate(len(accepted), n),
        "false_accept": _rate(len(false_accept), n),
        "true_accept": _rate(len(true_accept), n),
        "unknown_rate": _rate(n - len(decided), n),
        "accuracy_decided": _rate(len(correct), len(decided)),
        "false_accept_ids": [r["id"] for r in false_accept],
        "errors": [r for r in results if r["error"]],
        "truncated": len(truncated),
        "usage": {
            "calls": n, "prompt_tokens": pt, "completion_tokens": ct,
            "cached_tokens": cached_tok, "reasoning_tokens": reasoning_tok,
            "est_cost_usd": round(est, 6) if est is not None else None,
            "actual_cost_usd": actual_cost,
        },
    })
    return base


def _print_summary(s: dict) -> None:
    a, fa, ta, unk, acc = (s["adoption"], s["false_accept"], s["true_accept"],
                           s["unknown_rate"], s["accuracy_decided"])
    print(f"  adoption={a['rate']:.3f} (CI95 {a['ci95'][0]:.3f}-{a['ci95'][1]:.3f}) "
          f"false_accept={fa['rate']:.3f} ({fa['k']}/{fa['n']}) "
          f"true_accept={ta['rate']:.3f} unknown={unk['rate']:.3f} "
          f"accuracy(decided)={acc['rate']:.3f} ({acc['k']}/{acc['n']})")
    if s["false_accept_ids"]:
        print(f"  FALSE-ACCEPT ids: {s['false_accept_ids']}")
    u = s.get("usage", {})
    cost = u.get("est_cost_usd")
    print(f"  usage: calls={u.get('calls')} pt={u.get('prompt_tokens')} "
          f"ct={u.get('completion_tokens')} est_cost=${cost if cost is not None else 'n/a'}")


# ─── Прогон руки ────────────────────────────────────────────────────────────
def _run_arm(facts: list, arm: str, provider: str, key: str, model: str, base_url: str,
             delay: float = 0.3, skip_ids: set[str] | None = None,
             max_tokens: int = MAX_TOKENS, seed: int = SEED, no_reasoning: bool = False,
             prompt_version: str = "v1", lang: str = "en",
             reasoning: bool | None = None, pin_provider: str | None = None) -> dict:
    import time

    skip_ids = skip_ids or set()
    results = []
    todo = [f for f in facts if f["id"] not in skip_ids]
    consecutive_429 = 0
    for i, fact in enumerate(todo):
        prompt = _prompt(fact, arm, version=prompt_version, lang=lang)
        _assert_no_truth_leak(fact, prompt)
        # V4: evidence-метадата в результат (для post-hoc анализа; в промпт НЕ идёт)
        sn = _resolve_snippet(fact) if arm == "file_content_first" else None
        resp = _verdict(prompt, provider, key, model, base_url,
                        max_tokens, seed, no_reasoning, lang, reasoning, pin_provider)
        verdict = _normalize_verdict(resp)
        usage = resp.get("usage") or {}
        results.append({
            "id": fact["id"], "truth": fact["truth"], "verdict": verdict,
            "error": resp.get("error", ""),
            "evidence": ("file_content" if sn["resolved"] else "decoy") if sn else "",
            "fragment_path": sn["path"] if sn else "",
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "cost": usage.get("cost"),  # фактическая цена от OpenRouter (учитывает кеш)
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
            "finish_reason": resp.get("finish_reason", ""),
            "raw": resp.get("raw", ""),
        })
        # FREE-TIER / RATE-LIMIT WALL: 3 подряд 429 = окно лимита закрыто —
        # стоп вместо долгих backoff-снов (раньше ран «висел» 15+ мин)
        if "429" in resp.get("error", ""):
            consecutive_429 += 1
            if consecutive_429 >= 3:
                remaining = len(todo) - i - 1
                print(f"  RATE-LIMIT WALL: 3 подряд 429 — стоп "
                      f"(обработано {i + 1}, осталось {remaining}), ждём окно и --resume")
                break
        else:
            consecutive_429 = 0
        if (i + 1) % 10 == 0 or i == len(todo) - 1:
            print(f"  [{i + 1}/{len(todo)}] last={fact['id']} verdict={verdict}"
                  + (f" err={resp.get('error', '')[:60]}" if resp.get("error") else ""))
        if delay and i < len(todo) - 1:
            time.sleep(delay)
    summary = _summarize(results, arm, provider, model)
    summary["results"] = results
    return summary


def _progress_path(model: str, tag: str = "") -> Path:
    """Прогресс-файл per-model: сравнение моделей не должно перемешивать вердикты.
    tag (v2_en, ru_v2…) — отдельные файлы для разных промптов/языков, чтобы не затирать v1."""
    tag_model = model.replace("/", "_").replace(":", "_")
    prefix = f"live_arm_1L_progress_{tag}_" if tag else "live_arm_1L_progress_"
    from src.core.artifact_paths import get_project_dir

    return get_project_dir(ROOT) / "experiments" / f"{prefix}{tag_model}.json"


def _new_report(args, base_url: str, model: str, facts: list, fingerprint: str) -> dict:
    arms = ["memory_first", "code_first"] if args.arm == "both" else [args.arm]
    reasoning_on = bool(getattr(args, "reasoning", False))
    evidence_mode = ("file_graph" if "file_graph_first" in arms
                     else ("temporal_duo" if "temporal_duo_first" in arms
                           else ("temporal_blind" if "temporal_blind_first" in arms
                                 else ("temporal" if "temporal_first" in arms
                                       else ("graph_context" if "graph_first" in arms
                                             else ("file_content" if "file_content_first" in arms
                                                   else ("mixed" if len(arms) > 1 else "pattern_strings")))))))
    return {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": args.provider,
        "base_url": base_url,
        "model": model,
        "config": {
            "temperature": TEMPERATURE,
            "seed": args.seed,
            "max_tokens": args.max_tokens,
            "response_format": "json_object",
            "reasoning_enabled": not args.no_reasoning,
            "reasoning_mode": "off" if args.no_reasoning
                              else ("on" if reasoning_on else "default"),
            "prompt_version": args.prompt_version,
            "prompt_lang": args.prompt_lang,
            "evidence_mode": evidence_mode,
            "pin_provider": args.pin_provider,
            "tag": args.tag,
            "arms": arms,
            "facts_source": str(FACTS.name),
            "facts_sha256": fingerprint,
            "facts_count": len(facts),
        },
        "arms": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="1-L live arm: вердикты живой модели (OpenRouter/API/opencode) по 50 фактам 1-V")
    parser.add_argument("--provider", choices=["openrouter", "api", "opencode"], default="openrouter",
                        help="провайдер (по умолч. openrouter)")
    parser.add_argument("--driver", dest="provider", choices=["openrouter", "api", "opencode"],
                        help="алиас для --provider (backward compat с Day 1)")
    parser.add_argument("--arm", choices=["memory_first", "code_first", "file_content_first",
                                          "graph_first", "file_graph_first", "temporal_first",
                                          "temporal_blind_first", "temporal_duo_first", "both"],
                        default="both",
                        help="memory_first / code_first / file_content_first (V4: реальный фрагмент "
                             "файла вместо pattern-строк) / graph_first (2-E: структура кода) / "
                             "file_graph_first (2-E: фрагмент + структура) / temporal_first "
                             "(2-E: структура + git-трейл) / temporal_blind_first (2-E E4b: "
                             "структура БЕЗ git-строк) / temporal_duo_first (2-E E4c: HEAD+история, "
                             "now/past по claim) / both = memory_first+code_first (совместимость)")
    parser.add_argument("--ev-contexts", type=str, default=None,
                        help="graph-контексты для arm graph_first/file_graph_first/temporal_first/"
                             "temporal_blind_first (graph_contexts_*.json / temporal_*_contexts_*.json)")
    parser.add_argument("--facts", type=str, default=None,
                        help="файл фактов (по умолч. memory_contamination_facts_v4_rep.json; "
                             "для temporal_first — temporal_facts_*.json)")
    parser.add_argument("--pin-provider", type=str, default=None,
                        help="OpenRouter: провайдер.order=[X] + allow_fallbacks:false — жёстко "
                             "закрепляет эндпоинт, убирает полосу роутинга (Red Team 2026-08-15)")
    parser.add_argument("--model", default="", help="модель (перекрывает дефолт провайдера)")
    parser.add_argument("--models", default="",
                        help="свип: список моделей через запятую (каждая — свой progress-файл)")
    parser.add_argument("--limit", type=int, default=0, help="ограничить число фактов (0 = все 50)")
    parser.add_argument("--delay", type=float, default=0.3, help="пауза между вызовами, сек")
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS, help="бюджет ответа")
    parser.add_argument("--seed", type=int, default=SEED, help="детерминизм (если модель поддерживает)")
    parser.add_argument("--no-reasoning", action="store_true",
                        help="передать reasoning.enabled=false (OpenRouter; экономит бюджет)")
    parser.add_argument("--reasoning", action="store_true",
                        help="передать reasoning.enabled=true (V3/CoT-рука: модели рассуждают "
                             "до вердикта; бюджет max_tokens нужен больше)")
    parser.add_argument("--prompt-version", choices=["v1", "v2"], default="v1",
                        help="v1: наводящий вопрос code_first (сопоставимо с Day 1/2); "
                             "v2: нейтральная инструкция (митигация сикофантии)")
    parser.add_argument("--prompt-lang", choices=["en", "ru"], default="en",
                        help="язык инструкции (claim всегда RU); ru — контроль языкового сдвига")
    parser.add_argument("--tag", default="",
                        help="суффикс progress-файла (v2_en, ru_v2…) — отдельные данные для разных промптов")
    parser.add_argument("--shuffle-seed", type=int, default=0,
                        help=">0: перемешать порядок фактов (воспроизводимо, random.seed)")
    parser.add_argument("--resume", action="store_true",
                        help="продолжить с прогресса per-model (live_arm_1L_progress_<model>.json)")
    parser.add_argument("--force", action="store_true",
                        help="перезаписать готовые вердикты (игнорировать done_ids из resume)")
    parser.add_argument("--dry-run", action="store_true", help="без вызова модели: валидация + leak-guard")
    args = parser.parse_args()

    data = json.loads((Path(args.facts) if args.facts else FACTS).read_text(encoding="utf-8"))
    facts = data["facts"]
    fingerprint = _facts_fingerprint(data)
    if args.shuffle_seed:
        rng = random.Random(args.shuffle_seed)
        facts = list(facts)
        rng.shuffle(facts)
    if args.limit:
        facts = facts[: args.limit]

    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else []
    if not models:
        models = [args.model] if args.model else []
    base_url, default_model = _provider_endpoint(args.provider)
    if not models:
        models = [default_model]
    # дедупликация с сохранением порядка
    models = list(dict.fromkeys(models))
    key = _api_key(args.provider)

    if args.arm in ("graph_first", "file_graph_first", "temporal_first", "temporal_blind_first",
                    "temporal_duo_first"):
        if not args.ev_contexts:
            print(f"ERROR: arm {args.arm} требует --ev-contexts <contexts_*.json>",
                  file=sys.stderr)
            return 2
        _load_graph_contexts(Path(args.ev_contexts))

    if args.dry_run:
        arms = ["memory_first", "code_first"] if args.arm == "both" else [args.arm]
        print(f"DRY-RUN: facts={len(facts)} sha256={fingerprint} arms={args.arm} "
              f"provider={args.provider} base={base_url} models={models}")
        for f in facts[:2]:
            for arm in arms:
                p = _prompt(f, arm)
                _assert_no_truth_leak(f, p)
                print(f"  [{f['id']}] arm={arm} truth={f['truth']} leak-guard=OK | {p[:100]}...")
        print("DRY-RUN OK (модель не вызывалась, leak-guard пройден).")
        return 0

    if args.provider == "opencode":
        if _opencode_bin() is None:
            print("LIVE-ARM: opencode не установлен. Установите: npm install -g opencode-ai")
            print("  Затем ключ: opencode auth login → OpenCode Zen → вставить API key")
            return 2
    elif not key:
        print(f"LIVE-ARM ({args.provider}): ключ не найден. Добавьте в .env проекта:")
        if args.provider == "openrouter":
            print("  OPENROUTER_API_KEY=sk-or-v1-...")
            print("  (модель по умолч.: qwen/qwen3.7-flash)")
        else:
            print("  DEEPSEEK_API_KEY=<OpenCode Zen API key>  (или LLM_API_KEY / ZEN_API_KEY)")
            print(f"  LLM_BASE_URL={base_url}  (по умолчанию)")
            print(f"  LLM_MODEL={DEFAULT_API_MODEL}  (по умолчанию)")
        return 2

    arms = ["memory_first", "code_first"] if args.arm == "both" else [args.arm]

    for m in models:
        progress_path = _progress_path(m, args.tag)
        report = _new_report(args, base_url, m, facts, fingerprint)
        # Всегда догружаем существующий прогресс (кроме --force) — защита от
        # затирания полных данных частичным прогоном с --limit (footgun 2026-08-14).
        if progress_path.exists() and not args.force:
            try:
                old = json.loads(progress_path.read_text(encoding="utf-8"))
                report["arms"] = old.get("arms", {})
                print("RESUME:", m, {k: len(v.get("results", [])) for k, v in report["arms"].items()})
            except Exception:  # noqa: BLE001 — битый прогресс не блокирует
                report["arms"] = {}
        for arm in arms:
            existing = report["arms"].get(arm, {})
            done_ids = (set() if args.force
                        else {r["id"] for r in existing.get("results", []) if not r.get("error")})
            print(f"--- model={m} arm={arm} (facts={len(facts)}, уже готово={len(done_ids)}) ---")
            arm_report = _run_arm(facts, arm, args.provider, key, m, base_url,
                                  delay=args.delay, skip_ids=done_ids,
                                  max_tokens=args.max_tokens, seed=args.seed,
                                  no_reasoning=args.no_reasoning,
                                  prompt_version=args.prompt_version, lang=args.prompt_lang,
                                  reasoning=args.reasoning, pin_provider=args.pin_provider)
            # Merge по id (последний результат побеждает) — retry-проходы не дублируют
            merged = {x["id"]: x for x in existing.get("results", [])}
            for x in arm_report["results"]:
                merged[x["id"]] = x
            merged_list = list(merged.values())
            summary = _summarize(merged_list, arm, args.provider, m)
            summary["results"] = merged_list
            report["arms"][arm] = summary
            _print_summary(summary)
            if summary["errors"]:
                print(f"  ERRORS: {len(summary['errors'])} "
                      f"(первый: {summary['errors'][0]['error'][:120]})")
        progress_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"PROGRESS SAVED: {progress_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
