# Write Tools + LSP Integration — Architecture & Implementation Plan

> **Date:** 2026-07-11  
> **Status:** Draft / Research  
> **Version:** v3.0 roadmap  
> **Competitors analyzed:** Serena (LSP-client inside MCP), Qartez (modification guard + rename/move)

---

## 1. Motivation

MSCodeBase — read-only MCP server. Agent can **search** and **understand** code, but cannot **change** it.
To become a full code editing assistant, we need:

- **Write tools** — rename, move, safe-delete, insert, replace
- **Safety** — modification guard (what Qartez calls "impact validation")
- **LSP integration** (optional) — higher-quality rename/refactor via language server

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────┐
│                   MCP Server                        │
│  ┌──────────────────────────────────────────────┐  │
│  │              Write Tools Layer                │  │
│  │  rename_symbol / move_symbol / safe_delete   │  │
│  │  ┌────────────────────────────────────────┐  │  │
│  │  │      @modification_guard decorator      │  │  │
│  │  │  - PageRank check (get_repo_rank)       │  │  │
│  │  │  - Blast radius check (impact_analysis) │  │  │
│  │  │  - Ack system (ack_impact)              │  │  │
│  │  └────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────┘  │
│                           │                         │
│  ┌──────────────────────────────────────────────┐  │
│  │              Core Layer                       │  │
│  │  ┌──────────────┐  ┌──────────────────────┐  │  │
│  │  │ SymbolIndex  │  │   LspClient (opt)     │  │  │
│  │  │ - definitions│  │  - pyright/stdin     │  │  │
│  │  │ - references │  │  - rename/references │  │  │
│  │  │ - rename()   │  │  - Fallback → AST    │  │  │
│  │  └──────────────┘  └──────────────────────┘  │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

### Key design decisions

| Decision | Rationale |
|----------|-----------|
| **Start without LSP** | SymbolIndex + tree-sitter AST already cover 80% of rename/move. LSP is optional amplifier. |
| **Preview/Apply by default** | All destructive tools have `apply=False` (preview mode). Explicit opt-in to apply. |
| **Modification guard as decorator** | Separates safety from business logic. Easy to reuse across tools. |
| **Ack system with TTL** | After `impact` analysis, write is allowed for 600s (same as Qartez). |
| **LSP as subprocess** | pyright-langserver via stdin/stdout (like Serena's `StdioLanguageServer`). |
| **LSP fallback chain** | LSP → AST → SymbolIndex. Graceful degradation. |

---

## 3. Modification Guard (`src/core/modification_guard.py`)

### 3.1 API

```python
@modification_guard(
    pagerank_min=0.05,      # порог PageRank
    blast_min=10,           # порог blast radius
    ack_ttl=600,            # TTL ack в секундах
)
async def rename_symbol(self, ...):
    ...
```

### 3.2 Logic

```
1. Получить PageRank файла через get_repo_rank(file_path)
2. Получить blast radius через impact_analysis(symbol)
3. Если оба порога превышены → DENY(403, "file is load-bearing")
4. Если есть актуальный ack (impact вызван <600s назад) → ALLOW
5. Иначе → ALLOW (негорячие файлы пропускаем)
```

### 3.3 Ack storage

```python
# In-memory dict {file_path: timestamp}
_ack_registry: Dict[str, float] = {}
```

Persistent? No — MCP process lives as long as Zed session. Sufficient.

---

## 4. Write Tools (`src/mcp/tools/write_tools.py`)

### 4.1 Tool: `rename_symbol`

```
rename_symbol(old_name, new_name, file_path="", apply=False, allow_collision=False)

Preview mode (default):
→ {"status": "preview", "changes": [
    {"file": "src/a.py", "line": 42, "old": "old_func", "new": "new_func"},
    {"file": "src/b.py", "line": 15, "old": "old_func", "new": "new_func"},
  ]}

Apply mode:
→ {"status": "applied", "changes": 3, "files": ["src/a.py", "src/b.py"]}
```

**Implementation:**
1. `SymbolIndex.find_all_references(old_name)` — cross-file refs
2. Collision check: `allow_collision=False` → error if `new_name` exists in target scope
3. Preview: return list of changes
4. Apply: file-by-file via `edit_file` on disk
5. Update SymbolIndex in-memory: `rename_symbol(old, new)`

### 4.2 Tool: `move_symbol`

```
move_symbol(symbol, to_file, apply=False)
```

**Implementation:**
1. Find definition + all references via SymbolIndex
2. Compute new import path
3. Preview: {old_file→new_file, import changes}
4. Apply: move definition + update all imports

### 4.3 Tool: `safe_delete`

```
safe_delete(symbol, force=False, apply=False)
```

**Implementation:**
1. Find all references to symbol
2. If `force=False` and references exist (excluding definition) → Deny
3. Preview: which files reference it
4. Apply: remove definition + optionally remove reference lines

### 4.4 Tool: `replace_symbol`

```
replace_symbol(symbol, new_code, file_path="", apply=False)
```

Replace a symbol's body (function/class) at its definition site.

### 4.5 Tool: `insert_before_symbol` / `insert_after_symbol`

```
insert_before_symbol(anchor_symbol, new_code, file_path="", apply=False)
insert_after_symbol(anchor_symbol, new_code, file_path="", apply=False)
```

Anchor-based insertion. Uses SymbolIndex to find line number.

---

## 5. LspClient (`src/core/lsp_client.py`)

### 5.1 Architecture

```python
class LspClient:
    """Thin LSP client for pyright/typescript-language-server.

    Starts language server as subprocess, communicates via stdin/stdout
    using JSON-RPC 2.0 protocol. Optional — falls back to AST/SymbolIndex.
    """

    def __init__(self, project_root: Path): ...

    async def start(self, language: str = "python"):
        # Spawn: pyright-langserver --stdio
        pass

    async def stop(self):
        # shutdown/exit notification
        pass

    async def open_file(self, path: str):
        # textDocument/didOpen
        pass

    async def close_file(self, path: str):
        # textDocument/didClose
        pass

    async def find_definition(self, path: str, line: int, col: int):
        # textDocument/definition
        pass

    async def find_references(self, path: str, line: int, col: int):
        # textDocument/references
        pass

    async def rename_symbol(self, path: str, line: int, col: int, new_name: str):
        # textDocument/rename
        pass

    async def document_symbols(self, path: str):
        # textDocument/documentSymbol
        pass
```

### 5.2 LSP → JSON-RPC protocol

Serena's approach (pattern we follow):
```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
← {"jsonrpc":"2.0","id":1,"result":{"capabilities":{...}}}
→ {"jsonrpc":"2.0","method":"initialized","params":{}}
→ {"jsonrpc":"2.0","id":2,"method":"textDocument/didOpen","params":{...}}
→ {"jsonrpc":"2.0","id":3,"method":"textDocument/definition","params":{...}}
← {"jsonrpc":"2.0","id":3,"result":[...]}
```

### 5.3 Activation policy

```
┌──────────┐     LSP subprocess starts?     ┌────────────┐
│ On first │ ─────────────────────────────> │ LSP mode   │
│ write    │     No (server not found)      │ (preferred)│
│ request  │     └────────────────────────> │ AST mode   │
└──────────┘                                │ (fallback) │
                                            └────────────┘
```

- Lazy start: LSP starts on first write tool call, not at MCP init
- Timeout: 10s to start, otherwise fallback to AST
- Per-language: pyright for Python, typescript-language-server for TS

---

## 6. SymbolIndex Extensions

### 6.1 New methods

```python
class SymbolIndex:
    def find_all_references(self, symbol_name: str, kind: str = "") -> List[SymbolRef]:
        """Cross-file reference search. Full-text fallback if not indexed."""
        pass

    def rename_symbol(self, old_name: str, new_name: str) -> int:
        """Update in-memory index after rename."""
        pass

    def get_symbol_count(self) -> int:
        """Total unique symbols (already exists)."""
        return len(self._definitions)
```

### 6.2 Disambiguation

A symbol can exist in multiple files (e.g., `__init__`). Disambiguate by:
- `file_path` if provided
- `kind` (function vs class vs method)
- Line range if provided

---

## 7. Integration with MCP Tools

### 7.1 Registration pattern

```python
# src/mcp/tools/__init__.py
from src.mcp.tools.write_tools import (
    RenameSymbolTool,
    MoveSymbolTool,
    SafeDeleteTool,
    ReplaceSymbolTool,
    InsertSymbolTool,
    AckImpactTool,
)

WRITE_TOOLS = [
    RenameSymbolTool,     # rename_symbol
    MoveSymbolTool,       # move_symbol
    SafeDeleteTool,       # safe_delete
    ReplaceSymbolTool,    # replace_symbol
    InsertSymbolTool,     # insert_before/after_symbol
    AckImpactTool,        # ack_impact (clear modification guard)
]
```

### 7.2 Error boundary

All write tools use `@error_boundary("tool_name", timeout_ms=30000)` for consistent error handling.

### 7.3 Notification

After successful apply → `notify_change()` for reindex.

---

## 8. Comparison with Qartez

| Feature | Qartez (Rust) | MSCodeBase (Python) |
|---------|--------------|-------------------|
| Modification guard | PageRank + blast radius | Same logic |
| Guard implementation | Struct + trait | Decorator |
| Ack TTL | 600s | 600s |
| Rename | `qartez_rename` | `rename_symbol` |
| Move | `qartez_move` | `move_symbol` |
| Safe delete | `qartez_safe_delete` | `safe_delete` |
| Replace | `qartez_replace_symbol` | `replace_symbol` |
| Insert | `qartez_insert_before/after` | `insert_before/after_symbol` |
| Preview/Apply | `apply: bool = false` | `apply: bool = false` |
| Impact analysis | `qartez_impact` | `impact_analysis` (existing MCP tool) |
| LSP integration | None | Optional (LspClient) |
| Search | External | Built-in (search_code) |

## 9. Comparison with Serena

| Feature | Serena | MSCodeBase |
|---------|--------|------------|
| LSP client | `SolidLanguageServer` | `LspClient` (minimal) |
| LSP backend | pyright/typescript | Same |
| Communication | stdin/stdout LSP | Same |
| File size | 158KB (ls.py) | ~500 lines |
| Dependencies | sensai, pathspec, etc. | None (stdlib + httpx) |
| Write tools | None (read-only) | Planned (6 tools) |
| Search | External | Built-in |

---

## 10. Implementation Order

```
Phase 1 (now)
├── src/core/modification_guard.py  ← декоратор + ack registry
├── src/mcp/tools/write_tools.py    ← rename_symbol + ack_impact
└── SymbolIndex extensions          ← find_all_references, rename_symbol

Phase 2 (next)
├── src/core/lsp_client.py          ← thin LSP client
├── move_symbol + safe_delete
└── Integration tests

Phase 3 (future)
├── replace_symbol
├── insert_before/after_symbol
└── Multi-file refactoring (move file + update imports)
```

---

## 11. Risk Assessment

| Risk | Mitigation |
|------|------------|
| Edit conflicts with Zed | notify_change after write → reindex |
| encoding issues | Windows: utf-8-sig for safety |
| LSP subprocess crash | Auto-restart + fallback to AST |
| Large rename (100+ files) | Streaming changes, progress reporting |
| Permission denied | Try-except with clear error message |
| Git dirty state | Warn user before destructive write |

---

*Part of MSCodeBase Intelligence v3.0 roadmap*
*Based on Serena (MIT) and Qartez patterns — reimplemented from scratch in Python*
