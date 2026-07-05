# Installing MSCodebase Intelligence for Zed IDE

[🇬🇧 English](INSTALL.md) • [🇷🇺 Русский](../ru/INSTALL.md) • [🇨🇳 中文](../zh/INSTALL.md)

![MSCodeBase Banner](../../logo/baner.svg)

> **MSCodebase Intelligence** — MCP server for semantic code search in Zed IDE.
> Development hosted at [github.com/ManSio/mscodebase-intelligence](https://github.com/ManSio/mscodebase-intelligence)
> Runs fully locally after installation.

---

## 🔧 System Requirements

| Component | Requirement |
|-----------|-----------|
| **OS** | Windows 10+ (primary support), macOS 12+, Linux |
| **Python** | 3.10+ (3.11+ recommended) |
| **RAM** | 4 GB (8+ GB recommended) |
| **Disk** | 500 MB (with model — up to 2 GB) |
| **Zed IDE** | latest version |
| **LM Studio** (optional) | for vector search via embeddings |

---

## 📥 Quick Installation

### Step 1: Install the Extension

Open a terminal in the **root of your project** (where `install.py` is located) and run:

```bash
python install.py
```

> **Linux/macOS:** You can also use `./install.sh` for a guided install.
> **Windows:** You can also use `install.bat` (double-click or run in cmd).

The installer will:
1. ✅ Check Python and compatibility
2. ✅ Create a virtual environment and install dependencies
3. ✅ Configure the MCP server in Zed's `settings.json`
4. ✅ Copy source files into the installed extension
5. ✅ Create `uninstall.bat`

> **Important:** The installer copies files from the current directory into the extension.
> All source changes take effect only after `python install.py`.

### Step 2: Restart Zed

**File → Quit**, then reopen the project.
A simple `window: reload` is **insufficient** — the MCP server must fully restart.

### Step 3: Verification

Open the **Agent Panel** (`Ctrl+Shift+P` → `Agent Panel: Toggle`) and run:

```
get_index_status()
```

You should see:

```
📂 <your-project-root>
🟢 **MSCodeBase** — active
📦 **Chunks:** `1603` | **Files:** `114` | **Symbols:** `134`
🧠 **Embedder:** 🌐 LM Studio
```

If the project is detected incorrectly (showing a different project instead of yours) — close
all Zed windows and open only the desired project.

---

## 🧠 Windows Specifics

On Windows there are **critical specifics** you need to know:

| Issue | Symptom | Solution |
|-------|---------|----------|
| **Restricted Mode** | LSP doesn't start, MCP doesn't see the project | Press "Trust and Continue" when opening the project |
| **CWD = Zed directory** | MCP server starts from the folder where Zed is installed, not from the project | Fixed via SQLite fallback (project is taken from Zed's database, not from CWD) |
| **MCP doesn't restart** | After killing the process, tools don't work | Only a full Zed restart (File → Quit) |
| **Project resolves incorrectly** | Shows gemma_agent instead of MSCodeBase | Close all Zed windows, open only the desired project |

Details: **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)**

### How the project is determined (without LSP)

The MCP server determines the current project in this order:

1. **Explicit `project_root`** from tool arguments
2. **SQLite `active_workspace_id`** (NEW, primary!) — reads `scoped_kv_store`
   in Zed's database, which stores `active_workspace_id` — the ONLY mechanism
   working on Windows. Instantly switches when changing projects.
3. **SQLite `workspaces`** (old fallback) — selects the most recent project
   from the `workspaces` table if `active_workspace_id` is not found.
4. **LSP Bridge** (JSON file from LSP — **doesn't work on Windows**, LSP doesn't start)
5. **`PROJECT_PATH`** from environment
6. **CWD** — **always rejected** by self-indexing guard
7. **ext_root** (extension directory) — fallback

> On Windows, steps 1, 4-5 are typically unavailable, so the project is determined
> via SQLite `active_workspace_id` (step 2). This mechanism automatically
> switches the project when the active window changes in Zed. If the determination
> is still incorrect — close extra Zed windows.

---

## 🚀 Optional: LM Studio

LM Studio provides higher quality search through vector embeddings.

1. Install [LM Studio](https://lmstudio.ai/)
2. Download an embedding model (e.g., `BAAI/bge-m3`)
3. Start the local server on port `1234`
4. The MCP server will connect automatically

Verification:
```
intel_get_runtime_status()
```
The response should include `"embedding_provider": "lm_studio"` and `"lm_studio_at_1234": "online"`.

---

## 📄 Uninstallation

```cmd
:: Run the uninstaller
uninstall.bat
```

Or manually:
1. Remove the `mscodebase-intelligence` section from `%APPDATA%\Zed\settings.json`
2. Delete the extension folder:
   ```
   %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
   ```
3. Delete `.codebase_indices` from your project root (if present)

---

## ❗ Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| **Tools not responding** | MCP server not running | File → Quit → reopen the project. Logs: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| **Wrong project** | SQLite selected another workspace | Close all Zed windows, open only the desired project |
| **0 chunks** | Index is empty | `intel_trigger_reindex()` — wait 1-5 minutes |
| **LM Studio offline** | Server not running | Start LM Studio, check port 1234 |
| **settings.json warning** | Outdated keys (`lsp`, `mscodebase`) | Run `python install.py` — it will clean up |
| **ModuleNotFoundError** | PYTHONPATH doesn't point to the extension | `python install.py` — fixes automatically |

**Where data is stored:**
- **Index (LanceDB):** `<project>/.codebase_indices/lancedb_v2/` — vector DB with code chunks
- **Logs:** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`
- **Project Memory (ADR, known_issues):** `<project>/.codebase_indices/intelligence/`

---

## 👨‍💻 Development (contributors)

```bash
# Clone
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Install in Zed (after changes)
python install.py
```

Details: **[CONTRIBUTING.md](CONTRIBUTING.md)**

---

## 🔗 Related Documents

| Document | Description |
|----------|-------------|
| [README.md](README.md) | Main documentation, map of all docs, tool list |
| [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) | **Windows specifics:** Restricted Mode, CWD, MCP restart |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Project architecture, DI, layers |
| [TELEMETRY.md](TELEMETRY.md) | Metrics, ETA, data collection |
| [LSP_WONTFIX.md](investigations/LSP_WONTFIX.md) | Why LSP doesn't work on Windows |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development, tests, PRs |
