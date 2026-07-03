import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("mscodebase_configurator")

class ZedSmartConfigurator:
    """Умная система управления и автоматического внедрения настроек в Zed."""

    def __init__(self, extension_root: Optional[Path] = None):
        # Автоматически определяем корень расширения, если не передан явный путь
        self.ext_root = extension_root or Path(__file__).resolve().parent.parent.parent
        self.zed_dir = self._find_zed_config_dir()
        self.settings_path = self.zed_dir / "settings.json"

    def _find_zed_config_dir(self) -> Path:
        """Находит папку глобальных настроек Zed в зависимости от ОС."""
        if sys.platform == "win32":
            base = Path(os.getenv("APPDATA", os.path.expanduser("~\\AppData\\Roaming")))
            return base / "Zed"
        elif sys.platform == "darwin":
            return Path(os.path.expanduser("~/.config/zed"))
        else:
            return Path(os.path.expanduser("~/.config/zed"))

    def get_correct_venv_python(self) -> Path:
        """Вычисляет абсолютный путь к python.exe внутри venv этого расширения."""
        if sys.platform == "win32":
            return self.ext_root / "venv" / "Scripts" / "python.exe"
        return self.ext_root / "venv" / "bin" / "python"

    def _load_settings(self) -> Dict[str, Any]:
        """Безопасно читает текущие настройки Zed."""
        if not self.settings_path.exists():
            return {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                # Очищаем возможные BOM-символы
                content = f.read().strip()
                return json.loads(content) if content else {}
        except json.JSONDecodeError:
            logger.error(f"Файл {self.settings_path} поврежден или содержит невалидный JSON. Создаем бэкап.")
            self._backup_settings()
            return {}
        except Exception as e:
            logger.error(f"Не удалось прочитать настройки: {e}")
            return {}

    def _backup_settings(self):
        """Создает резервную копию настроек перед модификацией."""
        if self.settings_path.exists():
            backup_path = self.settings_path.with_suffix(".json.bak")
            try:
                backup_path.write_text(self.settings_path.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info(f"Создан бэкап настроек: {backup_path}")
            except Exception as e:
                logger.error(f"Ошибка при создании бэкапа: {e}")

    def patch_settings(self) -> bool:
        """Умное внедрение и синхронизация серверов на базе единого VENV."""
        try:
            self.zed_dir.mkdir(parents=True, exist_ok=True)
            self._backup_settings()

            settings = self._load_settings()
            python_path = str(self.get_correct_venv_python().resolve())
            lsp_main_path = str((self.ext_root / "src" / "lsp_main.py").resolve())

            # Инициализация базовых структур данных
            if "context_servers" not in settings:
                settings["context_servers"] = {}
            if "context_servers_to_query" not in settings:
                settings["context_servers_to_query"] = []
            if "lsp" not in settings:
                settings["lsp"] = {}
            if "languages" not in settings:
                settings["languages"] = {}

            # 1. Синхронизация MCP Context Server (Умный инжект venv)
            settings["context_servers"]["mscodebase-intelligence"] = {
                "command": python_path,
                "args": ["-u", "-m", "src.main"],
                "current_dir": "$ZED_WORKTREE_ROOT",
                "env": {
                    "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
                    "PYTHONPATH": "$ZED_WORKTREE_ROOT"
                }
            }

            if "mscodebase-intelligence" not in settings["context_servers_to_query"]:
                settings["context_servers_to_query"].append("mscodebase-intelligence")

            # 2. Синхронизация LSP сервера
            settings["lsp"]["mscodebase-lsp"] = {
                "command": python_path,
                "arguments": ["-u", lsp_main_path]
            }

            # 3. Привязка поддерживаемых языков к нашему LSP
            supported_languages = ["Python", "TypeScript", "Rust", "Go", "JavaScript"]
            for lang in supported_languages:
                if lang not in settings["languages"]:
                    settings["languages"][lang] = {}
                if "language_servers" not in settings["languages"][lang]:
                    settings["languages"][lang]["language_servers"] = []

                if "mscodebase-lsp" not in settings["languages"][lang]["language_servers"]:
                    settings["languages"][lang]["language_servers"].append("mscodebase-lsp")

            # Атомарная запись изменений обратно в файл настроек Zed
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

            logger.info("Умная конфигурация успешно внедрена в settings.json.")
            return True

        except Exception as e:
            logger.error(f"Критическая ошибка при патче настроек Zed: {e}")
            return False

    def remove_settings(self) -> bool:
        """Полная очистка следов расширения при деинсталляции."""
        if not self.settings_path.exists():
            return True

        try:
            settings = self._load_settings()

            # Удаляем MCP
            if "context_servers" in settings:
                settings["context_servers"].pop("mscodebase-intelligence", None)
            if "context_servers_to_query" in settings:
                if "mscodebase-intelligence" in settings["context_servers_to_query"]:
                    settings["context_servers_to_query"].remove("mscodebase-intelligence")

            # Удаляем LSP
            if "lsp" in settings:
                settings["lsp"].pop("mscodebase-lsp", None)

            # Очищаем привязки к языкам
            if "languages" in settings:
                for lang in settings["languages"].values():
                    if "language_servers" in lang and "mscodebase-lsp" in lang["language_servers"]:
                        lang["language_servers"].remove("mscodebase-lsp")

            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

            logger.info("Следы расширения успешно удалены из настроек Zed.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении настроек: {e}")
            return False

if __name__ == "__main__":
    # Точка входа для отладки или прямого вызова из инсталлятора
    logging.basicConfig(level=logging.INFO)
    configurator = ZedSmartConfigurator()
    configurator.patch_settings()
