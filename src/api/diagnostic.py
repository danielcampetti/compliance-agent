"""Diagnostic endpoint — inspect every stage of the RAG pipeline without calling the LLM."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from fastapi import APIRouter
from pydantic import BaseModel

from src.retrieval.query_engine import retrieve_with_details

router = APIRouter()


class ChunkPreview(BaseModel):
    rank: int
    documento: str
    pagina: Union[int, str]
    texto_preview: str
    score: float


class BuscaVetorial(BaseModel):
    total_candidatos: int
    top_10: List[ChunkPreview]


class ExpansaoDocumento(BaseModel):
    regulamentos_detectados: List[str]
    total_chunks_documento: int
    chunks_novos_adicionados: int
    bypass_reranker: bool


class Reranking(BaseModel):
    total_entrada: int
    top_10: List[ChunkPreview]


class DiagnosticRequest(BaseModel):
    pergunta: str


class DiagnosticResponse(BaseModel):
    pergunta: str
    busca_vetorial: BuscaVetorial
    expansao_documento: ExpansaoDocumento
    reranking: Optional[Reranking]   # None when reranker was bypassed
    chunks_enviados_ao_llm: int


@router.post(
    "/diagnostic",
    response_model=DiagnosticResponse,
    summary="Inspecionar etapas do pipeline RAG sem chamar LLM",
)
async def diagnostic(request: DiagnosticRequest) -> DiagnosticResponse:
    """Return intermediate data from each RAG pipeline stage.

    Shows what the vector search retrieved, what the document-aware expansion
    added, whether the reranker was bypassed, and how many chunks would be sent
    to the LLM — all without making any LLM call.
    """
    det = retrieve_with_details(request.pergunta)

    vec_top10 = [
        ChunkPreview(
            rank=i + 1,
            documento=Path(meta.get("source", "desconhecido")).name,
            pagina=meta.get("page", "?"),
            texto_preview=doc[:200],
            score=round(1.0 - dist, 4),  # cosine distance → similarity
        )
        for i, (doc, meta, dist) in enumerate(det.vec_results[:10])
    ]

    expansao = ExpansaoDocumento(
        regulamentos_detectados=det.reg_numbers,
        total_chunks_documento=len(det.expansion_chunks),
        chunks_novos_adicionados=det.new_chunks_added,
        bypass_reranker=det.bypass_reranker,
    )

    reranking: Optional[Reranking] = None
    if not det.bypass_reranker and det.final_chunks:
        reranking = Reranking(
            total_entrada=det.merged_pool_size,
            top_10=[
                ChunkPreview(
                    rank=i + 1,
                    documento=Path(c.metadata.get("source", "desconhecido")).name,
                    pagina=c.metadata.get("page", "?"),
                    texto_preview=c.content[:200],
                    score=round(c.score, 4),
                )
                for i, c in enumerate(det.final_chunks[:10])
            ],
        )

    return DiagnosticResponse(
        pergunta=request.pergunta,
        busca_vetorial=BuscaVetorial(
            total_candidatos=len(det.vec_results),
            top_10=vec_top10,
        ),
        expansao_documento=expansao,
        reranking=reranking,
        chunks_enviados_ao_llm=len(det.final_chunks),
    )
