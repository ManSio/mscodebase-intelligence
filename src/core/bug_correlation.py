"""
Bug Correlation — анализ связи багов с изменениями в коде.

Связывает:
- Коммиты с ключевыми словами (fix, bug, hotfix, resolve) → "баг-фиксы"
- Баг-фиксы с файлами и символами
- Символы с "баго-историей" — сколько раз их правили из-за багов

Позволяет отвечать на вопросы:
- "Какие модули чаще всего ломаются?"
- "Какие файлы имеют наибольшую баго-нагрузку?"
- "Кто чаще всего правит этот модуль?"
"""

import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

__all__ = [
    "BugCorrelation",
]
logger = logging.getLogger("bug_correlation")

# Паттерны для определения баг-фиксов
BUGFIX_PATTERNS = [
    r'\bfix\b',
    r'\bbug\b',
    r'\bhotfix\b',
    r'\bresolve\b',
    r'\bpatch\b',
    r'\bworkaround\b',
    r'\bcorrect\b',
    r'\bissue\b',
    r'\bdefect\b',
    r'\bcrash\b',
    r'\berror\b',
    r'\bbroken\b',
]

BUGFIX_REGEX = re.compile('|'.join(BUGFIX_PATTERNS), re.IGNORECASE)


class BugCorrelation:
    """Анализ связи багов с изменениями в коде."""

    def __init__(self, commit_memory):
        """
        Args:
            commit_memory: Инстанс CommitMemory с загруженными коммитами
        """
        self.commit_memory = commit_memory
        self._bug_commits: List[Dict] = []
        self._file_bug_count: Dict[str, int] = {}
        self._symbol_bug_count: Dict[str, int] = {}
        self._analyzed = False

    def analyze(self) -> Dict[str, Any]:
        """Полный анализ баго-корреляции.

        Returns:
            Результаты анализа: баг-коммиты, статистика по файлам/символам
        """
        commits = self.commit_memory._commits
        if not commits:
            self.commit_memory.fetch_commits()
            commits = self.commit_memory._commits

        self._bug_commits = []
        self._file_bug_count = defaultdict(int)
        self._symbol_bug_count = defaultdict(int)

        for commit in commits:
            message = commit.get("message", "")
            if self._is_bugfix(message):
                self._bug_commits.append(commit)
                # Считаем баги по файлам
                for f in commit.get("files", []):
                    self._file_bug_count[f] += 1

        self._analyzed = True

        return {
            "total_commits": len(commits),
            "bugfix_commits": len(self._bug_commits),
            "bugfix_ratio": round(len(self._bug_commits) / max(len(commits), 1), 3),
            "top_buggy_files": self.get_top_buggy_files(10),
        }

    def _is_bugfix(self, message: str) -> bool:
        """Определяет является ли коммит баг-фиксом."""
        return bool(BUGFIX_REGEX.search(message))

    def get_bugfix_commits(self, limit: int = 50) -> List[Dict]:
        """Возвращает список баг-фикс коммитов."""
        if not self._analyzed:
            self.analyze()
        return self._bug_commits[:limit]

    def get_top_buggy_files(self, top_n: int = 10) -> List[Dict]:
        """Возвращает файлы с наибольшим количеством баг-фиксов.

        Returns:
            [{file, bug_count, total_commits, bug_ratio}]
        """
        if not self._analyzed:
            self.analyze()

        # Считаем общее количество коммитов по файлам
        file_total = defaultdict(int)
        for commit in self.commit_memory._commits:
            for f in commit.get("files", []):
                file_total[f] += 1

        # Сортируем по количеству багов
        sorted_files = sorted(
            self._file_bug_count.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]

        result = []
        for file_path, bug_count in sorted_files:
            total = file_total.get(file_path, 0)
            result.append({
                "file": file_path,
                "bug_count": bug_count,
                "total_commits": total,
                "bug_ratio": round(bug_count / max(total, 1), 3),
            })

        return result

    def get_bug_history_for_file(self, file_path: str) -> Dict:
        """Получает полную баго-историю файла.

        Args:
            file_path: Путь к файлу

        Returns:
            {file, bug_commits, total_commits, bug_risk}
        """
        if not self._analyzed:
            self.analyze()

        file_commits = self.commit_memory.get_commits_for_file(file_path)
        bug_commits = [c for c in file_commits if self._is_bugfix(c.get("message", ""))]

        # Определяем уровень риска
        total = len(file_commits)
        bug_count = len(bug_commits)
        ratio = bug_count / max(total, 1)

        if ratio >= 0.5:
            risk = "critical"
        elif ratio >= 0.3:
            risk = "high"
        elif ratio >= 0.1:
            risk = "medium"
        else:
            risk = "low"

        return {
            "file": file_path,
            "bug_commits": bug_commits,
            "total_commits": total,
            "bug_count": bug_count,
            "bug_ratio": round(ratio, 3),
            "bug_risk": risk,
        }

    def get_bug_history_for_symbol(self, symbol_name: str, file_path: str = "") -> Dict:
        """Получает баго-историю для символа.

        Args:
            symbol_name: Имя символа
            file_path: Файл где символ определён

        Returns:
            {symbol, file, bug_commits, risk}
        """
        if not self._analyzed:
            self.analyze()

        # Ищем коммиты связанные с символом
        symbol_commits = self.commit_memory.get_commits_for_symbol(symbol_name, file_path)
        bug_commits = [c for c in symbol_commits if self._is_bugfix(c.get("message", ""))]

        return {
            "symbol": symbol_name,
            "file": file_path,
            "bug_commits": bug_commits,
            "bug_count": len(bug_commits),
            "total_commits": len(symbol_commits),
            "bug_risk": "high" if len(bug_commits) >= 3 else "medium" if len(bug_commits) >= 1 else "low",
        }

    def get_hotspots(self, top_n: int = 10) -> List[Dict]:
        """Находит "горячие точки" — файлы с высокой баго-нагрузкой.

        Учитывает:
        - Количество баг-фиксов
        - Давность последнего баг-фикса
        - Частоту изменений

        Returns:
            [{file, bug_score, last_bugfix, risk}]
        """
        if not self._analyzed:
            self.analyze()

        hotspots = []
        now = datetime.now()

        for file_path, bug_count in self._file_bug_count.items():
            # Находим последний баг-фикс
            file_commits = self.commit_memory.get_commits_for_file(file_path)
            bug_commits = [c for c in file_commits if self._is_bugfix(c.get("message", ""))]

            last_bugfix = None
            if bug_commits:
                dates = [c.get("date", "") for c in bug_commits if c.get("date")]
                if dates:
                    last_bugfix = max(dates)

            # Считаем score: чем больше багов и чем свежее — тем выше
            recency_bonus = 0
            if last_bugfix:
                try:
                    bug_date = datetime.fromisoformat(last_bugfix)
                    days_ago = (now - bug_date).days
                    if days_ago < 30:
                        recency_bonus = 3
                    elif days_ago < 90:
                        recency_bonus = 1
                except (ValueError, TypeError):
                    pass

            score = bug_count * 2 + recency_bonus

            hotspots.append({
                "file": file_path,
                "bug_count": bug_count,
                "bug_score": score,
                "last_bugfix": last_bugfix,
                "risk": "critical" if score >= 10 else "high" if score >= 5 else "medium",
            })

        hotspots.sort(key=lambda x: x["bug_score"], reverse=True)
        return hotspots[:top_n]

    def get_stats(self) -> Dict:
        """Статистика баго-корреляции."""
        if not self._analyzed:
            self.analyze()

        return {
            "total_commits": len(self.commit_memory._commits),
            "bugfix_commits": len(self._bug_commits),
            "bugfix_ratio": round(len(self._bug_commits) / max(len(self.commit_memory._commits), 1), 3),
            "unique_buggy_files": len(self._file_bug_count),
            "top_risk_file": self.get_top_buggy_files(1)[0]["file"] if self._file_bug_count else None,
        }
