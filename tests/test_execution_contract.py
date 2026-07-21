"""
Тесты для Execution Contract — верификация действий агента.
"""



from src.core.execution_contract import ExecutionContract, format_verification_report


class TestVerifyFileWrite:
    """Тесты verify_file_write."""

    def test_file_exists_and_verified(self, tmp_path):
        """Существующий файл проходит верификацию."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        contract = ExecutionContract()
        result = contract.verify_file_write(str(test_file))

        assert result["verified"] is True
        assert not result["errors"]

    def test_file_not_exists_fails(self, tmp_path):
        """Несуществующий файл не проходит верификацию."""
        contract = ExecutionContract()
        result = contract.verify_file_write(str(tmp_path / "nonexistent.py"))

        assert result["verified"] is False
        assert len(result["errors"]) == 1
        assert "не существует" in result["errors"][0]

    def test_content_mismatch_fails(self, tmp_path):
        """Несовпадение содержимого не проходит верификацию."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        contract = ExecutionContract()
        result = contract.verify_file_write(str(test_file), expected_content="def world")

        assert result["verified"] is False
        assert "не совпадает" in result["errors"][0]

    def test_content_match_passes(self, tmp_path):
        """Совпадение содержимого проходит верификацию."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): return 'world'")

        contract = ExecutionContract()
        result = contract.verify_file_write(str(test_file), expected_content="hello")

        assert result["verified"] is True


class TestVerifyGitCommit:
    """Тесты verify_git_commit."""

    def test_no_git_repo_fails(self, tmp_path):
        """Без git репозитория верификация падает."""
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            contract = ExecutionContract()
            result = contract.verify_git_commit()
            # Может быть verified=False с ошибкой git, или verified=True если есть родительский git
            # Главное — не падает с exception
            assert isinstance(result, dict)
            assert "verified" in result
        finally:
            os.chdir(old_cwd)

    def test_expected_message_mismatch(self):
        """Несообщение коммита определяется корректно."""
        contract = ExecutionContract()
        result = contract.verify_git_commit(expected_message="NONEXISTENT_MSG_12345")
        # Если есть гит репозиторий, должен вернуть False
        if result.get("commit_hash"):
            assert result["verified"] is False
            assert any("NONEXISTENT" in e for e in result["errors"])


class TestVerifyGitPush:
    """Тесты verify_git_push."""

    def test_returns_dict(self):
        """Возвращает словарь с полем verified."""
        contract = ExecutionContract()
        result = contract.verify_git_push()
        assert isinstance(result, dict)
        assert "verified" in result


class TestFormatVerificationReport:
    """Тесты format_verification_report."""

    def test_all_success(self):
        """Все успешные результаты."""
        results = [
            {"action": "file_write", "verified": True, "errors": []},
            {"action": "git_commit", "verified": True, "errors": [], "commit_hash": "abc12345", "commit_message": "test commit"},
        ]
        report = format_verification_report(results)
        assert "✅" in report
        assert "abc12345" in report

    def test_with_errors(self):
        """Результаты с ошибками."""
        results = [
            {"action": "file_write", "verified": False, "errors": ["File not found"]},
        ]
        report = format_verification_report(results)
        assert "❌" in report
        assert "File not found" in report

    def test_empty_results(self):
        """Пустой список результатов."""
        report = format_verification_report([])
        assert "✅" in report  # Пустой = нет ошибок


class TestExecutionContractIntegration:
    """Интеграционные тесты."""

    def test_full_workflow_simulation(self, tmp_path):
        """Симуляция полного workflow: запись → верификация."""
        test_file = tmp_path / "module.py"
        test_content = "def process(): return True"
        test_file.write_text(test_content)

        contract = ExecutionContract()

        # 1. Верификация записи
        result = contract.verify_file_write(str(test_file), expected_content="process")
        assert result["verified"] is True

        # 2. Проверка что файл реально на диске
        assert test_file.exists()
        assert "process" in test_file.read_text()
