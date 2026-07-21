"""
auto_doc_updater.py — автоматическое обновление документации.

По Тумблеру: чистая бизнес-логика, без MCP-зависимостей.

Триггеры:
1. После реиндекса (вызывается из слоя intelligence)
2. Pre-commit хук (через GitHooksInstaller)
3. Idle scheduler (фоновый поток)
4. По требованию (MCP-инструмент)

Что обновляет:
- docs/generated/MODULE_INDEX.md — документация из PropertyGraph
- README.md — tool count, языки, статус тестов
- KNOWN_ISSUES.md — синхронизация из AGENT_DIARY.md
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AutoDocUpdater:
    """Автоматическое обновление документации проекта.

    Usage:
        updater = AutoDocUpdater()
        report = updater.update_all("/path/to/project")
    """

    def __init__(self):
        self._doc_generator = None

    # ─── Public API ────────────────────────────────────────

    def update_all(self, project_root: str) -> str:
        """Запускает полное обновление документации.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Отчёт: что обновлено, что пропущено, ошибки.
        """
        root = Path(project_root).resolve()
        if not root.exists():
            return f"❌ Project root not found: {root}"

        steps: List[str] = []
        errors: List[str] = []

        # Шаг 1: generate_docs
        try:
            doc_path = self._update_generated_docs(root)
            steps.append(f"✅ Module docs: {doc_path}")
        except Exception as e:
            errors.append(f"❌ Module docs: {e}")

        # Шаг 2: README.md
        try:
            readme_changed = self._update_readme(root)
            steps.append(f"✅ README.md: {'обновлён' if readme_changed else 'актуален'}")
        except Exception as e:
            errors.append(f"❌ README.md: {e}")

        # Шаг 3: KNOWN_ISSUES.md синхронизация
        try:
            known_changed = self._sync_known_issues(root)
            steps.append(f"✅ KNOWN_ISSUES.md: {'синхронизирован' if known_changed else 'актуален'}")
        except Exception as e:
            errors.append(f"❌ KNOWN_ISSUES.md: {e}")

        # Собираем отчёт
        report_lines = [
            f"📋 AutoDoc Update — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"📁 Проект: {root}",
            "",
            *steps,
        ]
        if errors:
            report_lines.extend(["", "⚠️ Ошибки:", *errors])

        report = "\n".join(report_lines)
        logger.info("AutoDoc update complete:\n%s", report)
        return report

    def check_staleness(self, project_root: str) -> str:
        """Проверяет, устарела ли документация, без изменений.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Статус: актуально / что устарело.
        """
        root = Path(project_root).resolve()
        issues: List[str] = []

        # Проверка MODULE_INDEX.md
        doc_file = root / "docs" / "generated" / "MODULE_INDEX.md"
        if not doc_file.exists():
            issues.append("docs/generated/MODULE_INDEX.md не существует")
        else:
            age = datetime.now() - datetime.fromtimestamp(doc_file.stat().st_mtime)
            if age.days > 0 or age.seconds > 3600:
                issues.append(f"MODULE_INDEX.md старше 1ч ({age.seconds // 60}м)")

        # Проверка README tool count
        readme_path = root / "README.md"
        if readme_path.exists():
            text = readme_path.read_text(encoding="utf-8")
            actual_count = self._count_tools(root)
            if str(actual_count) not in text:
                issues.append(f"README.md: tool count устарел (ожидается {actual_count})")

        if not issues:
            return "✅ Документация актуальна"
        return "⚠️ Устарело:\n" + "\n".join(f"  • {i}" for i in issues)

    # ─── Internal: генерация docs ─────────────────────────

    def _update_generated_docs(self, root: Path) -> str:
        """Генерирует MODULE_INDEX.md."""
        from src.core.doc_generator import DocGenerator

        dg = DocGenerator()
        output_dir = str(root / "docs" / "generated")
        result = dg.generate(str(root), output_dir=output_dir)
        logger.info("Module docs generated: %s", result)
        return result

    # ─── Internal: обновление README.md ───────────────────

    def _count_tools(self, root: Path) -> int:
        """Считает количество MCP-инструментов по коду."""
        server_tools = root / "src" / "mcp" / "server_tools.py"
        if not server_tools.exists():
            return 0

        text = server_tools.read_text(encoding="utf-8")
        # Ищем паттерны регистрации инструментов
        tool_patterns = [
            r'@mcp\.tool\("',
            r'@mcp_app\.tool\("',
            r'name=name,',
            r'tool\(name=',
            r'class \w+Tool\b',
        ]
        count = 0
        for pattern in tool_patterns:
            count = max(count, text.count(pattern))
        return count

    def _update_readme(self, root: Path) -> bool:
        """Обновляет счетчики в README.md.

        Returns:
            True если были изменения.
        """
        readme_path = root / "README.md"
        if not readme_path.exists():
            return False

        text = readme_path.read_text(encoding="utf-8")

        # Собираем реальные метрики
        tool_count = self._count_tools(root)
        test_count = self._count_tests(root)
        lang_count = self._count_languages(root)

        # Обновляем tool count
        text = self._replace_between(
            text,
            "tools",
            str(tool_count),
        )

        # Обновляем test count (паттерн "N passed, 0 failed")
        test_match = re.search(r'\d+\s*passed', text)
        if test_match:
            old = test_match.group()
            new = f"{test_count} passed"
            if old != new:
                text = text.replace(old, new, 1)

        # Обновляем языки
        text = self._replace_between(
            text,
            "language",
            str(lang_count),
        )

        # Пишем только если были изменения
        old_text = readme_path.read_text(encoding="utf-8")
        if text != old_text:
            readme_path.write_text(text, encoding="utf-8")
            logger.info("README.md обновлён")
            return True
        return False

    def _count_tests(self, root: Path) -> int:
        """Считает количество тестовых функций."""
        tests_dir = root / "tests"
        if not tests_dir.exists():
            return 0
        count = 0
        for py_file in tests_dir.rglob("test_*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("def test_")
            count += text.count("async def test_")
        return count

    def _count_languages(self, root: Path) -> int:
        """Считает поддерживаемые языки из parser.py."""
        parser_path = root / "src" / "core" / "indexing" / "parser.py"
        if not parser_path.exists():
            return 0
        text = parser_path.read_text(encoding="utf-8")
        # Ищем словарь LANGUAGES или PARSE_EXTENSIONS
        lang_match = re.search(r'LANGUAGES\s*=\s*\{([^}]+)\}', text, re.DOTALL)
        if lang_match:
            return lang_match.group(1).count(":") + 1
        return 0

    @staticmethod
    def _replace_between(text: str, marker: str, new_value: str) -> str:
        """Заменяет число после маркера."""
        pattern = rf'(\b{marker}[^\d]*?)(\d+)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return text[:match.start(2)] + new_value + text[match.end(2):]
        return text

    # ─── Internal: синхронизация KNOWN_ISSUES.md ─────────

    def _sync_known_issues(self, root: Path) -> bool:
        """Синхронизирует KNOWN_ISSUES.md из AGENT_DIARY.md.

        Находит записи о багах/фиксах в AGENT_DIARY.md и добавляет
        их в KNOWN_ISSUES.md если их там ещё нет.
        """
        diary_path = root / "AGENT_DIARY.md"
        known_path = root / "KNOWN_ISSUES.md"

        if not diary_path.exists() or not known_path.exists():
            return False

        diary_text = diary_path.read_text(encoding="utf-8")
        known_text = known_path.read_text(encoding="utf-8")

        # Ищем записи об инцидентах в AGENT_DIARY
        new_entries: List[str] = []
        for match in re.finditer(
            r'## \[([^\]]+)\]\s*—\s*([^\n]+)\n(.*?)(?=\n## |\Z)',
            diary_text,
            re.DOTALL,
        ):
            date = match.group(1)
            title = match.group(2)
            body = match.group(3).strip()

            # Пропускаем если уже есть в KNOWN_ISSUES
            if title in known_text:
                continue
            # Пропускаем если не содержит информации о багах/фиксах
            if not any(kw in body.lower() for kw in ["fix", "баг", "bug", "исправлен"]):
                continue

            new_entries.append(
                f"\n## {date} — {title}\n\n"
                f"- **Источник:** AGENT_DIARY.md\n"
                f"- **Описание:** {body[:200]}...\n"
                f"- **Статус:** автоматически синхронизировано\n"
            )

        if not new_entries:
            return False

        # Добавляем новые записи перед последней строкой
        new_text = known_text.rstrip() + "\n" + "\n".join(new_entries) + "\n"
        known_path.write_text(new_text, encoding="utf-8")
        logger.info("KNOWN_ISSUES.md: добавлено %d записей", len(new_entries))
        return True
"""