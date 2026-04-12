"""FastAPI application for ComplianceAgent.

Endpoints:
- GET  /           -- Chat UI (browser interface)
- POST /ingest     -- Index all PDFs in data/raw/
- POST /chat       -- Answer a regulatory question with source citations
- GET  /documents  -- List all indexed documents
- POST /diagnostic -- Raw RAG inspection without calling LLM
- POST /evaluate   -- Grade a RAG response using Claude as judge
- POST /test-pipeline -- Compare Ollama vs Claude on the same question
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

from src.config import settings
from src.ingestion.chunker import chunk_pages
from src.ingestion.embedder import _get_client as _get_chroma_client
from src.ingestion.embedder import index_chunks, list_indexed_documents
from src.ingestion.pdf_loader import load_all_pdfs
from src.llm import ollama_client, claude_client
from src.retrieval.prompt_builder import build_prompt
from src.retrieval.query_engine import retrieve
from src.agents.coordinator import CoordinatorAgent, CoordinatorResponse
from src.database.connection import get_db
from src.database.seed import init_db
from src.api.diagnostic import router as diagnostic_router
from src.api.evaluate import router as evaluate_router

app = FastAPI(
    title="ComplianceAgent API",
    description="Sistema RAG para compliance e regulamentacao financeira brasileira",
    version="1.0.0",
)

app.include_router(diagnostic_router)
app.include_router(evaluate_router)


# -- Request / Response models -----------------------------------------------

class ChatRequest(BaseModel):
    pergunta: str
    provider: Optional[str] = None  # "ollama" or "claude"; falls back to settings.llm_provider


class FonteSchema(BaseModel):
    arquivo: str
    pagina: Union[int, str]
    score: float


class ChatResponse(BaseModel):
    resposta: str
    fontes: List[FonteSchema]


class AgentRequest(BaseModel):
    pergunta: str


# -- Endpoints ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def chat_ui() -> HTMLResponse:
    """Serve the browser chat interface."""
    return HTMLResponse(_TEMPLATE_PATH.read_text(encoding="utf-8"))


@app.post("/ingest", summary="Indexar documentos PDF")
async def ingest() -> dict:
    """Processa todos os PDFs em data/raw/ e indexa seus chunks no ChromaDB.

    Returns:
        Dict com contagem de paginas processadas e chunks indexados.
    """
    raw_dir = Path(settings.data_raw_dir)
    if not raw_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Diretorio '{raw_dir}' nao encontrado. Crie-o e adicione PDFs.",
        )

    pages = load_all_pdfs(raw_dir)
    if not pages:
        return {
            "mensagem": "Nenhum PDF encontrado em data/raw/",
            "paginas_processadas": 0,
            "chunks_indexados": 0,
        }

    chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
    count = index_chunks(chunks)

    return {
        "mensagem": "Indexacao concluida com sucesso.",
        "paginas_processadas": len(pages),
        "chunks_indexados": count,
    }


@app.post("/chat", response_model=ChatResponse, summary="Consultar base regulatoria")
async def chat(request: ChatRequest) -> ChatResponse:
    """Recebe uma pergunta e retorna resposta com citacoes das fontes.

    Args:
        request: JSON body com campo `pergunta`.

    Returns:
        Resposta gerada pelo LLM e lista de fontes utilizadas.
    """
    chunks = retrieve(request.pergunta)

    if not chunks:
        return ChatResponse(
            resposta="Esta informacao nao foi encontrada nos documentos disponiveis.",
            fontes=[],
        )

    prompt = build_prompt(request.pergunta, chunks)
    provider = (request.provider or settings.llm_provider).lower()
    if provider == "claude":
        resposta = await claude_client.generate(prompt)
    else:
        resposta = await ollama_client.generate(prompt)

    fontes = [
        FonteSchema(
            arquivo=str(c.metadata.get("source", "desconhecido")),
            pagina=c.metadata.get("page", "?"),
            score=round(c.score, 4),
        )
        for c in chunks
    ]

    return ChatResponse(resposta=resposta, fontes=fontes)


@app.get("/documents", summary="Listar documentos indexados")
async def list_documents() -> dict:
    """Lista todos os documentos unicos presentes no indice vetorial.

    Returns:
        Dict com lista de documentos e contagem total.
    """
    client = _get_chroma_client()
    docs = list_indexed_documents(client)
    return {"documentos": docs, "total": len(docs)}


@app.post("/agent", response_model=CoordinatorResponse)
async def agent_endpoint(request: AgentRequest) -> CoordinatorResponse:
    """Route a question to the appropriate specialized agent(s).

    Supports regulatory questions (Knowledge), data queries (Data),
    compliance actions (Action), and combined queries (Knowledge+Data).
    """
    coordinator = CoordinatorAgent()
    return await coordinator.process(request.pergunta)


@app.get("/alerts")
async def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """List compliance alerts with optional filters."""
    init_db()
    conditions: list[str] = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= ?")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM alerts {where} ORDER BY created_at DESC", params
        ).fetchall()

    return {
        "alertas": [dict(r) for r in rows],
        "total": len(rows),
    }


@app.get("/transactions")
async def list_transactions(
    transaction_type: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    reported_to_coaf: Optional[bool] = None,
    pep_flag: Optional[bool] = None,
) -> dict:
    """List transactions with optional filters."""
    init_db()
    conditions: list[str] = []
    params: list = []

    if transaction_type:
        conditions.append("transaction_type = ?")
        params.append(transaction_type)
    if amount_min is not None:
        conditions.append("amount >= ?")
        params.append(amount_min)
    if amount_max is not None:
        conditions.append("amount <= ?")
        params.append(amount_max)
    if date_from:
        conditions.append("date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("date <= ?")
        params.append(date_to)
    if reported_to_coaf is not None:
        conditions.append("reported_to_coaf = ?")
        params.append(1 if reported_to_coaf else 0)
    if pep_flag is not None:
        conditions.append("pep_flag = ?")
        params.append(1 if pep_flag else 0)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM transactions {where} ORDER BY date DESC", params
        ).fetchall()

    return {
        "transacoes": [dict(r) for r in rows],
        "total": len(rows),
    }
