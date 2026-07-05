# FAQ — MSCodeBase Intelligence

![MSCodeBase Logo](../logo/logo.svg)

> Frequently Asked Questions. Based on real development and operations experience.

---

## 📦 Installation & Startup

### MCP server not responding after installation

**Cause:** Zed wasn't restarted. `window: reload` is not enough.
**Solution:** File → Quit → reopen the project.

Logs: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### Nothing changed after `python install.py`

**Cause:** The installer copied files to the extension, but MCP server is already running with the old code.
**Solution:** File → Quit → reopen the project. Only a full restart restarts MCP.

### Index is empty (0 chunks)

**Solution:** Run `intel_trigger_reindex()` in Agent Panel. Wait 1-5 minutes.
Track progress via `intel_get_job_status(<job_id>)`.

---

## 🔍 Search & Tools

### `search_code` returns 0 results

**Causes:**
- Empty index → see above
- LM Studio not running → `intel_get_runtime_status()` shows "offline"
- Wrong project → check `get_index_status()` output

### `get_index_status()` shows wrong project

**Cause:** Project resolution via SQLite — if multiple projects are open in Zed,
it may pick the wrong one. Especially on Windows where `ZED_WORKTREE_ROOT` is unset.

**Solution:** Close all Zed windows, open only the needed project.
Details: `docs/investigations/2026-07-05-active-workspace-resolution.md`

### Tool returns raw JSON

**If from an older version:** Fixed. After commit `05de324` (2026-07-05)
all 43 tools output readable Markdown.
**Solution:** Run `python install.py` and restart Zed.

---

## 🪟 Windows

### LSP won't start (mscodebase-lsp)

**Cause:** Zed on Windows cannot register custom LSP names.
Requires a Rust/WASM adapter. `settings.json` is powerless.
**Status:** WONTFIX. MCP server works fully without LSP.
Details: `docs/investigations/2026-07-05-lsp-zed-1.9.0.md`

### Zed shows "Restricted Mode"

**Solution:** Click "Trust and Continue". Check "Trust all projects in..."
Otherwise LSP won't start, MCP won't see the project.

### MCP doesn't auto-restart

**Solution:** File → Quit → reopen the project only.
Auto-restart is not supported by Zed on Windows.

### Project resolves as "ext_root" (self-indexing)

**Cause:** `resolve_project_root()` couldn't find the project via SQLite.
**Solution:** Make sure the project is open in Zed. Check `LocalAPPDATA/Zed/db/0-stable/db.sqlite`.
If empty — Restricted Mode may be blocking it.

---

## ⚡ Performance

### Slow search (>10s)

**Causes:**
- LM Studio on a weak machine (check `intel_get_telemetry()` → ping)
- Index not optimized (run `intel_trigger_reindex()`)
- `limit` too high in `search_code` (recommended 6-10)

### LLM Ping > 2000ms

**Solution:** Check LM Studio. Make sure an embedding model
(e.g. `BAAI/bge-m3`) is loaded. Don't use LLM models via LM Studio
for embeddings — they're slow.

### Memory > 500 MB

**Normal:** LanceDB uses mmap files. Windows keeps them in memory.
**Solution:** Restart MCP to free memory (File → Quit).

---

## 🐛 Bugs & Errors

### `ModuleNotFoundError: No module named 'src'`

**Cause:** PYTHONPATH doesn't point to the extension directory.
**Solution:** Run `python install.py` — it sets the correct PYTHONPATH.

### `ToolError: Refusing to index self`

**Cause:** Self-indexing guard — MCP protects itself from indexing its own sources.
**Solution:** Open a different project in Zed (not the extension).

### MCP hangs after a batch of notify_change

**Was in older versions (before 2026-07-05):** Deadlock in DebounceBatch.
**Fixed.** If still happening — check version (`debug_runtime_passport` → BUILD_ID).
Solution: File → Quit.

---

## 🔗 Related Documents

| Document | Description |
|----------|-------------|
| `docs/INSTALL.md` | User installation guide |
| `docs/architecture.md` | Project architecture (10 layers) |
| `ZED_WINDOWS_QUIRKS.md` | Windows specifics |
| `docs/HANDFOFF_TO_AI_AGENT.md` | Development experience, architecture decisions |
