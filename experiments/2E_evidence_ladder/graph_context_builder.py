#!/usr/bin/env python3
"""graph_context_builder.py — Exp 2-E, Rung 3 (graph_first): резолв якорей фактов
в структурированный evidence из PropertyGraph + grep-вхождений.

Детерминированный билдер (БЕЗ LLM): для каждого факта v4_rep строит нейтральный
текстовый блок "STRUCTURE", который затем вставляется в промпт arm'а graph_first.

Политика резолва (зеркалит _resolve_snippet из V4, но структурно):
  1. file:<path>      → FILE BLOCK: импорты файла (ast), символы файла (graph),
                        callers (graph).
  2. bare-токен      → a) graph-узел найден (find_definitions) → SYMBOL BLOCK:
                          определение (file:line, kind), callers (top 5), callees (top 5);
                       b) узла нет → grep src/**/*.py: OCCURS BLOCK: список файлов
                          с числом вхождений (top 8) — модель проверяет ПРИНАДЛЕЖНОСТЬ
                          субъекту, а не наличие токена (фикс present-trap);
                       c) ноль вхождений → токен отсутствует.
  3. НИ ОДИН якорь не резолвнулся (mutation_absent/silent) → ДЕКОЙ: graph-блок
     контрольного символа InstructionScan. Декой НЕ помечается в промпте (иначе
     утечка "not found" → тривиальный false), помечается в метаданных
     (evidence: "decoy") — та же политика, что в V4.

Выход: graph_contexts_<sha8>.json: {fact_id: {block, evidence, resolved_anchors, tokens}}
Truth-лейбл в выход НЕ попадает (leak-guard: assert "truth" not in block).

Usage:
  python experiments/2E_evidence_ladder/graph_context_builder.py [--facts PATH] [--out PATH]
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FACTS = ROOT / "experiments" / "1V_memory_contamination" / "memory_contamination_facts_v4_rep.json"
DEFAULT_OUT = ROOT / "experiments" / "2E_evidence_ladder"
SRC = ROOT / "src"

CONTROL_SYMBOL = "InstructionScan"          # декой для нерезолвящихся фактов (как CONTROL_FILE в V4)
CONTROL_FILE = "src/core/instruction_scan.py"
MAX_SYMBOL_BLOCKS = 3                        # максимум блоков на факт (бюджет токенов ~6k)
MAX_CALLERS = 5
MAX_CALLEES = 5
MAX_OCCUR_FILES = 8
MAX_FILE_IMPORTS = 10
MAX_FILE_SYMBOLS = 10


class GraphContextBuilder:
    """Резолвер якорей: PropertyGraph + ast-импорты + grep-вхождения."""

    def __init__(self, project_root: Path, enable_graph: bool = True):
        self.root = project_root
        self.adapter = None
        self.graph_ok = False
        if enable_graph:
            self._init_graph()

    def _init_graph(self) -> None:
        """Подключение к PropertyGraph проекта; при недоступности — fallback на occurrences."""
        try:
            sys.path.insert(0, str(self.root))
            from src.core.artifact_paths import get_graph_db_path
            from src.core.graph import PropertyGraph
            from src.core.search.graph_adapter import SymbolIndexAdapter

            db_path = get_graph_db_path(self.root)
            if db_path and Path(db_path).exists():
                pg = PropertyGraph(db_path)
                self.adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
                self.graph_ok = True
        except Exception as e:  # noqa: BLE001 — fallback детерминирован и задокументирован
            print(f"[builder] PropertyGraph недоступен ({e}); режим occurrences-only", file=sys.stderr)

    # ─── Резолв якорей ─────────────────────────────────────────────────────

    def resolve_anchors(self, patterns: list[str]) -> tuple[list[dict], bool]:
        """Возвращает (blocks, resolved_any). Каждый block — dict{kind, text}."""
        blocks: list[dict] = []
        for pat in patterns:
            if len(blocks) >= MAX_SYMBOL_BLOCKS:
                break
            pat = pat.strip()
            if not pat:
                continue
            if pat.startswith("file:"):
                b = self._file_block(pat[5:].strip())
            else:
                b = self._token_block(pat)
            if b:
                blocks.append(b)
        return blocks, bool(blocks)

    def _file_block(self, rel_path: str) -> dict | None:
        f = self.root / rel_path
        if not f.exists():
            return None
        lines: list[str] = []
        imports = _ast_imports(f)
        symbols = _ast_top_level(f)
        lines.append(f"FILE: {rel_path} ({'exists'})")
        if imports:
            lines.append(f"  imports ({len(imports)}): {', '.join(imports[:MAX_FILE_IMPORTS])}")
        if symbols:
            lines.append(f"  defines ({len(symbols)}): "
                         + ", ".join(f"{n}@{line}" for n, line in symbols[:MAX_FILE_SYMBOLS]))
        callers = self._callers_of_file(rel_path)
        if callers:
            lines.append(f"  used by ({len(callers)}): {', '.join(callers[:MAX_CALLERS])}")
        return {"kind": "file", "text": "\n".join(lines)}

    def _rel(self, p: str) -> str:
        """Абсолютный путь → относительный (бюджет токенов + нейтральность)."""
        try:
            return str(Path(p).resolve().relative_to(self.root.resolve())).replace("\\", "/")
        except (ValueError, OSError):
            return p.replace("\\", "/")

    def _callers_of_file(self, rel_path: str) -> list[str]:
        """Кто импортирует/использует символы файла — по graph CALLS-рёбрам."""
        if not self.graph_ok or self.adapter is None:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for name, _line in _ast_top_level(self.root / rel_path)[:8]:
            try:
                for ref in self.adapter.get_callers(name):
                    sig = f"{ref.symbol} @ {self._rel(ref.file_path)}:{ref.line}"
                    if sig not in seen:
                        seen.add(sig)
                        out.append(sig)
            except Exception:  # noqa: BLE001 — один символ не должен ронять блок
                continue
        return out

    def _token_block(self, token: str) -> dict | None:
        """Граф-узел (class/function) → SYMBOL BLOCK; иначе → OCCURS BLOCK.

        module-узлы (артефакты импортов: pathlib/logging/re) НЕ дают структуры —
        для них список файлов-вхождений информативнее (проверка принадлежности
        субъекту, а не наличия токена).
        """
        if self.graph_ok and self.adapter is not None:
            try:
                defs = self.adapter.find_definitions(token)
            except Exception:  # noqa: BLE001
                defs = []
            real_defs = [d for d in defs
                         if any(k in str(getattr(d, "kind", "")).lower()
                                for k in ("class", "function", "method"))
                         and str(getattr(d, "file_path", "") or "").strip()
                         and getattr(d, "line", 0) > 0]
            if real_defs:
                return self._symbol_block(token, real_defs)
        return self._occurrences_block(token)

    def _symbol_block(self, token: str, defs: list) -> dict:
        lines = [f"SYMBOL: {token}"]
        d = defs[0]
        lines.append(f"  definition: {getattr(d, 'kind', '?')} @ "
                     f"{self._rel(getattr(d, 'file_path', '?'))}:{getattr(d, 'line', 0)}")
        if len(defs) > 1:
            lines.append(f"  (+{len(defs) - 1} more definitions)")
        try:
            callers = self.adapter.get_callers(token)[:MAX_CALLERS]
            if callers:
                lines.append("  called by:")
                for r in callers:
                    lines.append(f"    {r.symbol} @ {self._rel(r.file_path)}:{r.line}")
        except Exception:  # noqa: BLE001
            pass
        try:
            callees = self.adapter.get_callees(token)[:MAX_CALLEES]
            if callees:
                lines.append("  calls:")
                for c in callees:
                    sym = c.get("symbol", c.get("name", "?"))
                    fpath = c.get("file", c.get("file_path", "?"))
                    lines.append(f"    {sym} @ {self._rel(fpath)}:{c.get('line', 0)}")
        except Exception:  # noqa: BLE001
            pass
        return {"kind": "symbol", "text": "\n".join(lines)}

    def _occurrences_block(self, token: str) -> dict | None:
        """grep src/**/*.py: файлы с max-вхождениями (зеркало V4, но СПИСОК, не фрагмент)."""
        pat = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
        counts: Counter[str] = Counter()
        for f in SRC.rglob("*.py"):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            n = len(pat.findall(text))
            if n:
                counts[str(f.relative_to(self.root)).replace("\\", "/")] = n
        if not counts:
            return None
        top = counts.most_common(MAX_OCCUR_FILES)
        total = sum(counts.values())
        lines = [f"TOKEN: {token} — occurs in {len(counts)} files ({total} matches):"]
        for fpath, n in top:
            lines.append(f"  {fpath} ({n})")
        if len(counts) > MAX_OCCUR_FILES:
            lines.append(f"  ... +{len(counts) - MAX_OCCUR_FILES} more files")
        return {"kind": "occurrences", "text": "\n".join(lines)}


# ─── AST-хелперы ───────────────────────────────────────────────────────────

def _ast_imports(path: Path) -> list[str]:
    """Импорты файла: 'import x', 'from x import y' — в порядке появления."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(f"from {node.module} import {node.names[0].name}")
    return out


def _ast_top_level(path: Path) -> list[tuple[str, int]]:
    """Топ-уровневые классы/функции файла: [(name, lineno)]."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node.lineno))
    return out


# ─── Temporal-контексты (Rung 4) ────────────────────────────────────────────

def _anchor_path(anchors: list[str]) -> str | None:
    """Путь из file:-якоря (первый попавшийся) — для git-трейла."""
    for a in anchors:
        if a.startswith("file:"):
            return a[5:].strip()
    return None


def build_temporal_contexts(facts: list[dict], builder: GraphContextBuilder) -> dict:
    """Контексты для temporal_first: graph-блок HEAD + git-провенанс из фактов.

    Политика (отличается от build_contexts — НЕ декой!):
      resolved (real)     → обычный блок + 'GIT: last commit touching <path>';
      removed             → 'NOT FOUND AT HEAD' + 'GIT: existed at <commit> (<date>, <subject>)';
      absent              → 'NOT FOUND AT HEAD' + 'GIT: no history'.
    Git-данные берутся ИЗ ФАКТОВ (evidence_git/valid_at_commit), не из subprocess —
    детерминированно. Truth-лейбл не попадает в блок (assert ниже).
    """
    out: dict = {}
    for fact in facts:
        anchors = fact.get("support_patterns") or []
        blocks, resolved = builder.resolve_anchors(anchors)
        g = fact.get("evidence_git") or {}
        path = _anchor_path(anchors) or "?"
        if resolved:
            text = "\n\n".join(b["text"] for b in blocks)
            evidence = "real"
            if g.get("hash"):
                text += (f"\n\nGIT: last commit touching {path}: "
                         f"{g['hash'][:8]} {g.get('date', '?')} "
                         f"'{g.get('subject', '?')}' (branch {g.get('branch', '?')})")
        else:
            sym = fact.get("value") or (anchors[0] if anchors else "?")
            text = f"SYMBOL: {sym} — NOT FOUND AT HEAD"
            if fact.get("valid_at_commit") and g.get("hash"):
                evidence = "removed"
                text += (f"\n\nGIT: existed until commit {g['hash'][:8]} "
                         f"({g.get('date', '?')}, '{g.get('subject', '?')}', "
                         f"branch {g.get('branch', '?')})")
            else:
                evidence = "absent"
                text += f"\n\nGIT: no history found for {path}"
        assert "truth" not in text and "truth" not in str(anchors), f"leak in {fact['id']}"
        out[fact["id"]] = {
            "block": text,
            "evidence": evidence,
            "resolved_anchors": anchors,
            "tokens": max(1, len(text.split())),
        }
    return out


def build_temporal_blind_contexts(facts: list[dict], builder: GraphContextBuilder) -> dict:
    """Слепой контроль E4b: те же temporal-факты, БЕЗ git-строк в evidence.

    Проверяет red team атаку 4: «48/48 в E4 — артефакт лёгкости existence-claims
    (NOT FOUND AT HEAD подсказывает вердикт), а не git-провенанса».
    removed/absent → 'SYMBOL: X — NOT FOUND AT HEAD' (без 'existed until C');
    real → обычный блок (без 'GIT: last commit touching').
    """
    out: dict = {}
    for fact in facts:
        anchors = fact.get("support_patterns") or []
        blocks, resolved = builder.resolve_anchors(anchors)
        if resolved:
            text = "\n\n".join(b["text"] for b in blocks)
            evidence = "real"
        else:
            sym = fact.get("value") or (anchors[0] if anchors else "?")
            text = f"SYMBOL: {sym} — NOT FOUND AT HEAD"
            evidence = "removed" if fact.get("valid_at_commit") else "absent"
        assert "truth" not in text and "truth" not in str(anchors), f"leak in {fact['id']}"
        out[fact["id"]] = {
            "block": text,
            "evidence": evidence,
            "resolved_anchors": anchors,
            "tokens": max(1, len(text.split())),
        }
    return out


def _ast_names_from_text(text: str) -> list[str]:
    """Топ-уровневые классы/функции из текста (git show C:file)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    return [n.name for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]


def _git_symbols_at(commit: str, path: str, root: Path) -> list[str]:
    """Символы файла на коммите (git show; short-lived subprocess, §5.16 не про нас)."""
    import subprocess
    try:
        r = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        return []
    return _ast_names_from_text(r.stdout) if r.returncode == 0 else []


def build_temporal_duo_contexts(facts: list[dict], builder: GraphContextBuilder) -> dict:
    """E4c: ОДИН нейтральный evidence (HEAD + история) на факт, БЕЗ 'NOT FOUND AT HEAD'.

    Позволяет два вопроса: 'X определён в F' (now) и 'X был определён в F' (past).
      removed → HEAD-состояние файла (file-блок или 'deleted in commit C') +
                'SYMBOLS in F at <commit>: [...]' (из git show) — X виден в истории,
                но не в HEAD: ловушка для now, подтверждение для past;
      real    → обычный FILE-блок + 'GIT: last commit touching F';
      absent  → 'not found in repository history or current tree'.
    """
    out: dict = {}
    for fact in facts:
        anchors = fact.get("support_patterns") or []
        path = _anchor_path(anchors) or "?"
        g = fact.get("evidence_git") or {}
        blocks, resolved = builder.resolve_anchors(anchors)
        if fact.get("valid_at_commit") and g.get("hash"):
            commit = g["hash"]
            syms = _git_symbols_at(commit, path, builder.root) or \
                   _git_symbols_at(f"{commit}~1", path, builder.root)
            lines = [f"FILE: {path}"]
            if resolved:
                lines.append("  " + "\n  ".join(blocks[0]["text"].splitlines()[1:]))
            else:
                lines.append(f"  deleted in commit {commit[:8]} ({g.get('date', '?')}, "
                             f"'{g.get('subject', '?')}', branch {g.get('branch', '?')})")
            if syms:
                lines.append(f"  SYMBOLS in {path} at history ({len(syms)}): "
                             + ", ".join(syms[:12]))
            text = "\n".join(lines)
            evidence = "removed"
        elif resolved:
            text = "\n\n".join(b["text"] for b in blocks)
            if g.get("hash"):
                text += (f"\n\nGIT: last commit touching {path}: {g['hash'][:8]} "
                         f"{g.get('date', '?')} '{g.get('subject', '?')}' "
                         f"(branch {g.get('branch', '?')})")
            evidence = "real"
        else:
            sym = fact.get("value") or (anchors[0] if anchors else "?")
            text = (f"SYMBOL: {sym} — not found in repository history or current tree\n"
                    f"GIT: no commits touch {path}")
            evidence = "absent"
        assert "truth" not in text and "truth" not in str(anchors), f"leak in {fact['id']}"
        out[fact["id"]] = {
            "block": text,
            "evidence": evidence,
            "resolved_anchors": anchors,
            "tokens": max(1, len(text.split())),
        }
    return out


# ─── Main ──────────────────────────────────────────────────────────────────

def build_contexts(facts: list[dict], builder: GraphContextBuilder,
                   control: str | None = None) -> dict:
    """{fact_id: {block, evidence, resolved_anchors, token_count}} — без truth."""
    if control is None:
        control = _control_block(builder)
    out: dict = {}
    for fact in facts:
        anchors = fact.get("support_patterns") or []
        blocks, resolved = builder.resolve_anchors(anchors)
        if resolved:
            text = "\n\n".join(b["text"] for b in blocks)
            evidence = "real"
        else:
            text = control
            evidence = "decoy"
        assert "truth" not in text and "truth" not in str(anchors), f"leak in {fact['id']}"
        out[fact["id"]] = {
            "block": text,
            "evidence": evidence,
            "resolved_anchors": anchors,
            "tokens": max(1, len(text.split())),
        }
    return out


def _control_block(builder: GraphContextBuilder) -> str:
    """Graph-блок контрольного символа (декой) — как голова CONTROL_FILE в V4."""
    blocks, _ = builder.resolve_anchors([CONTROL_SYMBOL, f"file:{CONTROL_FILE}"])
    if blocks:
        return "\n\n".join(b["text"] for b in blocks)
    return f"SYMBOL: {CONTROL_SYMBOL} (structure unavailable)"


def main() -> int:
    facts_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FACTS
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    blind = len(sys.argv) > 3 and sys.argv[3] == "--blind"
    duo = len(sys.argv) > 3 and sys.argv[3] == "--duo"

    facts = json.loads(facts_path.read_text(encoding="utf-8"))["facts"]
    raw = facts_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()[:8]
    print(f"[builder] facts={facts_path.name} N={len(facts)} sha256[:8]={sha}")

    builder = GraphContextBuilder(ROOT)
    print(f"[builder] PropertyGraph: {'OK' if builder.graph_ok else 'UNAVAILABLE (occurrences-only)'}")

    is_temporal = "temporal" in facts_path.name or "valid_at_commit" in raw.decode("utf-8", "replace")
    if is_temporal and duo:
        ctx = build_temporal_duo_contexts(facts, builder)
    elif is_temporal and blind:
        ctx = build_temporal_blind_contexts(facts, builder)
    elif is_temporal:
        ctx = build_temporal_contexts(facts, builder)
    else:
        ctx = build_contexts(facts, builder)
    decoys = sum(1 for v in ctx.values() if v["evidence"] in ("decoy", "absent"))
    tok_avg = sum(v["tokens"] for v in ctx.values()) / len(ctx)
    print(f"[builder] contexts={len(ctx)} decoys/absent={decoys} avg_tokens={tok_avg:.0f}")

    prefix = "temporal_duo_contexts_" if (is_temporal and duo) else \
             ("temporal_blind_contexts_" if (is_temporal and blind) else \
              ("temporal_contexts_" if is_temporal else "graph_contexts_"))
    out_file = out_dir / f"{prefix}{sha}.json"
    out_file.write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[builder] written: {out_file.relative_to(ROOT)}")

    for fid in tuple(ctx)[:4]:
        v = ctx[fid]
        print(f"\n--- {fid} evidence={v['evidence']} tokens={v['tokens']} ---")
        print(v["block"][:800])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — §5.11: try/except в каждом скрипте
        import traceback
        traceback.print_exc()
        sys.exit(1)
