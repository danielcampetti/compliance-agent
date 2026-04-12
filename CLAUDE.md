# ComplianceAgent — Project Guide for Claude

## What This Project Is

ComplianceAgent is a multi-agent RAG-based assistant for Brazilian financial compliance and regulation. It ingests PDF documents from the Brazilian Central Bank (BCB), CVM, and other regulatory bodies, processes them into a vector store, and answers questions with source citations.

**Target Audience:** AI Engineer / GenAI Engineer positions at Brazilian financial institutions (Banco BV, Neon, CashMe, CI&T, Radix, etc).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| LLM | Ollama (llama3:8b) — local, zero cost |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) — local |
| Reranking | cross-encoder/ms-marco-MiniLM-L-6-v2 — local |
| Vector Store | ChromaDB (file-based, persistent) |
| Database | PostgreSQL (Phase 2+) |
| API | FastAPI |
| Agent Framework | LangChain / LangGraph (Phase 2+) |
| Frontend | React (Phase 3+) |
| Containerization | Docker + Docker Compose |
| CI/CD | GitHub Actions |

## Project Phases

### Phase 1 — Basic RAG System [CURRENT]
Functional RAG pipeline: ingest BCB PDFs → vector store → answer questions with citations.
**Status:** In Progress

Modules:
- `src/config.py` — Central Pydantic Settings config
- `src/ingestion/pdf_loader.py` — PyMuPDF PDF extraction
- `src/ingestion/chunker.py` — RecursiveCharacterTextSplitter chunking
- `src/ingestion/embedder.py` — Sentence Transformers + ChromaDB indexing
- `src/retrieval/query_engine.py` — Similarity search + cross-encoder reranking
- `src/retrieval/prompt_builder.py` — Portuguese prompt assembly with citations
- `src/llm/ollama_client.py` — Ollama HTTP client (sync + streaming)
- `src/api/main.py` — FastAPI: POST /ingest, POST /chat, GET /documents

### Phase 2 — Multi-Agent System [FUTURE]
Agent Coordinator → Knowledge Agent (RAG) + Data Agent (SQL) + Action Agent
Communication via MCP (Model Context Protocol). LangGraph orchestration.

### Phase 3 — Frontend & Integration [FUTURE]
React frontend, real-time SSE streaming, document management panel, JWT auth.

### Phase 4 — Governance & Observability [FUTURE]
PII masking (LGPD), structured logging, automated RAG evals, GitHub Actions CI/CD.

## Architecture Decisions

- **Local-first:** Zero cloud dependency. Ollama for LLM, sentence-transformers for embeddings.
- **ChromaDB over Pinecone/Weaviate:** No API key, no network latency, portable.
- **Cross-encoder reranking:** Retrieves top-20, reranks to top-5. Better precision than pure vector search.
- **Portuguese prompts:** All system prompts, error messages, and API responses are in Brazilian Portuguese.
- **Pydantic Settings:** All config from environment variables with `.env` file support.

## Coding Conventions

- **Type hints** on all function signatures and class attributes
- **Docstrings** on all public functions and classes (Google style)
- **Async** for all FastAPI endpoints and Ollama client
- **dataclasses** for internal data transfer objects (DocumentPage, TextChunk, RetrievedChunk)
- **No global state** — models loaded inside functions or dependency-injected
- All user-facing text in **Brazilian Portuguese**
- Tests use `pytest`, mocking external services (ChromaDB, Ollama, SentenceTransformer)

## Module Status Tracker

| Module | Status |
|--------|--------|
| src/config.py | ⬜ Pending |
| src/ingestion/pdf_loader.py | ⬜ Pending |
| src/ingestion/chunker.py | ⬜ Pending |
| src/ingestion/embedder.py | ⬜ Pending |
| src/retrieval/query_engine.py | ⬜ Pending |
| src/retrieval/prompt_builder.py | ⬜ Pending |
| src/llm/ollama_client.py | ⬜ Pending |
| src/api/main.py | ⬜ Pending |
| Dockerfile + docker-compose.yml | ⬜ Pending |
| README.md | ⬜ Pending |

## Running Locally (Phase 1)

```bash
# Install deps
pip install -r requirements.txt

# Start Ollama separately (outside Docker for dev)
ollama serve
ollama pull llama3:8b

# Start API
uvicorn src.api.main:app --reload

# Drop PDFs in data/raw/, then:
curl -X POST http://localhost:8000/ingest
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"pergunta": "O que é política de conformidade?"}'
```
