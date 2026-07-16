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

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("commit_memory")


class CommitMemory:
    """Семантическая память коммитов."""

    def __init__(self, project_path: Path, cache_dir: Optional[Path] = None):
        # Fix Windows path issue with /d/ style paths
        resolved = project_path.resolve()
        resolved_str = str(resolved)
        # Check for D:\d\ pattern (wrong from /d/ path)
        if (
            len(resolved_str) > 4
            and resolved_str[2] == "\\"
            and resolved_str[3] == "d"
            and resolved_str[4] == "\\"
        ):
            # D:\d\... -> D:\...
            resolved = Path(resolved_str[:2] + resolved_str[4:])
        self.project_path = resolved
        self.cache_dir = cache_dir or (
            self.project_path / ".codebase_indices" / "commit_memory"
        )
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
        """Получает историю коммитов из .git/logs/HEAD (без subprocess).

        Args:
            limit: Максимальное количество коммитов

        Returns:
            Список коммитов с метаданными
        """
        import zlib

        git_dir = self.project_path / '.git'
        reflog_path = git_dir / 'logs' / 'HEAD'
        if not reflog_path.exists():
            logger.warning(f".git/logs/HEAD not found: {reflog_path}")
            return []

        try:
            reflog_raw = reflog_path.read_text('utf-8', errors='replace')
        except Exception as e:
            logger.error(f"Failed to read reflog: {e}")
            return []

        lines = reflog_raw.strip().split('\n')
        # Последние limit строк (новые коммиты в конце)
        recent = lines[-limit:] if len(lines) > limit else lines

        commits = []
        seen_hashes: set = set()

        for line in recent:
            if not line.strip():
                continue
            parts = line.split(' ', 2)
            if len(parts) < 2:
                continue
            new_hash = parts[1].strip()
            # Пропускаем нулевые хеши (merge, initial)
            if len(new_hash) < 10 or new_hash.count('0') == len(new_hash):
                continue
            if new_hash in seen_hashes:
                continue
            seen_hashes.add(new_hash)

            # Парсим reflog: "old_hash new_hash committer <timestamp> tz\tmessage"
            rest = parts[2] if len(parts) > 2 else ''
            reflog_msg = rest.split('\t', 1)[-1] if '\t' in rest else ''

            # Читаем объект коммита из .git/objects/
            obj_path = git_dir / 'objects' / new_hash[:2] / new_hash[2:]
            if not obj_path.exists():
                continue

            try:
                compressed = obj_path.read_bytes()
                raw = zlib.decompress(compressed)

                # Парсим commit объект: "commit <size>\0<content>"
                if b'\x00' in raw:
                    content = raw.split(b'\x00', 1)[1]
                else:
                    content = raw.split(b'\n', 1)[1] if b'\n' in raw else raw

                # Извлекаем заголовки (до двойного \n\n)
                header_end = content.find(b'\n\n')
                msg_raw = content[header_end + 2:].decode('utf-8', 'replace') if header_end != -1 else ''
                msg_lines = msg_raw.strip().split('\n')
                subject = msg_lines[0] if msg_lines else reflog_msg
                body = '\n'.join(msg_lines[1:]) if len(msg_lines) > 1 else ''

                # Парсим заголовки: tree, parent, author, committer
                header_part = content[:header_end].decode('utf-8', 'replace') if header_end != -1 else ''
                author = ''
                email = ''
                date_str = ''
                for hdr_line in header_part.split('\n'):
                    if hdr_line.startswith('author '):
                        # "author Name <email> timestamp timezone"
                        hdr = hdr_line[7:]
                        if '<' in hdr:
                            author = hdr.split('<')[0].strip()
                            email_part = hdr.split('<')[1].split('>')[0]
                            email = email_part
                            ts_part = hdr.split('>')[-1].strip().split()
                            if ts_part:
                                date_str = ts_part[0]

                commit = {
                    "hash": new_hash,
                    "author": author or 'unknown',
                    "email": email or '',
                    "date": date_str or '',
                    "message": subject,
                    "body": body[:200] if body else '',
                    "files": [],  # список файлов не парсим (сложно), но не критично
                }
                commits.append(commit)
            except Exception:
                continue

            if len(commits) >= limit:
                break

        self._commits = commits
        self._save_cache()

        return commits

    def compute_co_change_matrix(
        self, min_co_changes: int = 3
    ) -> Dict[str, Dict[str, float]]:
        """Вычисляет матрицу совместных изменений (co-change coupling).

        Формула: coupling(A, B) = co_changes(A, B) / max(changes(A), changes(B))

        Args:
            min_co_changes: минимальное число совместных изменений для включения

        Returns:
            {file_a: {file_b: coupling_strength, ...}, ...}
            Только файлы с coupling >= 0.3 и >= min_co_changes.
        """
        if not self._commits:
            self.fetch_commits()
        if not self._commits:
            return {}

        # Считаем частоту изменений каждого файла
        file_changes: Dict[str, int] = {}
        # Считаем совместные изменения пар файлов
        co_changes: Dict[str, Dict[str, int]] = {}

        for commit in self._commits:
            files = commit.get("files", [])
            for f in files:
                file_changes[f] = file_changes.get(f, 0) + 1
            for i, f1 in enumerate(files):
                for f2 in files[i + 1 :]:
                    if f1 not in co_changes:
                        co_changes[f1] = {}
                    co_changes[f1][f2] = co_changes[f1].get(f2, 0) + 1
                    if f2 not in co_changes:
                        co_changes[f2] = {}
                    co_changes[f2][f1] = co_changes[f2].get(f1, 0) + 1

        # Вычисляем coupling strength
        matrix: Dict[str, Dict[str, float]] = {}
        for f1, partners in co_changes.items():
            for f2, count in partners.items():
                if count >= min_co_changes:
                    coupling = count / max(
                        file_changes.get(f1, 1), file_changes.get(f2, 1)
                    )
                    if coupling >= 0.3:
                        if f1 not in matrix:
                            matrix[f1] = {}
                        matrix[f1][f2] = round(coupling, 3)

        return matrix

    def get_commits_for_file(self, file_path: str) -> List[Dict]:
        """Находит все коммиты изменившие конкретный файл.

        Args:
            file_path: Относительный путь к файлу

        Returns:
            Список коммитов
        """
        if not self._commits:
            self.fetch_commits()

        # Fallback: если files пуст (новая реализация без subprocess) —
        # ищем по упоминанию файла в сообщении или теле коммита
        def _matches(c: dict) -> bool:
            if file_path in c.get("files", []):
                return True
            # Fallback: поиск в message + body
            fp_lower = file_path.lower()
            msg = (c.get("message", "") + " " + c.get("body", "")).lower()
            return fp_lower in msg
        return [c for c in self._commits if _matches(c)]

    def get_commits_for_symbol(
        self, symbol_name: str, file_path: str = ""
    ) -> List[Dict]:
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
                for f2 in files[i + 1 :]:
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
        bug_keywords = ["fix", "bug", "hotfix", "resolve", "error", "crash", "issue"]
        bug_commits = [
            c
            for c in self._commits
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
            results.append(
                {
                    "hash": commit.get("hash", "")[:8],
                    "message": commit.get("message", ""),
                    "date": commit.get("date", ""),
                    "files": commit.get("files", []),
                    "relevance_score": score,
                }
            )

        return results

    def _extract_keywords(self, text: str) -> List[str]:
        """Извлекает ключевые слова из текста ошибки."""
        # Убираем общие слова
        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "cannot",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "and",
            "or",
            "but",
            "not",
            "no",
            "if",
            "then",
            "else",
            "this",
            "that",
            "it",
            "its",
            "my",
            "your",
            "our",
        }

        # Разбиваем на слова, фильтруем
        words = text.lower().split()
        keywords = [
            w.strip(".,;:()[]{}")
            for w in words
            if w.strip(".,;:()[]{}") not in stop_words
            and len(w.strip(".,;:()[]{}")) > 2
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
            is_bugfix = any(bk in message for bk in ["fix", "bug", "hotfix", "resolve"])

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
                hotspots.append(
                    {
                        "file": f,
                        "total_changes": metrics["total"],
                        "bugfix_changes": metrics["bugfixes"],
                        "bug_ratio": round(bug_ratio, 2),
                        "risk": "high"
                        if bug_ratio > 0.3
                        else "medium"
                        if bug_ratio > 0.1
                        else "low",
                        "last_change": metrics["last_change"],
                    }
                )

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
