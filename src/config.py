"""Central configuration for ComplianceAgent.

All values can be overridden via environment variables or a .env file.
"""
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Paths
    data_raw_dir: Path = Path("data/raw")
    chroma_db_path: str = "./chroma_db"

    # Database
    db_path: str = "./data/compliance.db"

    # Embedding model (local, no API key required)
    embedding_model: str = "all-MiniLM-L6-v2"

    # Reranking model (local, no API key required)
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

    # Chunking parameters
    chunk_size: int = 800
    chunk_overlap: int = 100

    # Retrieval parameters
    retrieval_top_k: int = 50
    rerank_top_k: int = 20

    # Ollama connection
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3:8b"

    # ChromaDB collection name
    collection_name: str = "compliance_docs"

    # LLM provider selection: "ollama" or "claude"
    llm_provider: str = "ollama"

    # Claude / Anthropic settings
    claude_model: str = "claude-sonnet-4-6"
    anthropic_api_key: Optional[str] = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
