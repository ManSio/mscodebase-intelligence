# F4b — кандидаты свежего held-out списка (НЕ заморожено)

Источник: 8 реальных симптомов, извлечённых **контекстно-чистым субагентом** (не читал каталог и
использованный список) из `AGENT_DIARY.md` / `KNOWN_ISSUES.md` / `ISSUE.md` / `EXPERIMENTS_LOG.md`.
Формулировки — «как пришло» (симптом, а не диагноз). Перед заморозкой: пройти `frozen_overlap_check.py`
→ `OVERLAP: PASS`; затем добавить 6 контролей (3 must-hit, 3 must-NONE); sha256 ДО прогона.

1. The index snapshot showed the same files counted twice — the row count grew from about 9,991 to 19,653 even though no files had been added.
2. A full reindex stalled at 52% and sat in "running" forever, with every process showing 0% CPU.
3. The first `search_code` call after a period of inactivity timed out and never returned results — the server on `:8080` was no longer answering.
4. While a full reindex was running, every MCP call in the session froze for roughly 7.5 minutes until the reindex finished.
5. The pilot answers file came back as 120/120 `Error 500`, and a live smoke run printed `# FUNC NOT FOUND` for every class method.
6. A reindex that had been running for about nine hours crashed and lost all of its work, with progress reset back to zero.
7. `auto_update_docs(action="verify")` crashed with `IndexError: string index out of range`.
8. During the parsing phase of a reindex the machine showed only ~5% CPU and ~3 MB/s of disk I/O while graph building crawled.

## SOURCES (verbatim)
1 -> KNOWN_ISSUES.md: "file_path distinct raw=1378 vs normalized=710 (path-duplication 668)"
2 -> KNOWN_ISSUES.md: "live job 090149f1 (stuck 52% \"running\", 0 CPU)"
3 -> AGENT_DIARY.md: "RemoteEmbedder его не поднимал → :8080 мёртв → WinError 10061 → поштучные ретраи → search_code timeout"
4 -> AGENT_DIARY.md: "заморозка ВСЕХ MCP-вызовов"
5 -> AGENT_DIARY.md: "e17_pilot_answers.json = 120/120 Error 500; live smoke gave # FUNC NOT FOUND"
6 -> AGENT_DIARY.md: "run() копил все эмбеддинги и писал одним bulk_write в конце — краш на 330K чанков (~9ч) терял всё"
7 -> AGENT_DIARY.md: "auto_update_docs(action=\"verify\") падал IndexError: string index out of range"
8 -> EXPERIMENTS_LOG.md: "root cause «CPU 5% + диск ~3 МБ/с» на фазе parsing"
