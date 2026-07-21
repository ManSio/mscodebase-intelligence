"""
Тесты для Relation Extractor.
"""

import subprocess
import tempfile
from pathlib import Path

from src.core.commit_memory import CommitMemory
from src.core.relation_extractor import RelationExtractor


class TestRelationExtractor:
    """Тесты RelationExtractor."""

    def _init_git(self, path: Path):
        """Инициализирует git репозиторий."""
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)

    def _create_multi_file_commit(self, path: Path, files: dict, message: str):
        """Создаёт коммит с несколькими файлами."""
        for name, content in files.items():
            (path / name).write_text(content)
        subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True)

    def test_cochange_relations(self):
        """Извлекает связи со-изменения."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            # Два файла всегда меняются вместе
            for i in range(3):
                self._create_multi_file_commit(
                    tmp_path,
                    {"a.py": f"a = {i}", "b.py": f"b = {i}"},
                    f"Update both files #{i}"
                )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            relations = extractor.extract_cochange_relations(min_frequency=2)

            assert len(relations) > 0
            # Проверяем что связь a.py <-> b.py есть
            found = any(
                (r["source"] == "a.py" and r["target"] == "b.py") or
                (r["source"] == "b.py" and r["target"] == "a.py")
                for r in relations
            )
            assert found

    def test_bug_correlations(self):
        """Извлекает связи через баг-фиксы."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            # Баг-фикс затрагивает два файла
            self._create_multi_file_commit(
                tmp_path,
                {"auth.py": "x = 1", "session.py": "y = 1"},
                "Fix: resolve auth bug"
            )
            self._create_multi_file_commit(
                tmp_path,
                {"auth.py": "x = 2", "session.py": "y = 2"},
                "Fix: another auth issue"
            )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            relations = extractor.extract_bug_correlations()

            assert len(relations) > 0
            # Проверяем что auth.py и session.py связаны через баги
            found = any(
                (r["source"] == "auth.py" and r["target"] == "session.py") or
                (r["source"] == "session.py" and r["target"] == "auth.py")
                for r in relations
            )
            assert found

    def test_build_knowledge_graph(self):
        """Строит граф знаний."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_multi_file_commit(
                tmp_path,
                {"a.py": "a = 1", "b.py": "b = 1", "c.py": "c = 1"},
                "Initial commit"
            )
            self._create_multi_file_commit(
                tmp_path,
                {"a.py": "a = 2", "b.py": "b = 2"},
                "Fix: update a and b"
            )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            graph = extractor.build_knowledge_graph()

            assert len(graph) > 0
            # a.py должен быть связан с b.py
            assert "a.py" in graph or "b.py" in graph

    def test_get_related_files(self):
        """Находит связанные файлы."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            # a.py и b.py меняются вместе
            for i in range(3):
                self._create_multi_file_commit(
                    tmp_path,
                    {"a.py": f"a = {i}", "b.py": f"b = {i}", "c.py": "c = 0"},
                    f"Update #{i}"
                )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            extractor.build_knowledge_graph()

            related = extractor.get_related_files("a.py", max_depth=1)

            assert len(related) > 0
            # b.py должен быть связан с a.py
            files = [r["file"] for r in related]
            assert "b.py" in files

    def test_get_related_files_depth_2(self):
        """Находит связанные файлы через посредника (depth=2)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            # a+b вместе (2 раза), b+c вместе (2 раза) → a связан с c через b
            for i in range(2):
                self._create_multi_file_commit(
                    tmp_path, {"a.py": str(i), "b.py": str(i)}, f"AB #{i}"
                )
            for i in range(2):
                self._create_multi_file_commit(
                    tmp_path, {"b.py": str(i+10), "c.py": str(i)}, f"BC #{i}"
                )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            extractor.build_knowledge_graph()

            related = extractor.get_related_files("a.py", max_depth=2)

            # c.py должен быть достижим через b.py
            files = [r["file"] for r in related]
            assert "c.py" in files, f"Expected c.py in related files, got: {files}"

    def test_relation_summary(self):
        """Сводка по связям."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_multi_file_commit(
                tmp_path,
                {"a.py": "1", "b.py": "1"},
                "Initial"
            )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            summary = extractor.get_relation_summary()

            assert "total_relations" in summary
            assert "by_type" in summary

    def test_empty_repo(self):
        """Пустой репозиторий — нет связей."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory)
            relations = extractor.extract_cochange_relations()

            assert relations == []

    def test_no_symbol_index(self):
        """Работает без SymbolIndex."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_multi_file_commit(
                tmp_path, {"a.py": "1", "b.py": "1"}, "Commit"
            )

            memory = CommitMemory(tmp_path)
            extractor = RelationExtractor(memory, symbol_index=None)
            relations = extractor.extract_all_relations()

            assert "cochange" in relations
            assert "bug_correlation" in relations
            # call_graph не должно быть если symbol_index=None
            assert "call_graph" not in relations
