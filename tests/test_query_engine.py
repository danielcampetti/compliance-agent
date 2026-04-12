"""Tests for the retrieval and reranking query engine."""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from src.retrieval.query_engine import retrieve, RetrievedChunk


def _mock_chroma_query_result(docs: list, scores: list) -> dict:
    return {
        "ids": [[f"id{i}" for i in range(len(docs))]],
        "documents": [docs],
        "metadatas": [[{"source": f"doc{i}.pdf", "page": i + 1} for i in range(len(docs))]],
        "distances": [scores],
    }


def test_retrieve_returns_retrieved_chunk_instances() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = _mock_chroma_query_result(
        ["Artigo 1 compliance.", "Artigo 2 risco."],
        [0.1, 0.2],
    )
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = np.array([0.9, 0.7])

    with patch("src.retrieval.query_engine.SentenceTransformer") as mock_emb, \
         patch("src.retrieval.query_engine.CrossEncoder", return_value=mock_reranker), \
         patch("src.retrieval.query_engine.chromadb.PersistentClient") as mock_client:
        mock_emb.return_value.encode.return_value = np.array([0.1, 0.2])
        mock_client.return_value.get_or_create_collection.return_value = mock_collection

        results = retrieve("O que e compliance?")

    assert len(results) >= 1
    assert isinstance(results[0], RetrievedChunk)


def test_retrieve_results_sorted_by_score_descending() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = _mock_chroma_query_result(
        ["doc A", "doc B", "doc C"],
        [0.1, 0.2, 0.3],
    )
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = np.array([0.6, 0.9, 0.75])

    with patch("src.retrieval.query_engine.SentenceTransformer") as mock_emb, \
         patch("src.retrieval.query_engine.CrossEncoder", return_value=mock_reranker), \
         patch("src.retrieval.query_engine.chromadb.PersistentClient") as mock_client:
        mock_emb.return_value.encode.return_value = np.array([0.5])
        mock_client.return_value.get_or_create_collection.return_value = mock_collection

        results = retrieve("pergunta")

    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_result_carries_metadata() -> None:
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["id0"]],
        "documents": [["Texto sobre PLD."]],
        "metadatas": [[{"source": "circ3978.pdf", "page": 7}]],
        "distances": [[0.1]],
    }
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = np.array([0.88])

    with patch("src.retrieval.query_engine.SentenceTransformer") as mock_emb, \
         patch("src.retrieval.query_engine.CrossEncoder", return_value=mock_reranker), \
         patch("src.retrieval.query_engine.chromadb.PersistentClient") as mock_client:
        mock_emb.return_value.encode.return_value = np.array([0.3])
        mock_client.return_value.get_or_create_collection.return_value = mock_collection

        results = retrieve("PLD FT")

    assert results[0].metadata["source"] == "circ3978.pdf"
    assert results[0].metadata["page"] == 7
