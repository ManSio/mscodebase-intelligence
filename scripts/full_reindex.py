"""
Полная переиндексация проекта MSCodeBase вне MCP-процесса.

Walk всех файлов → IndexParser → RemoteEmbedder → LanceDB.

Запуск:
    cd D:\\Project\\MSCodeBase
    C:\\Users\\misha\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence\\venv\\Scripts\\python.exe scripts\\full_reindex.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import time
import hashlib
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict

PROJECT_PATH = Path(r"D:\Project\MSCodeBase").resolve()
DB_PATH = PROJECT_PATH / ".codebase_indices" / "lancedb_v2" / "index_mscodebase_bfe9644b.db"
BATCH_SIZE = 4

def main():
    t_start = time.perf_counter()

    # ── 1. FileGuard ──────────────────────────────────────────
    print("🔍 Init FileGuard...")
    from src.core.indexing.file_guard import FileGuard
    file_guard = FileGuard(PROJECT_PATH)

    # ── 2. CodeParser + SafePathManager + IndexParser ─────────
    print("🔧 Init CodeParser + IndexParser...")
    from src.core.parser import CodeParser
    code_parser = CodeParser()

    from src.utils.paths import SafePathManager
    path_manager = SafePathManager(DB_PATH.parent)

    from src.core.indexing.index_parser import IndexParser
    index_parser = IndexParser(
        parser=code_parser,
        path_manager=path_manager,
        project_path=PROJECT_PATH,
    )

    # ── 3. RemoteEmbedder ─────────────────────────────────────
    print("🤖 Init RemoteEmbedder...")
    from src.providers.embedder.remote_embedder import RemoteEmbedder
    embedder = RemoteEmbedder()

    # Ждём готовности эмбеддера (до 120 сек)
    print("⏳ Waiting for embedder to be ready (up to 120s)...")
    for i in range(120):
        if embedder.is_ready():
            break
        if i % 10 == 9:
            print(f"   ...still waiting ({i+1}s)")
        time.sleep(1)

    mode = getattr(embedder, 'mode', 'unknown')
    dim = getattr(embedder, 'embedding_dim', None) or 384
    print(f"✅ Embedder ready: is_ready={embedder.is_ready()}, mode={mode}, dim={dim}")

    # ── 4. LanceDB ────────────────────────────────────────────
    print(f"📦 Connecting to LanceDB: {DB_PATH}")
    import lancedb
    db = lancedb.connect(str(DB_PATH))
    tbl = db.open_table("codebase_chunks")
    rows_before = tbl.count_rows()
    print(f"📊 Table rows before: {rows_before}")

    # ── 5. Walk files ─────────────────────────────────────────
    print("📂 Walking files...")
    all_files: List = []
    for root, dirs, files in os.walk(str(PROJECT_PATH)):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if not file_guard.should_skip_dir(d)]
        for fname in files:
            fp = Path(root) / fname
            if file_guard.should_skip_file(fp):
                continue
            rel = str(fp.relative_to(PROJECT_PATH))
            all_files.append((fp, rel))

    total = len(all_files)
    print(f"📄 Found {total} files to index")

    # ── 6. Process in batches ─────────────────────────────────
    indexed = 0
    failed = 0
    skipped = 0

    for i in range(0, total, BATCH_SIZE):
        batch = all_files[i:i+BATCH_SIZE]
        for fp, rel in batch:
            try:
                # Parse via IndexParser
                parsed = index_parser.parse_file(fp, rel)
                if parsed is None:
                    skipped += 1
                    continue

                chunk_texts = parsed.get("chunk_texts", [])
                if not chunk_texts:
                    skipped += 1
                    continue

                # Embed
                embeddings = embedder.embed_batch(chunk_texts)
                if not embeddings or len(embeddings) != len(chunk_texts):
                    print(f"  ⚠ Embedding mismatch {rel}: {len(embeddings)} vs {len(chunk_texts)}")
                    failed += 1
                    continue

                # Pad/truncate vectors
                for j, vec in enumerate(embeddings):
                    if len(vec) != dim:
                        embeddings[j] = vec[:dim] + [0.0] * (dim - len(vec))

                # Build records (same logic as LanceDBWriter.write_records)
                chunk_texts_full = parsed.get("chunk_texts_full", [])
                chunk_metadatas = parsed.get("chunk_metadatas", [])
                health = parsed.get("health", {})
                current_hash = parsed.get("current_hash",
                    hashlib.md5(b"").hexdigest())

                records = []
                for j, (txt, vec) in enumerate(zip(chunk_texts, embeddings)):
                    full_text = chunk_texts_full[j] if j < len(chunk_texts_full) else txt
                    meta = chunk_metadatas[j] if j < len(chunk_metadatas) else {}
                    records.append({
                        "id": f"{hashlib.md5(rel.encode()).hexdigest()}_{j}",
                        "vector": vec,
                        "text": txt,
                        "text_full": full_text,
                        "file_path": rel,
                        "file_hash": current_hash,
                        "chunk_index": j,
                        "source": "filesystem",
                        "indexed_at": datetime.now().isoformat(),
                        "summary": "",
                        "layer": meta.get("layer", ""),
                        "module_name": meta.get("module_name", ""),
                        "hierarchy_level": meta.get("hierarchy_level", "other"),
                        "is_public": meta.get("is_public", False),
                        "symbol_type": meta.get("symbol_type", ""),
                        "parent_id": meta.get("parent_id", ""),
                        "callees": meta.get("callees", ""),
                        "health_score": health.get("score", 0.0),
                        "health_band": health.get("band", ""),
                    })

                tbl.add(records)
                indexed += 1
                if indexed % 10 == 0:
                    pct = indexed * 100 // total if total else 0
                    print(f"  ✅ {indexed}/{total} ({pct}%) — last: {rel}")

            except Exception as e:
                print(f"  ❌ Error {rel}: {e}")
                import traceback
                traceback.print_exc()
                failed += 1

    elapsed = time.perf_counter() - t_start
    rows_after = tbl.count_rows()
    rows_added = rows_after - rows_before

    # ── Summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"🏁 INDEXING COMPLETE")
    print(f"   Files found:     {total}")
    print(f"   Indexed:         {indexed}")
    print(f"   Skipped:         {skipped}")
    print(f"   Failed:          {failed}")
    print(f"   Chunks added:    {rows_added}")
    print(f"   Total chunks:    {rows_after}")
    print(f"   Time:            {elapsed:.1f}s")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
