#!/usr/bin/env python
"""🧪 Диагностика БД индекса — проверка целостности без запуска MCP.

Запуск: python scripts/db_health.py [путь_к_проекту]
По умолчанию: D:\Project\MSCodeBase
"""
import sys, os, time
from pathlib import Path

def check_db(project_root: Path):
    print(f"🔍 Проверка индекса: {project_root}")
    print("=" * 60)

    # Ищем .codebase_indices
    indices_dir = project_root / ".codebase_indices"
    if not indices_dir.exists():
        print("❌ .codebase_indices не найден")
        return
    
    # Ищем LanceDB
    lance_dirs = list(indices_dir.rglob("*.lance"))
    if not lance_dirs:
        print("❌ LanceDB таблицы не найдены")
        return

    for ld in lance_dirs:
        print(f"\n📦 Таблица: {ld.relative_to(project_root)}")
        try:
            import lancedb
            db = lancedb.connect(str(ld.parent))
            tbl = db.open_table(ld.stem)
            
            count = tbl.count_rows()
            print(f"   Чанков: {count}")
            
            if count > 0:
                # Сэмпл данных
                sample = tbl.search().limit(3).to_pandas()
                print(f"   Колонки: {list(sample.columns)}")
                print(f"   Пример file_path: {sample['file_path'].tolist()[:3]}")
                unique_files = sample["file_path"].nunique()
                print(f"   Уникальных файлов (в сэмпле): {unique_files}")
                
                # Размерность векторов
                vec = sample["vector"].iloc[0]
                print(f"   Размерность вектора: {len(vec)}")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

    # Размер на диске
    total_size = sum(f.stat().st_size for f in indices_dir.rglob("*") if f.is_file())
    print(f"\n💾 Размер индекса на диске: {total_size / 1024 / 1024:.1f} MB")
    
    # Проверка логов
    log_dir = indices_dir / "logs"
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log*"))
        print(f"📋 Лог-файлов: {len(log_files)}")
        for lf in sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
            size_kb = lf.stat().st_size / 1024
            print(f"   {lf.name} ({size_kb:.0f} KB)")
    else:
        print("📋 Директория логов не найдена")

    # Проверка SymbolIndex
    si_file = indices_dir / "symbol_index.json"
    if si_file.exists():
        print(f"📊 SymbolIndex: {si_file.stat().st_size / 1024:.0f} KB")
    
    print("\n✅ Диагностика завершена")

if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\Project\MSCodeBase")
    check_db(root)
