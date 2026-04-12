"""Retrieval query engine with dense embedding search and cross-encoder reranking.

Pipeline (general queries):
1. Embed user query with Sentence Transformers
2. ANN search in ChromaDB (top-K candidates)
3. Document-aware expansion: if query names a specific regulation, fetch ALL
   chunks from that document and merge into the candidate pool
4. Rerank merged pool with cross-encoder (top-N final results)

Pipeline (single-document queries — named regulation with ≤30 chunks):
1–3. Same as above
4. BYPASS reranker — return ALL chunks from the named document directly.
   The document is small enough to fit in one LLM context window, and the
   English-trained cross-encoder cannot reliably rank Portuguese legal prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import chromadb
import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

from src.config import settings

# ---------------------------------------------------------------------------
# Regex patterns that match regulation references in a query.
# Each pattern captures a normalized key used to build a ChromaDB source filter.
# ---------------------------------------------------------------------------
_REG_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "Resolução CMN nº 5.274/2025", "Res. CMN 5274", "Resolução 5.274" …
    (
        re.compile(
            r"Resolu[cç][aã]o\s+(?:CMN\s+)?(?:n[oº°]?\s*)?(\d[\d.]*)"
            r"(?:/(\d{4}))?",
            re.IGNORECASE,
        ),
        "res",
    ),
    # "Circular BCB nº 3.978", "Circ. 3978" …
    (
        re.compile(
            r"Circular\s+(?:BCB\s+)?(?:n[oº°]?\s*)?(\d[\d.]*)",
            re.IGNORECASE,
        ),
        "circ",
    ),
    # "Resolução BCB nº 119" …
    (
        re.compile(
            r"Resolu[cç][aã]o\s+BCB\s+(?:n[oº°]?\s*)?(\d[\d.]*)",
            re.IGNORECASE,
        ),
        "res_bcb",
    ),
]


def _extract_regulation_numbers(query: str) -> list[str]:
    """Return bare regulation numbers mentioned in *query* (e.g. ['5274', '4893']).

    Strips dots so '5.274' and '5274' both return '5274' for easy comparison.
    """
    found: list[str] = []
    for pattern, _ in _REG_PATTERNS:
        for m in pattern.finditer(query):
            raw = m.group(1).replace(".", "")
            if raw not in found:
                found.append(raw)
    return found


def _fetch_document_chunks(
    collection: chromadb.Collection,
    reg_numbers: list[str],
) -> tuple[list[str], list[dict], list[str]]:
    """Fetch every chunk whose source filename contains any of *reg_numbers*.

    Returns (documents, metadatas, ids).
    """
    if not reg_numbers:
        return [], [], []

    all_docs: list[str] = []
    all_metas: list[dict] = []
    all_ids: list[str] = []

    result = collection.get(include=["documents", "metadatas"])
    for chunk_id, doc, meta in zip(
        result["ids"], result["documents"], result["metadatas"]
    ):
        source: str = meta.get("source", "")
        # Normalise: drop dots, lowercase
        source_norm = source.replace(".", "").lower()
        if any(num in source_norm for num in reg_numbers):
            all_docs.append(doc)
            all_metas.append(meta)
            all_ids.append(chunk_id)

    return all_docs, all_metas, all_ids


@dataclass
class RetrievedChunk:
    """A retrieved text chunk with its relevance score and source metadata."""

    content: str
    score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class RetrievalDetails:
    """Intermediate data from each stage of the retrieval pipeline."""

    query: str
    # Step 1 — vector search: list of (content, metadata, cosine_distance)
    vec_results: list[tuple[str, dict, float]]
    # Step 2 — document-aware expansion
    reg_numbers: list[str]
    expansion_chunks: list[tuple[str, dict]]  # all fetched for named doc(s)
    new_chunks_added: int                     # after dedup against vec_results
    bypass_reranker: bool
    # Step 3 — reranking (0 when bypassed)
    merged_pool_size: int
    final_chunks: list[RetrievedChunk]


def retrieve_with_details(query: str) -> RetrievalDetails:
    """Same pipeline as retrieve() but returns all intermediate stage data."""
    embedder = SentenceTransformer(settings.embedding_model)
    query_embedding: List[float] = embedder.encode(query).tolist()

    client = chromadb.PersistentClient(path=settings.chroma_db_path)
    collection = client.get_or_create_collection(settings.collection_name)

    # Step 1: vector search
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=settings.retrieval_top_k,
        include=["documents", "metadatas", "distances"],
    )
    vec_docs: List[str]    = results["documents"][0]
    vec_metas: List[dict]  = results["metadatas"][0]
    vec_ids: List[str]     = results["ids"][0]
    vec_dists: List[float] = results["distances"][0]

    if not vec_docs:
        return RetrievalDetails(
            query=query, vec_results=[], reg_numbers=[],
            expansion_chunks=[], new_chunks_added=0,
            bypass_reranker=False, merged_pool_size=0, final_chunks=[],
        )

    vec_results = list(zip(vec_docs, vec_metas, vec_dists))

    # Step 2: document-aware expansion
    reg_numbers = _extract_regulation_numbers(query)
    exp_docs, exp_metas, exp_ids = _fetch_document_chunks(collection, reg_numbers)
    expansion_chunks = list(zip(exp_docs, exp_metas))

    # Bypass path (small named document — skip reranker)
    if exp_docs and len(exp_docs) <= 30:
        final = [
            RetrievedChunk(content=doc, score=1.0, metadata=meta)
            for doc, meta in zip(exp_docs, exp_metas)
        ]
        return RetrievalDetails(
            query=query, vec_results=vec_results,
            reg_numbers=reg_numbers, expansion_chunks=expansion_chunks,
            new_chunks_added=0, bypass_reranker=True,
            merged_pool_size=0, final_chunks=final,
        )

    # Merge with dedup
    seen_ids: set[str] = set(vec_ids)
    merged_docs  = list(vec_docs)
    merged_metas = list(vec_metas)
    new_count = 0
    for doc, meta, cid in zip(exp_docs, exp_metas, exp_ids):
        if cid not in seen_ids:
            merged_docs.append(doc)
            merged_metas.append(meta)
            seen_ids.add(cid)
            new_count += 1

    # Step 3: reranking
    reranker = CrossEncoder(settings.reranker_model)
    scores: np.ndarray = reranker.predict([[query, doc] for doc in merged_docs])
    ranked = sorted(
        zip(merged_docs, merged_metas, scores.tolist()),
        key=lambda x: x[2], reverse=True,
    )[: settings.rerank_top_k]

    final = [
        RetrievedChunk(content=doc, score=float(score), metadata=meta)
        for doc, meta, score in ranked
    ]
    return RetrievalDetails(
        query=query, vec_results=vec_results,
        reg_numbers=reg_numbers, expansion_chunks=expansion_chunks,
        new_chunks_added=new_count, bypass_reranker=False,
        merged_pool_size=len(merged_docs), final_chunks=final,
    )


def retrieve(query: str) -> List[RetrievedChunk]:
    """Retrieve and rerank the most relevant chunks for a query."""
    return retrieve_with_details(query).final_chunks
