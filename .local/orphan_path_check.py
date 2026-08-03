"""Проверка формата путей в индексе vs детектор orphans (health.py)."""
import os
from pathlib import Path

PROJECT = Path(r"D:\Project\MSCodeBase")


def main() -> int:
    from src.core.artifact_paths import get_db_path
    import lancedb

    db_path = get_db_path(PROJECT)
    print(f"DB: {db_path}")
    db = lancedb.connect(str(db_path))
    tbl = db.open_table("codebase_chunks")
    df = tbl.to_pandas()["file_path"].unique()[:2000]
    print(f"Всего уникальных путей в индексе (выборка): {len(df)}")

    # Форматы
    backslash = sum(1 for p in df if "\\" in p)
    forward = sum(1 for p in df if "/" in p and "\\" not in p)
    abs_fwd = sum(1 for p in df if p.startswith("D:/") or p.startswith("C:/"))
    print(f"с обратным слэшем: {backslash}")
    print(f"с прямым слэшем (не abs): {forward}")
    print(f"абсолютные (D:/...): {abs_fwd}")
    print("Примеры:", list(df[:8]))

    # Диск (как в health.py)
    disk = set()
    for p in PROJECT.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(PROJECT)).replace(os.sep, "/")
            disk.add(rel)
    print(f"Файлов на диске: {len(disk)}")

    # Орфаны по текущей логике health.py
    index_set = set(df)
    orphans = index_set - disk
    print(f"orphans по текущей логике: {len(orphans)}")

    # Орфаны с нормализацией слэшей
    index_norm = {p.replace("\\", "/") for p in df}
    orphans_norm = index_norm - disk
    print(f"orphans после нормализации слэшей: {len(orphans_norm)}")
    if orphans_norm:
        print("Примеры не-найденных:", list(orphans_norm)[:5])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
