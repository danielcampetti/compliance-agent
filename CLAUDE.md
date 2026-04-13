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

### Phase 6 — Conversation Memory [CURRENT]
**Status:** Complete

Architecture:
```
User → POST /agent {conversation_id: N}
     → ConversationService.get_context_messages()  → last 10 msgs as history
     → ConversationService.add_message(user_msg)
     → CoordinatorAgent.process(history=...)
         → KnowledgeAgent.answer(history=...)
             → build_prompt(question, chunks, conversation_history=history)
     → ConversationService.add_message(assistant_msg)
```

New modules:
- `src/services/conversation.py` — ConversationService (create, list_by_user, get_by_id, get_messages, add_message, update_title, delete, get_context_messages, auto_title)
- `src/api/conversation_routes.py` — CRUD router at /conversations

New tables: `conversations`, `messages` (with cascade delete)

API endpoints:
- `GET  /conversations`              — list user's conversations (auth required)
- `POST /conversations`              — create conversation (auth required)
- `GET  /conversations/{id}`         — messages + metadata (auth, must own)
- `DELETE /conversations/{id}`       — soft-delete (auth, must own)
- `PATCH /conversations/{id}/title`  — rename (auth, must own)

Context injection: last 10 messages fed into `build_prompt()` between system prompt and RAG chunks. RAG retrieval still uses current question only.

Frontend: 280px collapsible sidebar with date-grouped history, click-to-load, auto-title on first message, mobile hamburger toggle.

### Phase 7 — SSE Streaming [CURRENT]
**Status:** Complete

Architecture:
```
POST /agent/stream (SSE, JWT-protected)
  → CoordinatorAgent.process_stream(question, provider, user_id, username, conversation_history)
  → metadata event  {type: "metadata", roteamento, agentes_utilizados}
  → sources event   {type: "sources", chunks: ["file.pdf, p. 3", ...]}  (KNOWLEDGE only)
  → token events    {type: "token", content: "..."}  (streamed for KNOWLEDGE; single for DATA/ACTION)
  → sql event       {type: "sql", sql: "...", total: N}  (DATA agent only)
  → actions event   {type: "actions", acoes: [...]}  (ACTION agent only)
  → done event      {type: "done", pii_detected, data_classification, session_id, full_response}
  → error event     {type: "error", message: "..."}  (on exception)
```

New methods:
- `src/llm/llm_router.py` → `generate_stream(prompt, provider)` — routes streaming to Ollama or Claude
- `src/agents/knowledge_agent.py` → `KnowledgeAgent.prepare(question, conversation_history)` → `(prompt, chunks)`
- `src/agents/coordinator.py` → `CoordinatorAgent.process_stream(question, provider, user_id, username, conversation_history)` — async generator

Endpoints:
- `POST /agent` — unchanged, returns complete `CoordinatorResponse` JSON
- `POST /agent/stream` — new, returns `text/event-stream` SSE; requires JWT; accepts `conversation_id`

Frontend: blinking gold cursor appears immediately on send; tokens render word-by-word; route badge appears on metadata event; source chips and SQL/action blocks appear after streaming completes; conversation sidebar refreshes after done.

## Development Rules

- **NEVER use git worktrees.** Always work directly on `master` or create simple feature branches with `git checkout -b feature/xxx`. Worktrees cause environment fragmentation (missing `.env`, missing DB, missing indexed documents) and should not be used in this project.

## Architecture Decisions

- **Local-first:** Zero cloud dependency. Ollama for LLM, sentence-transformers for embeddings.
- **ChromaDB over Pinecone/Weaviate:** No API key, no network latency, portable.
- **Cross-encoder reranking:** Retrieves top-50, reranks to top-20. Better precision than pure vector search.
- **Reranker bypass:** When a named regulation has ≤30 chunks, all chunks are sent directly to the LLM (skipping reranking). Used for small documents where the reranker may compress results too aggressively.
- **Multilingual reranker:** Uses `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (trained on mMARCO multilingual data including Brazilian Portuguese). Switched from the English-only `ms-marco-MiniLM-L-6-v2` after benchmark showed it discarded correct Portuguese chunks.
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
| src/services/conversation.py | ✅ Done |
| src/api/conversation_routes.py | ✅ Done |
| src/llm/llm_router.py | ✅ Done |
| tests/test_streaming.py | ✅ Done |

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

## Multi-LLM Support

ComplianceAgent supports two LLM backends for generation. The default is always Ollama (local, no cost). Claude is available for higher-quality demos and comparative benchmarking.

### Switching Providers

**Via API (per-request):**
```bash
# Chat endpoint with Claude
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "O que é PLD?", "provider": "claude"}'

# Agent endpoint with Claude
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Qual o prazo da Resolução 5.274?", "provider": "claude"}'
```

**Via environment variable (default for all requests):**
```bash
export LLM_PROVIDER=claude
uvicorn src.api.main:app --reload
```

**In the browser UI:** Use the `OLLAMA | CLAUDE` toggle in the top-right header.

**Important:** If `provider: "claude"` is requested but `ANTHROPIC_API_KEY` is not set, the API returns HTTP 503 with a clear error message.

### LLM Router

`src/llm/llm_router.py` provides a unified `generate(prompt, provider)` interface used by all agents. Agents no longer call `ollama_client` or `claude_client` directly — they call the router.

### Comparative Benchmarking

```bash
# Run benchmark with Ollama (default)
python -m src.evaluation.benchmark

# Run benchmark with Claude
python -m src.evaluation.benchmark --provider claude

# Run both and print side-by-side comparison
python -m src.evaluation.benchmark --compare

# Quick test with 3 questions
python -m src.evaluation.benchmark --compare --limit 3
```

Results are saved to date-stamped files:
- `data/benchmark_ollama_YYYY-MM-DD.json`
- `data/benchmark_claude_YYYY-MM-DD.json`

The `--compare` output diagnoses whether low scores are caused by model quality (Claude scores high, Ollama scores low) or pipeline issues (both score low on the same questions).

Cost tracking: Claude benchmark runs print estimated generation cost in USD using Sonnet pricing ($3/MTok input, $15/MTok output).

## RAG Quality Improvements (Benchmark-Driven)

**Benchmark baseline (before fixes):** 4/15 passed (27%), avg score 4.2/10

### Fix 1 — Multilingual Reranker
Switched from `cross-encoder/ms-marco-MiniLM-L-6-v2` (English-only, ~90MB) to
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingual mMARCO, ~480MB).

The English reranker scored Portuguese legal text by surface keyword overlap, not
semantic similarity — discarding the correct regulatory chunks before they reached
the LLM. The mMARCO model was trained on translated multilingual data that includes
Brazilian Portuguese.

No re-indexing required — the reranker operates at query time only.

### Fix 2 — Hardened Prompt Template
Replaced the prompt in `src/retrieval/prompt_builder.py` with 6 explicit rules:
- Explicit "NUNCA invente informações" hallucination ban
- Rule to copy monetary values, dates, and percentages EXACTLY from chunks
- Self-check instruction: re-read chunks before answering
- Clearer chunk numbering with `[Trecho N]` and structured sections

### Results
Run `python -m src.evaluation.benchmark` to compare against the baseline.
Latest report: `data/benchmark_report.json`
