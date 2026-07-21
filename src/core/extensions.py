"""
Single source of truth for supported file extensions.

Заменяет три разошедшихся списка SUPPORTED_EXTENSIONS:
  - src/core/parser.py      (8  расширений)
  - src/core/file_guard.py  (35 расширений, есть .sql .sh)
  - src/lsp_main.py         (30 расширений, есть .txt)

Union всех трёх + разделение по назначению.
Inspired by Serena's FilenameMatcher (oraios/serena).
"""

from pathlib import Path

__all__ = [
    "is_supported",
    "is_parseable",
]
# ── Языки с семантическим парсингом (tree-sitter) ─────────────────────────
# Используется в parser.py для AST-чанкинга.
PARSE_EXTENSIONS: frozenset[str] = frozenset({
    # Core languages (полный граф: chunking + calls + data flow + imports)
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go",
    ".java", ".cs", ".rb", ".php", ".kt", ".swift",
    ".c", ".cpp", ".cxx", ".hpp", ".scala", ".dart",
    # Shell (calls + imports, без data flow)
    ".sh", ".bash",
    # Context-языки (только AST-парсинг и чанкинг)
    ".sql", ".yaml", ".yml", ".toml", ".html", ".htm", ".css",
    ".hcl", ".tf", ".tfvars",
    # Markdown
    ".md",
})

# ── Все расширения, которые индексируем ───────────────────────────────────
# Union всех трёх оригинальных списков. Используется в file_guard.py и lsp_main.py.
INDEX_EXTENSIONS: frozenset[str] = frozenset({
    # Core languages
    ".py", ".rs", ".go", ".java", ".cs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".r", ".m", ".mm",
    # Web
    ".ts", ".tsx", ".js", ".jsx",
    # C/C++
    ".c", ".cpp", ".h", ".hpp",
    # Styles
    ".css", ".scss", ".sass", ".less",
    # Markup / Data
    ".html", ".xml", ".json", ".yaml", ".yml", ".toml", ".md",
    # Database / Shell
    ".sql", ".sh", ".bash",
    # Text (из lsp_main.py)
    ".txt",
})

# ── Backward-compat alias (drop-in замена для старых мест) ─────────────────
SUPPORTED_EXTENSIONS: frozenset[str] = INDEX_EXTENSIONS


def is_supported(path: str) -> bool:
    """Быстрая проверка по суффиксу. Case-insensitive."""
    suffix = Path(path).suffix.lower()
    return suffix in INDEX_EXTENSIONS


def is_parseable(path: str) -> bool:
    """True если файл поддерживает AST-парсинг через tree-sitter."""
    suffix = Path(path).suffix.lower()
    return suffix in PARSE_EXTENSIONS
