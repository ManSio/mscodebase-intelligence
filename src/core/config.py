"""
MSCodeBase Intelligence - Central Configuration Module

Централизованное управление конфигурацией для всех компонентов системы.
Использует переменные окружения с разумными значениями по умолчанию.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class EmbeddingConfig:
    """Конфигурация для эмбеддингов (LM Studio, Ollama, ONNX)"""
    # LM Studio
    lm_studio_host: str = os.getenv("LM_STUDIO_HOST", "127.0.0.1")
    lm_studio_port: int = int(os.getenv("LM_STUDIO_PORT", "1234"))
    lm_studio_embeddings_url: str = f"http://{lm_studio_host}:{lm_studio_port}/v1/embeddings"
    lm_studio_models_url: str = f"http://{lm_studio_host}:{lm_studio_port}/v1/models"
    lm_studio_chat_url: str = f"http://{lm_studio_host}:{lm_studio_port}/v1/chat/completions"

    # Ollama
    ollama_host: str = os.getenv("OLLAMA_HOST", "127.0.0.1")
    ollama_port: int = int(os.getenv("OLLAMA_PORT", "11434"))
    ollama_tags_url: str = f"http://{ollama_host}:{ollama_port}/api/tags"
    ollama_chat_url: str = f"http://{ollama_host}:{ollama_port}/api/chat"
    ollama_embeddings_url: str = f"http://{ollama_host}:{ollama_port}/api/embeddings"

    # Общие
    model_name: str = os.getenv("MODEL_NAME", "text-embedding-bge-m3")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "1024"))

    def get_lm_studio_base_url(self) -> str:
        return f"http://{self.lm_studio_host}:{self.lm_studio_port}"

    def get_ollama_base_url(self) -> str:
        return f"http://{self.ollama_host}:{self.ollama_port}"


@dataclass
class ServerConfig:
    """Конфигурация для серверов (MCP, LSP, Hybrid)"""
    # MCP Server
    mcp_host: str = os.getenv("MCP_HOST", "127.0.0.1")
    mcp_port: int = int(os.getenv("MCP_PORT", "8765"))
    mcp_sse_url: str = f"http://{mcp_host}:{mcp_port}/sse"

    # LSP Server
    lsp_host: str = os.getenv("LSP_HOST", "127.0.0.1")

    def get_mcp_url(self) -> str:
        return f"http://{self.mcp_host}:{self.mcp_port}"


@dataclass
class SearchConfig:
    """Конфигурация для поиска и реранкинга"""
    # Reranking
    reranker_providers: List[str] = field(default_factory=lambda: os.getenv("RERANKER_PROVIDERS", "ollama,lm_studio").split(","))
    max_chunk_preview_len: int = int(os.getenv("MAX_CHUNK_PREVIEW_LEN", "800"))

    # Search
    default_search_limit: int = int(os.getenv("DEFAULT_SEARCH_LIMIT", "6"))
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "20"))

    # Query expansion
    query_synonyms_enabled: bool = os.getenv("QUERY_SYNONYMS_ENABLED", "true").lower() == "true"
    max_query_expansions: int = int(os.getenv("MAX_QUERY_EXPANSIONS", "3"))


@dataclass
class IndexConfig:
    """Конфигурация для индексации"""
    # LanceDB
    lancedb_version: str = os.getenv("LANCEDB_VERSION", "v2")

    # Chunking
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "512"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))

    # Performance
    index_batch_size: int = int(os.getenv("INDEX_BATCH_SIZE", "100"))
    max_concurrent_embeddings: int = int(os.getenv("MAX_CONCURRENT_EMBEDDINGS", "2"))


@dataclass
class PerformanceConfig:
    """Конфигурация производительности"""
    # Timeouts
    embedding_timeout: float = float(os.getenv("EMBEDDING_TIMEOUT", "30.0"))
    reranker_timeout: float = float(os.getenv("RERANKER_TIMEOUT", "30.0"))
    provider_ping_timeout: float = float(os.getenv("PROVIDER_PING_TIMEOUT", "0.5"))

    # Async settings
    max_async_workers: int = int(os.getenv("MAX_ASYNC_WORKERS", "10"))

    # Retry logic
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))

    # File operations
    file_retry_max_attempts: int = int(os.getenv("FILE_RETRY_MAX_ATTEMPTS", "3"))
    file_retry_delay: float = float(os.getenv("FILE_RETRY_DELAY", "0.05"))

    # Server startup
    mcp_startup_delay: float = float(os.getenv("MCP_STARTUP_DELAY", "1.0"))


@dataclass
class SecurityConfig:
    """Конфигурация безопасности"""
    # File filtering
    max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
    allowed_extensions: List[str] = field(default_factory=lambda: os.getenv("ALLOWED_EXTENSIONS",
        ".py,.rs,.ts,.jsx,.tsx,.js,.go,.java,.cpp,.c,.h,.hpp,.php,.rb,.md,.json,.yaml,.yml,.toml").split(","))

    # Path security
    allow_symlinks: bool = os.getenv("ALLOW_SYMLINKS", "true").lower() == "true"
    strict_path_validation: bool = os.getenv("STRICT_PATH_VALIDATION", "true").lower() == "true"


@dataclass
class Config:
    """Главная конфигурация, объединяющая все подконфигурации"""
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


# Глобальный экземпляр конфигурации
config = Config()


def reload_config() -> Config:
    """Перезагружает конфигурацию из переменных окружения"""
    global config
    config = Config()
    return config


def get_config() -> Config:
    """Возвращает текущую конфигурацию"""
    return config


# Удобные функции доступа
def get_lm_studio_embeddings_url() -> str:
    """Возвращает URL для эмбеддингов LM Studio"""
    return config.embedding.lm_studio_embeddings_url


def get_ollama_embeddings_url() -> str:
    """Возвращает URL для эмбеддингов Ollama"""
    return config.embedding.ollama_embeddings_url


def get_mcp_sse_url() -> str:
    """Возвращает URL для MCP SSE сервера"""
    return config.server.mcp_sse_url


def get_mcp_port() -> int:
    """Возвращает порт MCP сервера"""
    return config.server.mcp_port


def get_lm_studio_port() -> int:
    """Возвращает порт LM Studio"""
    return config.embedding.lm_studio_port


def get_ollama_port() -> int:
    """Возвращает порт Ollama"""
    return config.embedding.ollama_port
