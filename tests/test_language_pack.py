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
    result = language_pack.try_enable()
    if result["enabled"] is False:
        # Парсеры пакет качает по сети при первом использовании. На CI-раннере
        # 53 запроса манифеста упираются в лимит GitHub, и слой честно не
        # поднимается — это состояние окружения, а не дефект кода. Пропуск с
        # причиной вместо красного теста; локально (парсеры в кэше) тесты идут.
        failed = result.get("failed") or []
        if any("Download error" in f for f in failed):
            pytest.skip(
                "language-pack parsers unavailable: "
                f"{failed[0] if failed else 'download failed'}"
            )
    elif ".lua" not in result.get("extensions", []):
        # Частичный сбой сети: слой поднялся, но lua не скачался (наблюдение
        # 2026-11-08: GitHub отдаёт манифесты не для всех языков подряд).
        failed = [f for f in (result.get("failed") or []) if f.startswith("lua:")]
        if any("Download error" in f for f in failed):
            pytest.skip(f"language-pack lua parser unavailable: {failed[0]}")
    return result


class TestEnabled:
    def test_registers_parsers_and_tags(self, enabled):
        # Диагностика в сообщении: в чистом venv пакет качает парсеры по сети,
        # и без этого текста падение «False is True» ничего не объясняет.
        assert enabled["enabled"] is True, f"language pack не поднялся: {enabled}"
        # 53 языка из LANG_EXT_MAP получают парсер в 1.25.0.
        assert enabled["languages"] >= 50
        # tags.scm в 1.25.0 есть для 49 языков: queries для cuda/sflog/soql/sosl
        # пакет больше не поставляет (в 1.14.3 было 51). Порог 45 держит guard
        # живым, не завязываясь на точный номер версии пакета.
        assert enabled["tags_queries"] >= 45
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
