"""Trust-стор плагинов (Фаза 4, план §5.2/§5.6).

Хранит доверие per (plugin_id, version) с пином sha256 полезной нагрузки
(файла entrypoint). Решение «доверяю» не переносится между версиями и не
переживает дрейф хэша — любое изменение содержимого требует нового решения.

JSON-файл в data_root/plugins/trust.json (артефакт вне проекта). Атомарная
запись (tmp + replace) — защита от коррапции при крэше.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

TRUST_DECISION = "trusted"


class PluginTrustStore:
    def __init__(self, path: Path):
        self._path = path
        self._entries: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except json.JSONDecodeError:
            # Повреждённый файл доверия != паника: не пускаем доверенные плагины
            # молча — начнём с пустого (переспросим), но не роняем сервер.
            data = {}
        self._entries = data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._entries, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def decision(self, plugin_id: str, version: str) -> Optional[dict]:
        """Возвращает запись доверия для (id, version) или None если не трекается."""
        return self._entries.get(f"{plugin_id}@{version}")

    def is_trusted(self, plugin_id: str, version: str, sha256: str) -> bool:
        entry = self.decision(plugin_id, version)
        if not entry or entry.get("decision") != TRUST_DECISION:
            return False
        return entry.get("sha256") == sha256

    def trust(self, plugin_id: str, version: str, sha256: str, source: str) -> None:
        """Фиксирует доверие (после решения пользователя) для (id, version, sha256)."""
        self._entries[f"{plugin_id}@{version}"] = {
            "decision": TRUST_DECISION,
            "sha256": sha256,
            "source": source,
            "trusted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        self._save()

    def revoke(self, plugin_id: str, version: str) -> None:
        self._entries.pop(f"{plugin_id}@{version}", None)
        self._save()

    def all(self) -> dict:
        return dict(self._entries)
