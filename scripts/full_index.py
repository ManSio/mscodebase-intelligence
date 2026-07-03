"""Полная индексация проекта с LM Studio."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.indexer import Indexer
from src.core.remote_embedder import RemoteEmbedder
from src.core.file_guard import FileGuard

project_root = Path(__file__).resolve().parent.parent
db_path = project_root / ".codebase_indices" / "lancedb_v2" / "mscodebase.db"

print(f"🚀 Индексация проекта: {project_root}")
print(f"📁 БД: {db_path}")

embedder = RemoteEmbedder(port=1234)
fg = FileGuard(project_root)
indexer = Indexer(db_path, embedder, fg, project_path=project_root)

count = indexer.index_project(project_root)
print(f"✅ Проиндексировано {count} чанков")

status = indexer.get_status()
print(f"📊 Статус: {status}")
