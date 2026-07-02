"""
Semantic Commit Memory — хранение и анализ истории изменений кода.

Связывает:
- git commits с изменёнными файлами
- файлы с символами
- символы с бизнес-контекстом

Позволяет отвечать на вопросы:
- "Почему изменилась эта- "Какие файлы обычно меняются вместе?"
- "Какие баги были связаны с этим модулем?"
"""

import hashlib
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("commit_memory")


class CommitMemory:
    """Семантическая память коммитов."""

    def __init__(self, project_path: Path, cache_dir: Optional[Path] = None):
        # Fix Windows path issue with /d/ style paths
        resolved = project_path.resolve()
        resolved_str = str(resolved)
        # Check for D:\d\ pattern (wrong from /d/ path)
        if len(resolved_str) > 4 and resolved_str[2] == "\\" and resolved_str[3] == "d" and resolved_str[4] == "\\":
            # D:\d\... -> D:\...
            resolved = Path(resolved_str[:2] + resolved_str[4:])
        self.project_path = resolved
        self.cache_dir = cache_dir or (self.project_path / ".codebase_indices" / "commit_memory")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self.cache_dir / "commits.json"
        self._commits: List[Dict] = []
        self._load_cache()

    def _load_cache(self):
        """Загрузка кэша коммитов."""
        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._commits = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load commit cache: {e}")
                self._commits = []

    def _save_cache(self):
        """Сохранение кэша коммитов."""
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._commits, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save commit cache: {e}")

    def fetch_commits(self, limit: int = 100) -> List[Dict]:
        """Получает историю коммитов из git.

        Args:
            limit: Максимальное количество коммитов

        Returns:
            Список коммитов с метаданными
        """
        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={limit}", "--pretty=format:%H|%an|%ae|%ad|%s", "--date=iso", "--name-only"],
                capture_output=True, text=True, timeout=30,
                cwd=str(self.project_path),
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode != 0:
                return []

            commits = []
            current_commit = None

            for line in result.stdout.strip().split("\n"):
                if "|" in line and not line.startswith(" "):
                    # Строка коммита: hash|author|email|date|subject
                    parts = line.split("|", 4)
                    if len(parts) >= 5:
                        if current_commit:
                            commits.append(current_commit)
                        current_commit = {
                            "hash": parts[0],
                            "author": parts[1],
                            "email": parts[2],
                            "date": parts[3],
                            "message": parts[4],
                            "files": [],
                        }
                elif line.strip() and current_commit:
                    # Строка файла
                    current_commit["files"].append(line.strip())

            if current_commit:
                commits.append(current_commit)

            self._commits = commits
            self._save_cache()

            return commits

        except Exception as e:
            logger.error(f"Failed to fetch commits: {e}")
            return []

    def get_commits_for_file(self, file_path: str) -> List[Dict]:
        """Находит все коммиты изменившие конкретный файл.

        Args:
            file_path: Относительный путь к файлу

        Returns:
            Список коммитов
        """
        if not self._commits:
            self.fetch_commits()

        return [c for c in self._commits if file_path in c.get("files", [])]

    def get_commits_for_symbol(self, symbol_name: str, file_path: str = "") -> List[Dict]:
        """Находит коммиты связанные с символом.

        Ищет по:
        1. Упоминанию символа в сообщении коммита
        2. Изменению файла содержащего символ

        Args:
            symbol_name: Имя символа
            file_path: Файл где символ определён

        Returns:
            Список коммитов
        """
        if not self._commits:
            self.fetch_commits()

        results = []
        for commit in self._commits:
            # Проверяем упоминание в сообщении
            if symbol_name.lower() in commit.get("message", "").lower():
                results.append(commit)
                continue

            # Проверяем изменение файла
            if file_path and file_path in commit.get("files", []):
                results.append(commit)

        return results

    def get_cochange_frequency(self) -> Dict[str, int]:
        """Анализирует какие файлы часто меняются вместе.

        Returns:
            {file_pair: frequency}
        """
        if not self._commits:
            self.fetch_commits()

        cochange = {}

        for commit in self._commits:
            files = commit.get("files", [])
            # Для каждой пары файлов в коммите
            for i, f1 in enumerate(files):
                for f2 in files[i + 1:]:
                    pair = tuple(sorted([f1, f2]))
                    key = f"{pair[0]}|{pair[1]}"
                    cochange[key] = cochange.get(key, 0) + 1

        return dict(sorted(cochange.items(), key=lambda x: x[1], reverse=True))

    def get_file_stability(self, file_path: str) -> Dict:
        """Анализирует "стабильность" файла.

        Стабильный файл — редко меняется.
        Нестабильный — часто меняется (возможные проблемы).

        Args:
            file_path: Путь к файлу

        Returns:
            Метрики стабильности
        """
        commits = self.get_commits_for_file(file_path)

        if not commits:
            return {
                "file": file_path,
                "change_count": 0,
                "first_change": None,
                "last_change": None,
                "stability": "unknown",
            }

        dates = [c.get("date", "") for c in commits if c.get("date")]
        dates.sort()

        return {
            "file": file_path,
            "change_count": len(commits),
            "first_change": dates[0] if dates else None,
            "last_change": dates[-1] if dates else None,
            "stability": "stable" if len(commits) < 5 else "unstable",
        }

    def get_commit_summary(self, commit_hash: str) -> Optional[Dict]:
        """Получает информацию о конкретном коммите.

        Args:
            commit_hash: Хэш коммита

        Returns:
            Информация о коммите
        """
        if not self._commits:
            self.fetch_commits()

        for commit in self._commits:
            if commit.get("hash", "").startswith(commit_hash):
                return commit

        return None

    def search_commits(self, query: str) -> List[Dict]:
        """Поиск коммитов по сообщению.

        Args:
            query: Поисковый запрос

        Returns:
            Список подходящих коммитов
        """
        if not self._commits:
            self.fetch_commits()

        query_lower = query.lower()
        results = []

        for commit in self._commits:
            message = commit.get("message", "").lower()
            if query_lower in message:
                results.append(commit)

        return results

    def find_similar_bugs(self, error_message: str, max_results: int = 5) -> List[Dict]:
        """Находит похожие баги из истории коммитов.

        Ищет по ключевым словам из error_message в коммитах с fix/bug/hotfix.

        Args:
            error_message: Описание ошибки или исключения
            max_results: Максимум результатов

        Returns:
            Список похожих баг-фиксов с контекстом
        """
        if not self._commits:
            self.fetch_commits()

        # Извлекаем ключевые слова из ошибки
        keywords = self._extract_keywords(error_message)

        # Ищем только в баг-фиксах
        bug_keywords = ['fix', 'bug', 'hotfix', 'resolve', 'error', 'crash', 'issue']
        bug_commits = [
            c for c in self._commits
            if any(bk in c.get("message", "").lower() for bk in bug_keywords)
        ]

        # Скоринг по совпадению ключевых слов
        scored = []
        for commit in bug_commits:
            message = commit.get("message", "").lower()
            score = sum(1 for kw in keywords if kw in message)
            if score > 0:
                scored.append((score, commit))

        # Сортируем по score
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, commit in scored[:max_results]:
            results.append({
                "hash": commit.get("hash", "")[:8],
                "message": commit.get("message", ""),
                "date": commit.get("date", ""),
                "files": commit.get("files", []),
                "relevance_score": score,
            })

        return results

    def _extract_keywords(self, text: str) -> List[str]:
        """Извлекает ключевые слова из текста ошибки."""
        # Убираем общие слова
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'can', 'cannot',
            'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from',
            'and', 'or', 'but', 'not', 'no', 'if', 'then', 'else',
            'this', 'that', 'it', 'its', 'my', 'your', 'our',
        }

        # Разбиваем на слова, фильтруем
        words = text.lower().split()
        keywords = [
            w.strip('.,;:()[]{}')
            for w in words
            if w.strip('.,;:()[]{}') not in stop_words
            and len(w.strip('.,;:()[]{}')) > 2
        ]

        return keywords[:10]  # Топ-10 ключевых слов

    def get_hotspots(self, min_changes: int = 5) -> List[Dict]:
        """Находит 'горячие точки' — файлы с частыми изменениями.

        Args:
            min_changes: Минимум изменений для включения

        Returns:
            Список файлов с метриками изменений
        """
        if not self._commits:
            self.fetch_commits()

        # Считаем изменения по файлам
        file_changes: Dict[str, Dict] = {}

        for commit in self._commits:
            message = commit.get("message", "").lower()
            is_bugfix = any(bk in message for bk in ['fix', 'bug', 'hotfix', 'resolve'])

            for f in commit.get("files", []):
                if f not in file_changes:
                    file_changes[f] = {
                        "total": 0,
                        "bugfixes": 0,
                        "last_change": None,
                    }
                file_changes[f]["total"] += 1
                if is_bugfix:
                    file_changes[f]["bugfixes"] += 1
                file_changes[f]["last_change"] = commit.get("date", "")

        # Фильтруем и сортируем
        hotspots = []
        for f, metrics in file_changes.items():
            if metrics["total"] >= min_changes:
                bug_ratio = metrics["bugfixes"] / metrics["total"]
                hotspots.append({
                    "file": f,
                    "total_changes": metrics["total"],
                    "bugfix_changes": metrics["bugfixes"],
                    "bug_ratio": round(bug_ratio, 2),
                    "risk": "high" if bug_ratio > 0.3 else "medium" if bug_ratio > 0.1 else "low",
                    "last_change": metrics["last_change"],
                })

        hotspots.sort(key=lambda x: x["bug_ratio"], reverse=True)
        return hotspots

    def get_stats(self) -> Dict:
        """Статистика коммитов."""
        if not self._commits:
            self.fetch_commits()

        if not self._commits:
            return {"total": 0}

        authors = {}
        for commit in self._commits:
            author = commit.get("author", "unknown")
            authors[author] = authors.get(author, 0) + 1

        return {
            "total": len(self._commits),
            "authors": authors,
            "cached": self._cache_file.exists(),
        }
