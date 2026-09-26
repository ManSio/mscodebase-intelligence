"""Decisive probe: is the index bloated by duplicates?

Snapshot the live LanceDB dir and count total rows vs unique file_path / chunk
text. If unique ~= total -> no bloat (the count is legitimate). If unique << total
-> duplicates (bloat). Read-only: works on a COPY, never the live DB.

Run: <venv-python> experiments/misc_probes/exp_index_dedup_probe.py <lancedb_dir>
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: exp_index_dedup_probe.py <lancedb_dir>")
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"not found: {src}")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="idxsnap_"))
    dst = tmp / src.name
    shutil.copytree(src, dst)
    print(f"snapshot: {dst}")

    import lancedb

    db = lancedb.connect(str(dst))
    names = list(db.table_names())
    print(f"tables: {names}")
    if not names:
        print("no tables")
        return 1
    t = db.open_table(names[0])
    n = t.count_rows()
    print(f"total rows: {n}")

    df = t.to_arrow().to_pandas()
    cols = list(df.columns)
    print(f"columns: {cols}")

    for key in ("file_path", "text", "chunk_hash", "content_hash", "file_hash"):
        if key in df.columns:
            uniq = df[key].nunique(dropna=False)
            dups = n - uniq
            print(f"  {key}: unique={uniq}  duplicates={dups}  ({dups/max(n,1)*100:.1f}%)")

    # Exact duplicate chunk texts (within the same file) = real bloat signal.
    if "text" in df.columns and "file_path" in df.columns:
        key2 = df["file_path"].astype(str) + "\u0000" + df["text"].astype(str)
        dup2 = int(key2.duplicated().sum())
        print(f"  (file_path+text) duplicate rows: {dup2} ({dup2/max(n,1)*100:.1f}%)")

    # THE bloat test: same file, same position indexed twice = stale version kept.
    for combo in (("file_path", "chunk_index"), ("file_path", "chunk_hash"),
                  ("file_path", "start_line", "end_line")):
        if all(k in df.columns for k in combo):
            s = df[list(combo)].astype(str).agg("\u0000".join, axis=1)
            d = int(s.duplicated().sum())
            print(f"  dup{combo}: {d} ({d/max(n,1)*100:.1f}%)")

    # Path normalisation: same file under "\" and "/" = duplicated rows (bloat).
    if "file_path" in df.columns:
        norm = df["file_path"].astype(str).str.replace("\\", "/", regex=False)
        raw_u, norm_u = int(df["file_path"].nunique()), int(norm.nunique())
        print(f"\n  file_path distinct: raw={raw_u} normalized={norm_u} "
              f"-> path-duplication={raw_u - norm_u}")
        ext = norm.str.rsplit(".", n=1).str[-1]
        print("  top extensions by rows:")
        for e, c in ext.value_counts().head(8).items():
            print(f"    .{e}: {c}")

    # Show WHY spans repeat: example rows sharing (file_path, start_line, end_line).
    if all(k in df.columns for k in ("file_path", "start_line", "end_line", "text")):
        span = df.groupby(["file_path", "start_line", "end_line"]).size()
        hot = span[span > 1].sort_values(ascending=False).head(3)
        for (fp, sl, el), cnt in hot.items():
            sub = df[(df["file_path"] == fp) & (df["start_line"] == sl)
                     & (df["end_line"] == el)]
            kinds = sub.get("symbol_type", sub.get("source"))
            print(f"\n  EXAMPLE {fp} [{sl}-{el}] x{cnt}:")
            for _, r in sub.head(4).iterrows():
                t = str(r["text"])[:70].replace("\n", " ")
                print(f"    idx={r.get('chunk_index')} hash={str(r.get('chunk_hash'))[:8]} "
                      f"len={len(str(r['text']))} :: {t}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
