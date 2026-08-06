"""Тесты опционального language-pack слоя (Workstream B).

Проверяют:
1. Выключенный гейт (по умолчанию): слой не активен, стандартное поведение.
2. Включённый гейт (MSCODEBASE_LANGUAGE_PACK=true) + установленный пакет:
   регистрация парсеров новых языков и SCM-символы (.lua).
3. Fallback queries: язык без вендоренного tags.scm берёт query из language-pack.
4. Фильтр мусорных имён (макро-грамматики).

Пакет tree-sitter-language-pack в dev-окружении установлен (extra).
"""
import re

import pytest

from src.core import language_pack


@pytest.fixture(autouse=True)
def _reset_language_pack():
    """Сбрасывает модульное состояние между тестами."""
    language_pack._tried = False
    language_pack._enabled = False
    language_pack._parsers.clear()
    language_pack._tags.clear()
    yield
    language_pack._tried = False
    language_pack._enabled = False
    language_pack._parsers.clear()
    language_pack._tags.clear()


class TestDisabledByDefault:
    def test_env_gate_off(self, monkeypatch):
        monkeypatch.delenv("MSCODEBASE_LANGUAGE_PACK", raising=False)
        assert not language_pack.is_enabled()
        result = language_pack.try_enable()
        assert result["enabled"] is False
        assert "MSCODEBASE_LANGUAGE_PACK" in result["reason"]


@pytest.fixture()
def enabled(monkeypatch):
    pytest.importorskip("tree_sitter_language_pack")
    monkeypatch.setenv("MSCODEBASE_LANGUAGE_PACK", "true")
    return language_pack.try_enable()


class TestEnabled:
    def test_registers_parsers_and_tags(self, enabled):
        assert enabled["enabled"] is True
        assert enabled["languages"] >= 50
        assert enabled["tags_queries"] >= 50
        assert ".lua" in enabled["extensions"]

    def test_lua_scm_symbols(self, enabled, tmp_path):
        from src.core.indexing.parser import CodeParser

        parser = CodeParser()
        f = tmp_path / "sample.lua"
        f.write_text(
            "local M = {}\n"
            "function M.greet(name)\n"
            "    return 'Hi ' .. name\n"
            "end\n"
            "local function helper()\n"
            "    return 42\n"
            "end\n",
            encoding="utf-8",
        )
        _, symbols = parser.parse_file(f)
        names = {s["name"] for s in symbols}
        assert "greet" in names
        assert "helper" in names
        # мусор макро-грамматик отфильтрован (валидные идентификаторы)
        for s in symbols:
            assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s["name"])

    def test_no_garbage_from_macro_grammars(self, enabled):
        """Известный шум (elixir) исключён из карты — не регистрируется."""
        assert "elixir" not in language_pack.LANG_EXT_MAP
        assert ".ex" not in enabled["extensions"]

    def test_excluded_conflict_matlab(self, enabled):
        """MATLAB пропущен: .m пересекается с Objective-C."""
        assert "matlab" not in language_pack.LANG_EXT_MAP


class TestFileGuardExtension:
    def test_dynamic_extensions_propagate(self, enabled):
        from src.core.extensions import DYNAMIC_EXTENSIONS
        from src.core.indexing.file_guard import FileGuard

        assert ".lua" in DYNAMIC_EXTENSIONS
        assert ".lua" in FileGuard.SUPPORTED_EXTENSIONS
