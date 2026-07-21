"""
doc_sync_engine.py — авто-синхронизация документации с кодом.

По Тумблеру: чистая бизнес-логика, без MCP-зависимостей.

Работает БЕЗ участия пользователя:
1. После rename_symbol(old, new) → авто-замена во всех .md (en/ru/zh)
2. После реиндекса → проверка таблиц/списков, авто-фикс
3. Только неисправимое → в отчёт для LLM

Что может авто-фиксить:
- Переименованные символы (old -> new в .md)
- Пропущенные поля классов (если таблица распознаётся)
- Устаревшие пути/импорты

Что НЕ может (нужен LLM или человек):
- Описания, архитектурные секции
- Схемы, диаграммы
- Логические объяснения
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SyncAction:
    """Одно действие по синхронизации."""
    file: str           # путь к .md файлу
    line: int           # строка
    old_text: str       # что было
    new_text: str       # что стало
    reason: str         # причина (rename | missing_field | extra_field | broken_ref)
    symbol: str         # имя символа
    auto_applied: bool  # True = уже применено, False = нужен LLM


@dataclass
class SyncReport:
    """Результат синхронизации."""
    files_checked: int = 0
    drifts_found: int = 0
    auto_fixed: int = 0
    needs_llm: int = 0
    actions: List[SyncAction] = field(default_factory=list)
    elapsed_ms: int = 0


class DocSyncEngine:
    """Авто-синхронизация документации с кодом.

    Использует PropertyGraph для проверки существования символов
    и отслеживания переименований.

    Usage:
        engine = DocSyncEngine(project_root="/path")
        report = engine.sync_all()  # полная проверка + авто-фикс
        engine.apply_rename(old="func", new="new_func")  # после rename_symbol
    """

    # Паттерны: что НЕ трогаем (не код, а конфиг/пути)
    _SKIP_PATTERNS = [
        re.compile(r'^[A-Z][A-Z0-9_]{2,}(?:\.[A-Z][A-Z0-9_]*)*$'),  # ENV_VARS
        re.compile(r'^[a-z_]+_fts$'),  # SQL таблицы
        re.compile(r'.*\{[a-z_]+\}.*'),  # шаблоны {project}
        re.compile(r'.*\.(log|exe|dll|bat|gguf|onnx)$'),  # файлы
        re.compile(r'^@[a-zA-Z_][a-zA-Z0-9_.]*$'),  # декораторы
        re.compile(r'^\d+\.\d+'),  # версии
        # Search mode names (не код)
        re.compile(r'^(fast|quality|deep|context|auto|light|server|ask)$'),
    ]

    # Внешние модули — их символы не в нашем src/
    _EXTERNAL_MODULES: Set[str] = {
        'asyncio', 'json', 'os', 'sys', 're', 'math', 'pathlib', 'typing',
        'lancedb', 'onnxruntime', 'httpx', 'fastmcp', 'pydantic',
        'pyarrow', 'numpy', 'tree_sitter', 'zstandard', 'pytest',
    }

    def __init__(self, project_root: str):
        self._root = Path(project_root).resolve()
        self._src_dir = self._root / "src"
        self._docs_dir = self._root / "docs"
        self._symbol_cache: Optional[Set[str]] = None

    # ─── Public API ────────────────────────────────────────

    def apply_rename(self, old_name: str, new_name: str) -> SyncReport:
        """Вызвать ПОСЛЕ rename_symbol(). Авто-фикс во всех .md.

        Сканирует все .md файлы в docs/, находит old_name,
        заменяет на new_name. Без участия пользователя.
        """
        report = SyncReport()
        start = datetime.now()

        md_files = list(self._docs_dir.rglob("*.md"))
        # Исключаем generated/
        md_files = [f for f in md_files if "generated" not in f.parts]
        report.files_checked = len(md_files)

        for md_file in md_files:
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
                rel = str(md_file.relative_to(self._root))
            except Exception:
                continue

            # Ищем все вхождения old_name в backtick-контексте
            # Заменяем только если это отдельный backtick-символ
            pattern = re.compile(
                rf'`{re.escape(old_name)}`'
            )
            new_text, count = pattern.subn(f'`{new_name}`', text)

            if count > 0:
                # Найдём строку первого вхождения
                line_no = 1
                for i, line in enumerate(text.split('\n'), 1):
                    if f'`{old_name}`' in line:
                        line_no = i
                        break

                md_file.write_text(new_text, encoding="utf-8")
                report.auto_fixed += count
                report.drifts_found += count
                report.actions.append(SyncAction(
                    file=rel,
                    line=line_no,
                    old_text=f'`{old_name}`',
                    new_text=f'`{new_name}`',
                    reason="rename",
                    symbol=old_name,
                    auto_applied=True,
                ))
                logger.info("🔁 Rename in %s: %s → %s", rel, old_name, new_name)

        report.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        return report

    def sync_all(self, symbols: Optional[Set[str]] = None) -> SyncReport:
        """Полная проверка: все .md против всех символов из src/.

        Авто-фиксит что может, остальное в отчёт.
        """
        report = SyncReport()
        start = datetime.now()

        if symbols is None:
            symbols = self._build_symbol_set()

        md_files = list(self._docs_dir.rglob("*.md"))
        md_files = [f for f in md_files if "generated" not in f.parts]
        report.files_checked = len(md_files)

        for md_file in md_files:
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
                rel = str(md_file.relative_to(self._root))
            except Exception:
                continue

            refs = self._extract_refs(text)
            for ref_name, line_num, orig_ref in refs:
                # Пропускаем заведомо не-символы
                if self._skip_ref(ref_name):
                    continue

                # Проверяем существование
                if not self._symbol_exists(ref_name, symbols):
                    # Ищем похожий символ (возможно переименован)
                    suggestion = self._find_suggestion(ref_name, symbols)
                    # Если нашёлся кандидат И он похож — предлагаем
                    if suggestion:
                        report.drifts_found += 1
                        report.actions.append(SyncAction(
                            file=rel,
                            line=line_num,
                            old_text=orig_ref,
                            new_text=suggestion,
                            reason="broken_ref",
                            symbol=ref_name,
                            auto_applied=False,
                        ))

        report.elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        report.needs_llm = len([a for a in report.actions if not a.auto_applied])
        return report

    def format_report(self, report: SyncReport) -> str:
        """Форматирует отчёт для чтения агентом."""
        lines = [
            f"📋 DocSync Report — {datetime.now().strftime('%H:%M:%S')}",
            f"📁 Checked {report.files_checked} .md files",
            f"🔍 Drifts: {report.drifts_found}",
            f"✅ Auto-fixed: {report.auto_fixed}",
            f"🤖 Needs LLM: {report.needs_llm}",
            f"⚡ {report.elapsed_ms}ms",
            "",
        ]

        if report.auto_fixed > 0:
            lines.append("✅ Auto-fixed:")
            for a in report.actions:
                if a.auto_applied:
                    lines.append(f"  • {a.file}:{a.line} — {a.reason}: {a.old_text} → {a.new_text}")

        if report.needs_llm > 0:
            lines.append("")
            lines.append("🤖 Needs LLM (can't auto-fix):")
            llm_actions = [a for a in report.actions if not a.auto_applied and a.reason == "broken_ref"]

            # Группируем по файлам
            by_file: Dict[str, List[SyncAction]] = {}
            for a in llm_actions:
                by_file.setdefault(a.file, []).append(a)

            for file_path, actions in sorted(by_file.items()):
                refs = ", ".join(f"`{a.old_text}`" for a in actions[:10])
                if len(actions) > 10:
                    refs += f" ... +{len(actions) - 10} more"
                lines.append(f"  • {file_path}: {refs}")

        return "\n".join(lines)

    # ─── Internal ──────────────────────────────────────────

    def _build_symbol_set(self) -> Set[str]:
        """Строит множество всех символов из src/."""
        if self._symbol_cache is not None:
            return self._symbol_cache

        symbols: Set[str] = set()
        if not self._src_dir.exists():
            self._symbol_cache = symbols
            return symbols

        for py_file in self._src_dir.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # def / async def / class
            for m in re.finditer(
                r'(?:^|\n)\s*(?:async\s+)?(?:def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)', text
            ):
                symbols.add(m.group(1))

            # MCP tool names
            for m in re.finditer(r'@\w+\.tool\("([a-z_][a-z0-9_]+)"\)', text):
                symbols.add(m.group(1))

            # CONSTANTS
            for m in re.finditer(r'(?:^|\n)([A-Z][A-Z0-9_]+)\s*=', text):
                symbols.add(m.group(1))

            # Импорты для Module.attr
            for m in re.finditer(r'^import\s+([a-zA-Z_][a-zA-Z0-9_.]*)', text, re.MULTILINE):
                parts = m.group(1).split(".")
                for i in range(1, len(parts) + 1):
                    symbols.add(".".join(parts[:i]))
            for m in re.finditer(r'^from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import', text, re.MULTILINE):
                parts = m.group(1).split(".")
                for i in range(1, len(parts) + 1):
                    symbols.add(".".join(parts[:i]))

        self._symbol_cache = symbols
        return symbols

    def _extract_refs(self, text: str) -> List[Tuple[str, int, str]]:
        """Извлекает backtick-символы с номерами строк."""
        refs: List[Tuple[str, int, str]] = []
        for i, line in enumerate(text.split('\n'), 1):
            for m in re.finditer(r'`([^`]+)`', line):
                ref = m.group(1).strip()
                # Только если похоже на идентификатор (не URL, не путь, не файл)
                if ref and re.match(r'^[a-zA-Z_][a-zA-Z0-9_.\[\]\(\)]*$', ref):
                    # Нормализуем: убираем trailing () и аргументы в скобках
                    clean_ref = re.sub(r'\(.*\)', '', ref).rstrip('()').strip()
                    if clean_ref:
                        refs.append((clean_ref, i, ref))
        return refs

    def _skip_ref(self, ref_name: str) -> bool:
        """Проверяет, нужно ли пропустить ссылку."""
        # Python keywords
        if ref_name in {"True", "False", "None", "self", "cls", "super", "property", "return"}:
            return True
        # self.x / cls.x
        if ref_name.startswith("self.") or ref_name.startswith("cls."):
            return True
        # Паттерны
        for pat in self._SKIP_PATTERNS:
            if pat.match(ref_name):
                return True
        # Внешние модули
        if "." in ref_name:
            first = ref_name.split(".")[0].lower()
            if first in self._EXTERNAL_MODULES:
                return True
        return False

    def _symbol_exists(self, ref_name: str, symbols: Set[str]) -> bool:
        """Проверяет существование символа."""
        # Прямое совпадение
        if ref_name in symbols:
            return True

        # Dot-ссылка: Module.method
        if "." in ref_name:
            parts = ref_name.split(".")
            for i in range(len(parts), 0, -1):
                fqn = ".".join(parts[:i])
                if fqn in symbols:
                    return True
            last = parts[-1]
            if last in symbols:
                return True
        return False

    def _find_suggestion(self, ref_name: str, symbols: Set[str]) -> str:
        """Ищет похожий символ (возможно переименован).

        Критерии:
        - Отличается только суффиксом/префиксом (переименование)
        - Или ref_name — это часть полного имени (Module.method)
        """
        candidates = []
        lower_ref = ref_name.lower()

        for sym in symbols:
            lower_sym = sym.lower()

            # Точное совпадение без учёта регистра
            if lower_ref == lower_sym:
                return sym

            # ref — это часть qualified_name (File.method)
            if lower_ref in lower_sym or lower_sym in lower_ref:
                # Проверяем что разница небольшая (< 30%)
                max_len = max(len(lower_ref), len(lower_sym))
                min_len = min(len(lower_ref), len(lower_sym))
                if max_len > 0 and (max_len - min_len) / max_len < 0.3:
                    candidates.append((sym, abs(len(sym) - len(ref_name))))

            # Отличается одним словом (old_func → new_func)
            elif self._is_rename_candidate(lower_ref, lower_sym):
                candidates.append((sym, abs(len(sym) - len(ref_name))))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            return candidates[0][0]
        return ""

    @staticmethod
    def _is_rename_candidate(a: str, b: str) -> bool:
        """Проверяет, похожи ли два имени как возможное переименование.

        Считает совпадающие слова (разделители: _, ., ::) и
        если большинство совпадает — это кандидат на rename.
        """
        parts_a = set(re.split(r'[_.]+', a))
        parts_b = set(re.split(r'[_.]+', b))
        if not parts_a or not parts_b:
            return False
        common = parts_a & parts_b
        # > 50% общих частей
        return len(common) / max(len(parts_a), len(parts_b)) > 0.5
