"""
Semantic code chunking using AST (Abstract Syntax Tree) parsing.
Provides intelligent code segmentation for better RAG performance.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SemanticChunker:
    """Semantic code chunker using AST parsing for intelligent segmentation."""

    def __init__(self):
        self.parsers = {}
        self._setup_parsers()

    def _setup_parsers(self):
        """Setup language parsers for different file extensions."""
        try:
            import tree_sitter
            from tree_sitter import Language

            # Python parser
            self.parsers[".py"] = {
                "language": self._load_language("tree_sitter_python", "python"),
                "chunk_types": [
                    "function_definition",
                    "class_definition",
                    "method_definition",
                    "async_function_definition",
                    "lambda",
                    "import_statement",
                    "import_from_statement",
                ],
            }

            # JavaScript/TypeScript parsers
            self.parsers[".js"] = {
                "language": self._load_language("tree_sitter_javascript", "javascript"),
                "chunk_types": [
                    "function_declaration",
                    "class_declaration",
                    "method_definition",
                    "arrow_function",
                    "import_statement",
                    "export_statement",
                ],
            }

            self.parsers[".ts"] = {
                "language": self._load_language("tree_sitter_typescript", "typescript"),
                "chunk_types": [
                    "function_declaration",
                    "class_declaration",
                    "method_definition",
                    "interface_declaration",
                    "type_alias_declaration",
                    "import_statement",
                    "export_statement",
                ],
            }

            # Rust parser
            self.parsers[".rs"] = {
                "language": self._load_language("tree_sitter_rust", "rust"),
                "chunk_types": [
                    "function_item",
                    "impl_item",
                    "struct_item",
                    "enum_item",
                    "trait_item",
                    "use_declaration",
                ],
            }

            # Go parser
            self.parsers[".go"] = {
                "language": self._load_language("tree_sitter_go", "go"),
                "chunk_types": [
                    "function_declaration",
                    "method_declaration",
                    "type_declaration",
                    "import_declaration",
                    "const_declaration",
                ],
            }

        except ImportError as e:
            logger.warning(f"⚠️ Tree-sitter parsers not available: {e}")
            self.parsers = {}

    def _load_language(self, module_name: str, language_name: str):
        """Load Tree-sitter language parser."""
        try:
            import importlib

            module = importlib.import_module(module_name)
            return Language(module, language_name)
        except ImportError:
            logger.warning(f"⚠️ Could not load {language_name} parser")
            return None

    def chunk_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Chunk file into semantic units.

        Args:
            file_path: Path to the file to chunk

        Returns:
            List of chunks with metadata
        """
        extension = file_path.suffix.lower()

        if extension not in self.parsers:
            return self._fallback_chunking(file_path)

        parser_config = self.parsers[extension]
        language = parser_config["language"]
        chunk_types = parser_config["chunk_types"]

        if language is None:
            return self._fallback_chunking(file_path)

        try:
            # Read file content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse with Tree-sitter
            parser = tree_sitter.Parser(language)
            tree = parser.parse(content)

            # Extract chunks
            chunks = self._extract_chunks(tree, content, chunk_types)

            logger.debug(f"📝 Chunked {file_path}: {len(chunks)} semantic chunks")
            return chunks

        except Exception as e:
            logger.warning(f"⚠️ Failed to parse {file_path}: {e}")
            return self._fallback_chunking(file_path)

    def _extract_chunks(
        self, tree: Any, content: str, chunk_types: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract semantic chunks from parsed tree."""
        chunks = []

        for child in tree.children:
            if child.type in chunk_types:
                chunk = self._create_chunk_from_node(child, content)
                if chunk:
                    chunks.append(chunk)

        return chunks

    def _create_chunk_from_node(
        self, node: Any, content: str
    ) -> Optional[Dict[str, Any]]:
        """Create a chunk from a Tree-sitter node."""
        try:
            start_byte = node.start_byte
            end_byte = node.end_byte
            start_point = node.start_point
            end_point = node.end_point

            chunk_content = content[start_byte:end_byte]

            # Extract metadata
            metadata = {
                "type": node.type,
                "name": self._extract_node_name(node),
                "line_range": [start_point[0], end_point[0]],
                "column_range": [start_point[1], end_point[1]],
                "byte_range": [start_byte, end_byte],
                "context": self._extract_context(node, content),
                "dependencies": self._extract_dependencies(node, content),
                "signature": self._extract_signature(node, content),
            }

            return {"content": chunk_content, "metadata": metadata}

        except Exception as e:
            logger.warning(f"⚠️ Failed to create chunk from node: {e}")
            return None

    def _extract_node_name(self, node: Any) -> str:
        """Extract name from node."""
        for child in node.children:
            if child.type in ["identifier", "type_identifier", "field_identifier"]:
                return child.text.decode("utf-8")
        return f"anonymous_{node.type}"

    def _extract_context(self, node: Any, content: str) -> Dict[str, Any]:
        """Extract surrounding context for the node."""
        context = {
            "imports": [],
            "parent_class": None,
            "module_level": True,
            "decorators": [],
        }

        # Find parent class or function
        parent = node.parent
        while parent:
            if parent.type == "class_definition":
                context["parent_class"] = self._extract_node_name(parent)
                context["module_level"] = False
                break
            elif parent.type in ["function_definition", "method_definition"]:
                if parent.type == "method_definition":
                    # Extract class name from grandparent
                    grandparent = parent.parent
                    if grandparent and grandparent.type == "class_definition":
                        context["parent_class"] = self._extract_node_name(grandparent)
                context["module_level"] = False
                break
            parent = parent.parent

        return context

    def _extract_dependencies(self, node: Any, content: str) -> List[str]:
        """Extract dependencies (imports, types, etc.) for the node."""
        dependencies = []

        # Look for imports in the file
        for child in node.parent.children if node.parent else []:
            if child.type in ["import_statement", "import_from_statement"]:
                dependencies.append(child.text.decode("utf-8"))

        return dependencies

    def _extract_signature(self, node: Any, content: str) -> str:
        """Extract function/method signature."""
        if node.type not in [
            "function_definition",
            "method_definition",
            "function_declaration",
        ]:
            return ""

        # Extract parameters
        params = []
        for child in node.children:
            if child.type == "parameters":
                for param in child.children:
                    if param.type == "parameter":
                        params.append(self._extract_node_name(param))

        return f"({', '.join(params)})"

    def _fallback_chunking(self, file_path: Path) -> List[Dict[str, Any]]:
        """Fallback chunking for unsupported file types."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Simple line-based chunking as fallback
            lines = content.split("\n")
            chunks = []

            # Create chunks of approximately 500 characters
            current_chunk = []
            current_length = 0

            for line in lines:
                if current_length + len(line) > 500 and current_chunk:
                    chunks.append(
                        {
                            "content": "\n".join(current_chunk),
                            "metadata": {
                                "type": "text_block",
                                "line_range": [0, len(current_chunk)],
                                "context": {"fallback": True},
                            },
                        }
                    )
                    current_chunk = []
                    current_length = 0

                current_chunk.append(line)
                current_length += len(line)

            if current_chunk:
                chunks.append(
                    {
                        "content": "\n".join(current_chunk),
                        "metadata": {
                            "type": "text_block",
                            "line_range": [0, len(current_chunk)],
                            "context": {"fallback": True},
                        },
                    }
                )

            logger.debug(f"📝 Fallback chunked {file_path}: {len(chunks)} chunks")
            return chunks

        except Exception as e:
            logger.warning(f"⚠️ Fallback chunking failed for {file_path}: {e}")
            return []


class ChunkingPipeline:
    """Main chunking pipeline that coordinates different chunking strategies."""

    def __init__(self):
        self.semantic_chunker = SemanticChunker()

    def chunk_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Chunk file using the best available strategy.

        Args:
            file_path: Path to the file to chunk

        Returns:
            List of chunks with metadata
        """
        # Try semantic chunking first
        if self.semantic_chunker.parsers:
            chunks = self.semantic_chunker.chunk_file(file_path)
            if chunks:
                return chunks

        # Fall back to basic chunking
        return self.semantic_chunker._fallback_chunking(file_path)

    def chunk_content(self, content: str, file_path: Path) -> List[Dict[str, Any]]:
        """Chunk content directly (for already loaded files)."""
        extension = file_path.suffix.lower()

        if extension in self.semantic_chunker.parsers:
            # Try to use semantic chunking with provided content
            try:
                import tree_sitter
                from tree_sitter import Language

                parser_config = self.semantic_chunker.parsers[extension]
                language = parser_config["language"]
                chunk_types = parser_config["chunk_types"]

                if language:
                    parser = tree_sitter.Parser(language)
                    tree = parser.parse(content)
                    return self.semantic_chunker._extract_chunks(
                        tree, content, chunk_types
                    )

            except Exception:
                pass

        # Fallback to basic chunking
        return self.semantic_chunker._fallback_chunking(file_path)
