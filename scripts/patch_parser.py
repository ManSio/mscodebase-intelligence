import re

with open(r"D:\Project\MSCodeBase\src\core\indexing\parser.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find and replace parse_file method
old = '''    def parse_file(self, file_path: Path) -> tuple:
        """Главный метод парсинга файла. Возвращает (chunks, symbols)."""
        ext = file_path.suffix.lower()
        if ext not in self.parsers:
            return [], []

        # Сначала пробуем парсить через Tree-sitter
        try:
            chunks, symbols = self._parse_with_tree_sitter(file_path, ext)
            if not chunks:
                chunks, symbols = self._fallback_line_chunking(file_path)
        except Exception as e:
            logger.warning(
                f"Ошибка Tree-sitter для {file_path}, используем fallback: {e}"
            )
            chunks, symbols = self._fallback_line_chunking(file_path)

        return chunks, symbols'''

new = '''    def parse_file(self, file_path: Path) -> tuple:
        """Главный метод парсинга файла. Возвращает (chunks, symbols).

        Symbols теперь извлекаются через tags.scm (definition.* captures),
        chunks через _walk_node (calls/imports/assignments + метаданные).
        """
        ext = file_path.suffix.lower()
        if ext not in self.parsers:
            return [], []

        # 1. Определения через tags.scm (быстрее, полнее)
        symbols = self.extract_definitions_scm(file_path)
        if not symbols:
            # Fallback: старый walk для определений (для языков без tags.scm)
            _, symbols = self._parse_with_tree_sitter(file_path, ext)

        # 2. Чанки + calls/imports/assignments через walk
        chunks, _, _ = self._parse_with_tree_sitter(file_path, ext)
        # symbols уже есть, не перезаписываем

        return chunks, symbols'''

if old in content:
    content = content.replace(old, new)
    with open(r"D:\Project\MSCodeBase\src\core\indexing\parser.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: parse_file replaced")
else:
    print("FAIL: old text not found")
    # Try to find it with regex
    import re
    match = re.search(r'def parse_file\(self.*?return chunks, symbols', content, re.DOTALL)
    if match:
        print("Found with regex, length:", len(match.group(0)))
        print("---")
        print(match.group(0)[:500])
        print("---")