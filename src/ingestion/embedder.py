"""Embedding generation and ChromaDB vector store management.

Generates dense embeddings from text chunks using Sentence Transformers
and persists them to a local ChromaDB collection with source metadata.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import List, Optional

import chromadb
from sentence_transformers import SentenceTransformer

from src.config import settings
from src.ingestion.chunker import TextChunk


def _format_number(num_raw: str) -> str:
    """Add a thousands-separator period to a resolution number if absent.

    Examples: '5274' → '5.274', '4.893' → '4.893', '3978' → '3.978'
    """
    if "." in num_raw:
        return num_raw
    if len(num_raw) >= 4:
        return num_raw[:-3] + "." + num_raw[-3:]
    return num_raw


def _doc_label(filename: str) -> str:
    """Derive a human-readable document label from a BCB PDF filename.

    Supported patterns:
    - ``res_5274_18_12_2025.pdf``  → ``Resolução CMN nº 5.274/2025``
    - ``res_4.893_26_02_2021.pdf`` → ``Resolução CMN nº 4.893/2021``
    - ``Circ_3978_v3_P.pdf``       → ``Circular BCB nº 3.978``

    Falls back to the filename stem for unrecognized patterns.

    Args:
        filename: PDF filename (basename, with or without path).

    Returns:
        Human-readable document label string.
    """
    stem = Path(filename).stem

    m = re.match(r"res_([\d.]+)_\d{2}_\d{2}_(\d{4})", stem, re.IGNORECASE)
    if m:
        num, year = _format_number(m.group(1)), m.group(2)
        return f"Resolução CMN nº {num}/{year}"

    m = re.match(r"Circ_(\d+)", stem, re.IGNORECASE)
    if m:
        return f"Circular BCB nº {_format_number(m.group(1))}"

    return stem


def _get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=settings.chroma_db_path)


def _get_collection(client: chromadb.PersistentClient) -> chromadb.Collection:
    return client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def index_chunks(chunks: List[TextChunk]) -> int:
    """Embed a list of text chunks and store them in ChromaDB.

    Args:
        chunks: TextChunk objects to embed and index.

    Returns:
        Number of chunks successfully indexed.
    """
    model = SentenceTransformer(settings.embedding_model)
    client = _get_client()
    collection = _get_collection(client)

    texts = [c.content for c in chunks]
    # Prefix each text with its document label so the embedding space aligns
    # query mentions of "Resolução CMN nº X.XXX/YYYY" with the right chunks.
    # The original clean text is stored in ChromaDB; only the embedding changes.
    embedding_texts = [f"[{_doc_label(c.filename)}] {c.content}" for c in chunks]
    raw = model.encode(embedding_texts, show_progress_bar=True)
    embeddings = raw.tolist() if hasattr(raw, "tolist") else list(raw)
    ids = [str(uuid.uuid4()) for _ in chunks]
    metadatas = [c.metadata for c in chunks]

    collection.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(chunks)


def list_indexed_documents(client: Optional[chromadb.PersistentClient] = None) -> List[dict]:
    """Return one metadata record per unique source document in the collection.

    Args:
        client: Optional pre-existing ChromaDB client (creates new one if not provided).

    Returns:
        List of metadata dicts, one per unique source file.
    """
    if client is None:
        client = _get_client()
    collection = _get_collection(client)
    result = collection.get(include=["metadatas"])

    seen: dict[str, dict] = {}
    for meta in result["metadatas"]:
        source = meta.get("source", "desconhecido")
        if source not in seen:
            seen[source] = meta

    return list(seen.values())
