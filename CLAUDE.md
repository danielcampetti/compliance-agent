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

### Phase 1 — Basic RAG System [Complete]
Functional RAG pipeline: ingest BCB PDFs → vector store → answer questions with citations.
**Status:** Complete

Modules:
- `src/config.py` — Central Pydantic Settings config (llm_provider, claude_model, anthropic_api_key)
- `src/ingestion/pdf_loader.py` — PyMuPDF PDF extraction
- `src/ingestion/chunker.py` — RecursiveCharacterTextSplitter chunking
- `src/ingestion/embedder.py` — Sentence Transformers + ChromaDB indexing
- `src/retrieval/query_engine.py` — Similarity search + cross-encoder reranking
- `src/retrieval/prompt_builder.py` — Portuguese prompt assembly with citations
- `src/llm/ollama_client.py` — Ollama HTTP client (async, full + streaming)
- `src/llm/claude_client.py` — Anthropic Claude client (async, full + streaming, prompt caching)
- `src/api/main.py` — FastAPI: GET /, POST /ingest, POST /chat, GET /documents
- `src/api/diagnostic.py` — POST /diagnostic: raw RAG inspection without LLM
- `src/api/evaluate.py` — POST /evaluate (Claude grader), POST /test-pipeline (Ollama vs Claude)

### Phase 2 — Multi-Agent System [CURRENT]
**Status:** Complete

Architecture:
```
User Question → CoordinatorAgent → KnowledgeAgent | DataAgent | ActionAgent
                                      ChromaDB       SQLite      SQLite
```

Agents:
- `src/agents/coordinator.py` — Routes via LLM classification + heuristic fallback
- `src/agents/knowledge_agent.py` — Wraps Phase 1 RAG pipeline (retrieve → prompt → Ollama)
- `src/agents/data_agent.py` — NL→SQL→execute→NL-interpret against SQLite compliance.db
- `src/agents/action_agent.py` — Creates/updates alerts, marks COAF reports, logs actions

Database:
- `data/compliance.db` — SQLite; tables: transactions, alerts, agent_log
- `src/database/setup.py` — DDL; `src/database/seed.py` — 50 transactions, 5 alerts

New API endpoints:
- `POST /agent` — Multi-agent routing (returns `CoordinatorResponse`)
- `GET /alerts?status=&severity=` — List compliance alerts with optional filters
- `GET /transactions?transaction_type=&amount_min=&reported_to_coaf=` — List transactions

Example multi-agent queries:
```bash
# Data route
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Quantas transações em espécie não foram reportadas ao COAF?"}'

# Knowledge route
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Qual o prazo da Resolução CMN 5.274/2025?"}'

# Combined route (KNOWLEDGE+DATA)
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Verifique se estamos em conformidade com o Art. 49 da Circular 3.978"}'

# Action route
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Gere um relatório de alertas abertos"}'
```

### Phase 3 — Frontend & Integration [FUTURE]

React frontend, real-time SSE streaming, document management panel, JWT auth.

### Phase 4 — Governance & Observability [FUTURE]
PII masking (LGPD), structured logging, automated RAG evals, GitHub Actions CI/CD.

## Architecture Decisions

- **Local-first:** Zero cloud dependency. Ollama for LLM, sentence-transformers for embeddings.
- **ChromaDB over Pinecone/Weaviate:** No API key, no network latency, portable.
- **Cross-encoder reranking:** Retrieves top-50, reranks to top-20. Better precision than pure vector search.
- **Reranker bypass:** When a named regulation has ≤30 chunks, all chunks are sent directly to the LLM (skipping reranking). Fixes precision loss for small documents with English-trained cross-encoder.
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
| src/config.py | ✅ Done |
| src/ingestion/pdf_loader.py | ✅ Done |
| src/ingestion/chunker.py | ✅ Done |
| src/ingestion/embedder.py | ✅ Done |
| src/retrieval/query_engine.py | ✅ Done |
| src/retrieval/prompt_builder.py | ✅ Done |
| src/llm/ollama_client.py | ✅ Done |
| src/llm/claude_client.py | ✅ Done |
| src/api/main.py | ✅ Done |
| src/api/diagnostic.py | ✅ Done |
| src/api/evaluate.py | ✅ Done |
| src/api/templates/index.html | ✅ Done |
| Dockerfile + docker-compose.yml | ✅ Done |
| README.md | ✅ Done |
| src/database/connection.py | ✅ Done |
| src/database/setup.py | ✅ Done |
| src/database/seed.py | ✅ Done |
| src/agents/base.py | ✅ Done |
| src/agents/knowledge_agent.py | ✅ Done |
| src/agents/data_agent.py | ✅ Done |
| src/agents/action_agent.py | ✅ Done |
| src/agents/coordinator.py | ✅ Done |
| src/evaluation/benchmark.py | ✅ Done |

## Running Locally (Phase 1)

```bash
# Install deps
pip install -r requirements.txt

# Start Ollama separately (outside Docker for dev)
ollama serve
ollama pull llama3:8b

# Set Anthropic key for evaluation endpoints (optional)
export ANTHROPIC_API_KEY=sk-ant-...

# Start API
uvicorn src.api.main:app --reload

# Drop PDFs in data/raw/, then:
curl -X POST http://localhost:8000/ingest
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"pergunta": "O que e politica de conformidade?"}'

# Use Claude instead of Ollama for a single request:
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"pergunta": "O que e PLD?", "provider": "claude"}'

# Inspect RAG results without calling any LLM:
curl -X POST http://localhost:8000/diagnostic -H "Content-Type: application/json" \
     -d '{"pergunta": "O que e ciberseguranca?"}'

# Grade a response using Claude as judge:
curl -X POST http://localhost:8000/evaluate -H "Content-Type: application/json" \
     -d '{"pergunta": "O que e compliance?", "resposta": "Compliance e conformidade regulatoria."}'

# Compare Ollama vs Claude side-by-side:
curl -X POST http://localhost:8000/test-pipeline -H "Content-Type: application/json" \
     -d '{"pergunta": "Quais sao as obrigacoes de ciberseguranca?"}'
```

## Evaluation System (Phase 1 Extension)

`POST /diagnostic` — Inspects all three stages of the RAG pipeline without calling the LLM. Returns:
- `busca_vetorial`: top-50 vector search candidates with cosine similarity scores
- `expansao_documento`: regulations detected in the query, chunks fetched, dedup count, bypass flag
- `reranking`: cross-encoder reranking results (null when reranker was bypassed for small documents)
- `chunks_enviados_ao_llm`: count of final chunks that would be sent to the LLM

`POST /evaluate` — Takes `pergunta` + `resposta_rag` (+ optional `resposta_esperada`). Uses Claude as judge with 5 compliance-specific criteria:
- `precisao_normativa` — accuracy of regulatory citations
- `completude` — coverage of all relevant aspects
- `relevancia_chunks` — quality of retrieved context
- `coerencia` — logical consistency of the answer
- `alucinacao` — absence of fabricated content (10 = no hallucination)
- Returns `nota_geral` + `veredicto` (APROVADO ≥7.0 / REPROVADO <7.0)

`POST /test-pipeline` — Runs the full pipeline: retrieves chunks via RAG, generates answer with Ollama, evaluates with Claude. Returns `chunks_recuperados`, `resposta_ollama`, `avaliacao`, and `tempo_resposta_segundos`.

`python -m src.evaluation.benchmark` — Batch runner across 15 compliance test questions (`src/evaluation/test_dataset.json`). Covers prazo, PLD, and segurança cibernética categories. Saves results to `data/benchmark_report.json`.
```bash
python -m src.evaluation.benchmark          # all 15 questions
python -m src.evaluation.benchmark --limit 3  # first 3 only
```

`POST /chat` accepts an optional `"provider": "claude"` field to route a single request to Claude instead of Ollama.
