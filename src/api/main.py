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

import json
from pathlib import Path
from typing import List, Optional, Union

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

_TEMPLATE_PATH  = Path(__file__).parent / "templates" / "index.html"
_LOGIN_PATH     = Path(__file__).parent / "templates" / "login.html"
_DASHBOARD_PATH = Path(__file__).parent / "templates" / "dashboard.html"

from src.config import settings
from src.api.auth import TokenUser, require_role
from src.api.auth_routes import auth_router
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
from src.services.conversation import ConversationService
from src.api.diagnostic import router as diagnostic_router
from src.api.evaluate import router as evaluate_router
from src.api.conversation_routes import conversation_router

app = FastAPI(
    title="ComplianceAgent API",
    description="Sistema RAG para compliance e regulamentacao financeira brasileira",
    version="1.0.0",
)

app.include_router(auth_router)
app.include_router(diagnostic_router)
app.include_router(evaluate_router)
app.include_router(conversation_router)


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
    provider: Optional[str] = None  # "ollama" or "claude"; falls back to settings.llm_provider
    conversation_id: Optional[int] = None  # NEW — enables persistent memory


# -- Endpoints ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def chat_ui() -> HTMLResponse:
    """Serve the browser chat interface."""
    return HTMLResponse(_TEMPLATE_PATH.read_text(encoding="utf-8"))


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_ui() -> HTMLResponse:
    return HTMLResponse(_LOGIN_PATH.read_text(encoding="utf-8"))


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_ui() -> HTMLResponse:
    return HTMLResponse(_DASHBOARD_PATH.read_text(encoding="utf-8"))


@app.post("/ingest", summary="Indexar documentos PDF")
async def ingest(_: TokenUser = Depends(require_role("manager"))) -> dict:
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
async def chat(request: ChatRequest, _: TokenUser = Depends(require_role("analyst", "manager"))) -> ChatResponse:
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
    try:
        if provider == "claude":
            resposta = await claude_client.generate(prompt)
        else:
            resposta = await ollama_client.generate(prompt)
    except ValueError as exc:
        if "ANTHROPIC_API_KEY" in str(exc):
            raise HTTPException(status_code=503, detail=str(exc))
        raise

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
async def list_documents(_: TokenUser = Depends(require_role("analyst", "manager"))) -> dict:
    """Lista todos os documentos unicos presentes no indice vetorial.

    Returns:
        Dict com lista de documentos e contagem total.
    """
    client = _get_chroma_client()
    docs = list_indexed_documents(client)
    return {"documentos": docs, "total": len(docs)}


@app.post("/agent", response_model=CoordinatorResponse)
async def agent_endpoint(
    request: AgentRequest,
    current_user: TokenUser = Depends(require_role("analyst", "manager")),
) -> CoordinatorResponse:
    """Route a question to the appropriate specialized agent(s).

    When conversation_id is provided, saves both user question and agent response
    to the messages table and passes prior context to the coordinator.
    """
    provider = (request.provider or settings.llm_provider).lower()
    coordinator = CoordinatorAgent()
    svc = ConversationService()

    conversation_history = None
    if request.conversation_id is not None:
        # Verify ownership before any read or write
        if svc.get_by_id(request.conversation_id, current_user.user_id) is None:
            raise HTTPException(
                status_code=404,
                detail="Conversa não encontrada ou sem permissão de acesso.",
            )
        # Snapshot history BEFORE saving current message (these are the prior exchanges)
        conversation_history = svc.get_context_messages(
            request.conversation_id, max_messages=10
        )
        is_first_message = len(conversation_history) == 0
        svc.add_message(request.conversation_id, "user", request.pergunta)
        if is_first_message:
            svc.update_title(
                request.conversation_id,
                current_user.user_id,
                ConversationService.auto_title(request.pergunta),
            )

    try:
        response = await coordinator.process(
            request.pergunta,
            provider=provider,
            user_id=current_user.user_id,
            username=current_user.username,
            conversation_history=conversation_history,
        )
    except ValueError as exc:
        if "ANTHROPIC_API_KEY" in str(exc):
            raise HTTPException(status_code=503, detail=str(exc))
        raise

    if request.conversation_id is not None:
        svc.add_message(
            request.conversation_id,
            "assistant",
            response.resposta_final,
            agent_used=",".join(response.agentes_utilizados),
            provider=response.provider_utilizado,
            data_classification=response.data_classification,
            pii_detected=response.pii_detected,
        )

    return response


@app.post("/agent/stream")
async def agent_stream_endpoint(
    request: AgentRequest,
    current_user: TokenUser = Depends(require_role("analyst", "manager")),
) -> StreamingResponse:
    """Stream agent response via Server-Sent Events.

    Mirrors /agent's auth, conversation_id handling, and message persistence.
    The original POST /agent endpoint is unchanged for backward compatibility.
    """
    provider = (request.provider or settings.llm_provider).lower()
    coordinator = CoordinatorAgent()
    svc = ConversationService()

    conversation_history = None
    if request.conversation_id is not None:
        if svc.get_by_id(request.conversation_id, current_user.user_id) is None:
            raise HTTPException(
                status_code=404,
                detail="Conversa não encontrada ou sem permissão de acesso.",
            )
        conversation_history = svc.get_context_messages(
            request.conversation_id, max_messages=10
        )
        is_first_message = len(conversation_history) == 0
        svc.add_message(request.conversation_id, "user", request.pergunta)
        if is_first_message:
            svc.update_title(
                request.conversation_id,
                current_user.user_id,
                ConversationService.auto_title(request.pergunta),
            )

    async def event_generator():
        full_response = ""
        agents_used: list[str] = []
        data_classification: str = "public"
        pii_detected: bool = False

        async for event in coordinator.process_stream(
            request.pergunta,
            provider=provider,
            user_id=current_user.user_id,
            username=current_user.username,
            conversation_history=conversation_history,
        ):
            yield event
            if event.startswith("data:"):
                try:
                    data = json.loads(event[5:].strip())
                    if data.get("type") == "metadata":
                        agents_used = data.get("agentes_utilizados", [])
                    elif data.get("type") == "done":
                        full_response = data.get("full_response", "")
                        data_classification = data.get("data_classification", "public")
                        pii_detected = data.get("pii_detected", False)
                except Exception:
                    pass

        if request.conversation_id is not None and full_response:
            svc.add_message(
                request.conversation_id,
                "assistant",
                full_response,
                agent_used=",".join(agents_used) if agents_used else None,
                provider=provider,
                data_classification=data_classification,
                pii_detected=pii_detected,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/alerts")
async def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    _: TokenUser = Depends(require_role("analyst", "manager")),
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
    _: TokenUser = Depends(require_role("analyst", "manager")),
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
