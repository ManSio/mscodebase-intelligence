# MSCodeBase Intelligence

## ✨ Key Features

MSCodeBase Intelligence is a **enterprise-grade code search and analysis extension** for Zed editor that provides:

### 🔍 **Advanced Search Capabilities**
- **Hybrid Search**: Combines vector embeddings with lexical search for optimal results
- **Semantic Chunking**: AST-based intelligent code segmentation preserving structure
- **Merkle Tree Change Detection**: O(1) file system monitoring with atomic operations
- **Zero-Knowledge Security**: Path hashing and local-only storage

### 🛡️ **Production Features**
- **Windows File Locking Protection**: Retry logic for Zed save operations
- **Path Normalization**: Cross-platform compatibility (Windows/macOS/Linux)
- **Comprehensive Logging**: Structured debugging with clear prefixes
- **Enterprise Security**: No code exposure to external services

### 🚀 **Performance Optimizations**
- **O(1) Change Detection**: Merkle Tree for instant file system updates
- **Memory Efficient**: Hash-based storage instead of full file copies
- **Scalable Architecture**: Supports repositories with 50k+ files
- **Real-time Indexing**: Instant file processing and search

## 📋 Quick Start

### Prerequisites

- **Zed Editor** (latest version)
- **Python 3.8+** with development packages

### Installation

#### Windows
```powershell
# Clone the repository
git clone https://github.com/ManSio/mscodebase-intelligence.git

# Navigate to project directory
cd MSCodeBase

# Install Python dependencies
pip install -r requirements.txt

# The extension will automatically detect and install
```

#### macOS / Linux
```bash
# Clone the repository
git clone https://github.com/ManSio/mscodebase-intelligence.git

# Navigate to project directory
cd MSCodeBase

# Install Python dependencies
pip install -r requirements.txt

# The extension will automatically detect and install
```

### Usage

1. **Open your project** in Zed editor
2. **Use `@mscodebase-intelligence`** to search your codebase
3. **Get instant results** with semantic and lexical search
4. **Monitor changes** with real-time file watching

## 🏗️ Architecture

### System Components

#### 1. **File Watcher** (`src/core/watcher.py`)
- **Purpose**: Monitors file system changes with atomic operations
- **Features**:
  - Windows path normalization (`\` → `/`)
  - File locking protection with retry logic
  - Merkle Tree integration for O(1) detection
  - Structured logging with `[WATCHER]` prefixes

#### 2. **File Guard** (`src/core/file_guard.py`)
- **Purpose**: Security filtering and file validation
- **Features**:
  - Windows file locking protection (3 retries, 50ms delay)
  - .gitignore pattern matching
  - File size and content validation
  - Structured logging with `[FILEGUARD]` prefixes

#### 3. **Gitignore Parser** (`src/core/gitignore_parser.py`)
- **Purpose**: Advanced .gitignore pattern matching
- **Features**:
  - POSIX path normalization
  - Comprehensive pattern matching
  - Error handling and logging
  - Structured logging with `[GITIGNORE]` prefixes

#### 4. **Merkle Tree** (`src/core/integrity.py`)
- **Purpose**: O(1) change detection and integrity verification
- **Features**:
  - Efficient file system monitoring
  - Atomic root hash comparison
  - Hierarchical change tracking
  - Structured logging with `[INTEGRITY]` prefixes

#### 5. **Semantic Chunker** (`src/core/chunker.py`)
- **Purpose**: AST-based intelligent code segmentation
- **Features**:
  - Tree-sitter integration for multiple languages
  - Semantic chunk boundaries (functions, classes, methods)
  - Rich metadata preservation
  - Fallback to line-based chunking

#### 6. **Hybrid Search Engine** (`src/core/search.py`)
- **Purpose**: Combined vector + lexical search with RRF fusion
- **Features**:
  - Reciprocal Rank Fusion (RRF) for optimal results
  - Vector search for semantic relevance
  - Lexical search for exact matches
  - Advanced result enhancement

#### 7. **Indexer** (`src/core/indexer.py`)
- **Purpose**: Main indexing and search orchestration
- **Features**:
  - Integration with all core components
  - Vector database management
  - Search result caching
  - Performance optimization

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    MSCodeBase Architecture                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   File Watcher  │    │    File Guard   │    │ Gitignore Parser│  │
│  │ (watcher.py)    │    │ (file_guard.py) │    │ (gitignore_parser)│  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
│         │                       │                       │         │
│         └───────────────────────┼───────────────────────┘         │
│                               │                               │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │  Merkle Tree    │    │ Semantic Chunker│    │   Hybrid Search │  │
│  │ (integrity.py) │    │  (chunker.py)   │    │   (search.py)   │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
│                               │                               │
│  ┌─────────────────┐    ┌─────────────────┐                   │
│  │   Indexer       │    │   Other Modules │                   │
│  │ (indexer.py)    │    │   (parser, etc) │                   │
│  └─────────────────┘    └─────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

## ⚙️ Configuration

### Environment Variables

```bash
# File watcher polling interval (seconds)
POLL_INTERVAL=10

# Maximum file size for indexing (bytes)
MAX_FILE_SIZE=1048576

# Number of retries for file locking
MAX_RETRIES=3

# Retry delay in milliseconds
RETRY_DELAY=50
```

### Supported File Extensions

- **Programming Languages**: `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.rs`, `.go`, `.java`, `.cpp`, `.c`, `.h`, `.hpp`, `.php`, `.rb`, `.swift`, `.kt`, `.scala`, `.r`, `.m`, `.mm`
- **Web Technologies**: `.html`, `.css`, `.scss`, `.sass`, `.less`, `.xml`, `.json`, `.yaml`, `.yml`, `.toml`
- **Documentation**: `.md`, `.rst`, `.txt`
- **Configuration**: `.env`, `.config`, `.ini`, `.cfg`

### File Size Limits

- **Maximum file size**: 1 MB (1,048,576 bytes)
- **Maximum chunk size**: 500 characters (semantic) / 1000 characters (fallback)
- **Overlap**: 200 characters between chunks

## 🛠️ Development

### Environment Setup

```bash
# Clone the repository
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd MSCodeBase

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Install development dependencies (if any)
pip install -r requirements-dev.txt
```

### Running MCP Server

```bash
# Start the MCP server
cd MSCodeBase
python -m src.core.indexer
```

### Testing

```bash
# Run unit tests
pytest tests/ -v

# Run integration tests
pytest tests/integration/ -v

# Run all tests
pytest -v
```

### Building Standalone

```bash
# Build standalone executable
pyinstaller --onefile --windowed src/core/indexer.py
```

## 📁 Project Structure

```
MSCodeBase/
├── src/
│   └── core/
│       ├── __init__.py              # Package initialization
│       ├── chunker.py              # Semantic AST chunking
│       ├── context_engine.py        # Context management
│       ├── embedder.py              # Vector embedding
│       ├── file_guard.py            # File security filtering
│       ├── gitignore_parser.py      # .gitignore pattern matching
│       ├── integrity.py             # Merkle Tree implementation
│       ├── indexer.py               # Main indexing engine
│       ├── model_server.py           # Model serving
│       ├── parser.py                 # Code parsing
│       ├── remote_embedder.py       # Remote embedding
│       ├── reranker.py              # Result reranking
│       ├── search.py                 # Hybrid search engine
│       ├── searcher.py               # Search orchestration
│       ├── status_reporter.py        # System status reporting
│       ├── symbol_index.py           # Symbol indexing
│       └── watcher.py                # File system watching
├── tests/                          # Test suite
│   ├── test_embedder.py
│   ├── test_integration.py
│   ├── test_mutation_core.py
│   ├── test_parser.py
│   └── test_searcher.py
├── pyproject.toml                  # Project configuration
├── requirements.txt                 # Dependencies
├── setup.cfg                        # Setup configuration
├── README.md                        # This documentation
├── ARCHITECTURE.md                  # Technical specifications
├── CHANGELOG.md                     # Version history
├── LICENSE                          # License information
├── SECURITY.md                      # Security information
└── TESTING.md                       # Testing guidelines
```

## 📋 System Requirements

### Minimum Requirements

- **Operating System**: Windows 10/11, macOS 10.15+, Linux
- **Processor**: Modern multi-core processor (Intel i5/Ryzen 5 equivalent or better)
- **Memory**: 8 GB RAM (16 GB recommended for large repositories)
- **Storage**: 1 GB free space for extension + repository storage

### Recommended Requirements

- **Processor**: 8-core processor or better
- **Memory**: 16 GB RAM or more
- **Storage**: SSD with at least 100 GB free space
- **Network**: High-speed internet connection (for initial setup)

### Tool Permissions

The extension requires the following permissions:

- **File System Access**: Read/write access to project directories
- **Network Access**: For initial setup and updates
- **Process Access**: For file monitoring and indexing

## 🐛 Known Limitations

1. **Large Binary Files**: Files larger than 1 MB are skipped during indexing
2. **Complex Dependencies**: Some language parsers may not support all syntax variations
3. **Performance**: Initial indexing may take time for very large repositories
4. **Platform Specific**: Some Windows-specific features may not work on other platforms

## 🤖 AI Assistant Prompt

Для корректного использования расширения AI-ассистентом см. файл `AI_PROMPT.md`.

Кратко:
- Используйте `@mscodebase-intelligence` для поиска кода
- При первом открытии проекта запустите индексацию через `index_project_dir`
- Комбинируйте `search_code`, `get_context` и `get_symbol_info` для глубокого анализа

## 📄 License

MSCodeBase Intelligence is licensed under the MIT License. See the LICENSE file for more information.

---

*For support and issues, please visit the project repository.*
*Last updated: $(date -Iseconds)*