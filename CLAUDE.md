# ComplianceAgent — Project Guide for Claude

## What This Project Is

ComplianceAgent is a multi-agent RAG-based assistant for Brazilian financial compliance and regulation. It ingests PDF documents from the Brazilian Central Bank (BCB), CVM, and other regulatory bodies, processes them into a vector store, and answers questions with source citations.

**Target Audience:** AI Engineer / GenAI Engineer positions at Brazilian financial institutions (Banco BV, Neon, CashMe, CI&T, Radix, etc).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| LLM | Ollama (llama3:8b) — local, zero cost |
| LLM (alternate) | Anthropic Claude (claude-sonnet-4-6) — via `anthropic` SDK |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) — local |
| Reranking | cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 — multilingual, local |
| Vector Store | ChromaDB (file-based, persistent) |
| Database | SQLite (file: `data/compliance.db`) |
| API | FastAPI |
| Agent Framework | Custom implementation (no LangChain/LangGraph) |
| Auth | JWT (PyJWT + bcrypt), role-based (analyst / manager) |
| Frontend | Vanilla HTML/JS/CSS (no React framework) |
| HTTP client | httpx (async) |
| Containerization | Docker + Docker Compose |
| CI/CD | GitHub Actions (Python 3.11 + 3.13, 142 tests) |

## Project Phases

### Phase 1 — Basic RAG System [COMPLETE]

Functional RAG pipeline: ingest BCB PDFs → ChromaDB vector store → answer questions with citations.

```
PDF files → pdf_loader → chunker → embedder (ChromaDB)
Question  → query_engine (top-50 vector search → cross-encoder rerank to top-20) → prompt_builder → LLM
```

Modules:
- `src/config.py` — Pydantic Settings: paths, models, DB, Ollama, Claude, JWT config
- `src/ingestion/pdf_loader.py` — PyMuPDF PDF extraction → `DocumentPage` dataclasses
- `src/ingestion/chunker.py` — RecursiveCharacterTextSplitter chunking → `TextChunk` dataclasses
- `src/ingestion/embedder.py` — Sentence Transformers + ChromaDB indexing
- `src/retrieval/query_engine.py` — Similarity search (top-50) + multilingual cross-encoder reranking (top-20); small-doc bypass when ≤30 chunks
- `src/retrieval/prompt_builder.py` — Portuguese prompt assembly with citations and 6 anti-hallucination rules
- `src/llm/ollama_client.py` — Ollama HTTP client (async, full + streaming)
- `src/llm/claude_client.py` — Anthropic Claude client (async, full + streaming, prompt caching)
- `src/api/main.py` — FastAPI app with all routes and router includes
- `src/api/diagnostic.py` — `POST /diagnostic`: raw RAG inspection without LLM
- `src/api/templates/index.html` — Chat UI (vanilla JS, SSE streaming, conversation sidebar)

### Phase 2 — Multi-Agent System [COMPLETE]

Intent classification routes questions to specialized agents. No LLM call for routing — keyword classifier handles 95%+ of queries with zero latency.

```
User Question → CoordinatorAgent
    → keyword classifier (accent-insensitive)
        → KnowledgeAgent  (regulatory docs via RAG)
        → DataAgent        (NL→SQL→SQLite→NL interpretation)
        → ActionAgent      (create alerts, mark COAF reports, log actions)
        → KnowledgeAgent + DataAgent (combined regulatory+data queries)
```

Modules:
- `src/agents/base.py` — `AgentResponse` Pydantic model
- `src/agents/coordinator.py` — Routes via keyword heuristic; `_is_conversational()` guard; `process()` and `process_stream()` methods
- `src/agents/knowledge_agent.py` — Wraps Phase 1 RAG pipeline; `answer()` and `prepare()` methods
- `src/agents/data_agent.py` — NL→SQL→execute→NL-interpret against SQLite compliance.db
- `src/agents/action_agent.py` — Creates/updates alerts, marks COAF reports, logs actions
- `src/database/connection.py` — SQLite context-manager helper
- `src/database/setup.py` — DDL for all tables
- `src/database/seed.py` — 50 transactions, 5 alerts, 2 default users (analyst/manager)

SQLite tables (data/compliance.db):
- `users` — id, username, password_hash, full_name, role, created_at, last_login, is_active
- `transactions` — id, client_name, client_cpf, transaction_type, amount, date, branch, channel, reported_to_coaf, pep_flag, notes
- `alerts` — id, transaction_id, alert_type, severity, description, status, created_at, resolved_at
- `agent_log` — id, timestamp, agent_name, action, input_summary, output_summary, tokens_used
- `audit_log` — full LGPD audit record (see Phase 5)
- `governance_daily_stats` — daily aggregated PII/classification metrics
- `conversations` — id, user_id, title, created_at, updated_at, is_active
- `messages` — id, conversation_id, role, content, agent_used, provider, data_classification, pii_detected, timestamp

New API endpoints:
- `POST /agent` — Multi-agent routing (returns `CoordinatorResponse`)
- `GET /alerts?status=&severity=&date_from=&date_to=` — List compliance alerts with optional filters
- `GET /transactions?transaction_type=&amount_min=&amount_max=&date_from=&date_to=&reported_to_coaf=&pep_flag=` — List transactions

Example multi-agent queries:
```bash
# Data route
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"pergunta": "Quantas transações em espécie não foram reportadas ao COAF?"}'

# Knowledge route
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"pergunta": "Qual o prazo da Resolução CMN 5.274/2025?"}'

# Combined route (KNOWLEDGE+DATA)
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"pergunta": "Verifique se estamos em conformidade com o Art. 49 da Circular 3.978"}'

# Action route
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"pergunta": "Gere um relatório de alertas abertos"}'
```

### Phase 3 — Evaluation System [COMPLETE]

RAG quality evaluation using Claude as judge, batch benchmarking, and diagnostic inspection.

Modules:
- `src/api/evaluate.py` — `POST /evaluate` (Claude grader), `POST /test-pipeline` (Ollama vs Claude)
- `src/evaluation/benchmark.py` — Batch runner across 15 compliance test questions
- `src/evaluation/__init__.py`

`POST /diagnostic` — Inspects all three pipeline stages without calling the LLM. Returns:
- `busca_vetorial`: top-50 vector search candidates with cosine similarity scores
- `expansao_documento`: regulations detected in query, chunks fetched, dedup count, bypass flag
- `reranking`: cross-encoder results (null when bypassed for small documents)
- `chunks_enviados_ao_llm`: count of final chunks sent to LLM

`POST /evaluate` — Claude-as-judge with 5 criteria: `precisao_normativa`, `completude`, `relevancia_chunks`, `coerencia`, `alucinacao`. Returns `nota_geral` + `veredicto` (APROVADO ≥7.0 / REPROVADO <7.0).

`POST /test-pipeline` — Full pipeline: retrieve → Ollama → evaluate with Claude. Returns chunks, answer, evaluation, and `tempo_resposta_segundos`.

Benchmark runner:
```bash
python -m src.evaluation.benchmark          # all 15 questions (Ollama)
python -m src.evaluation.benchmark --provider claude
python -m src.evaluation.benchmark --compare  # side-by-side Ollama vs Claude
python -m src.evaluation.benchmark --limit 3  # first 3 only
```
Results saved to: `data/benchmark_ollama_YYYY-MM-DD.json`, `data/benchmark_claude_YYYY-MM-DD.json`, `data/benchmark_report.json`

### Phase 4 — Multi-LLM Support [COMPLETE]

Unified LLM router that all agents and endpoints use. Supports per-request provider switching.

```
API endpoint (provider="ollama"|"claude")
    → llm_router.generate(prompt, provider)
        → ollama_client.generate()   OR
        → claude_client.generate()
```

Modules:
- `src/llm/llm_router.py` — `generate(prompt, provider)` and `generate_stream(prompt, provider)`. Returns HTTP 503 if Claude requested without API key.

Switching providers:
```bash
# Per-request via API body
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer <token>" \
  -d '{"pergunta": "O que é PLD?", "provider": "claude"}'

# Default for all requests via env var
export LLM_PROVIDER=claude
uvicorn src.api.main:app --reload
```

Browser UI has an `OLLAMA | CLAUDE` toggle in the header.

### Phase 5 — LGPD Governance & Observability [COMPLETE]

Full LGPD compliance layer: PII detection/masking, audit logging with retention, governance dashboard.

```
Every CoordinatorAgent call →
    detect_pii(input + output)
    mask_text(FULL)
    audit.log_interaction() → audit_log table + governance_daily_stats upsert
    classify_query() → "public" | "internal" | "confidential" | "restricted"
    get_retention_expiry() → ISO date per Art. 23 of CMN 4.893
```

Modules:
- `src/governance/__init__.py`
- `src/governance/pii_detector.py` — Detects CPF, full names (Brazilian name list), high-value monetary amounts (≥R$10k), phone numbers, emails. `detect_pii()`, `mask_text()`, `has_pii()`, `count_pii()`. Accent-insensitive, multi-word name detection, overlap resolution.
- `src/governance/audit.py` — `generate_session_id()`, `classify_query()`, `get_retention_expiry()`, `log_interaction()` (async). Masks PII before storage; stores both original (null when PII present) and masked fields. Upserts `governance_daily_stats`.
- `src/governance/retention.py` — `purge_expired_pii()` (soft-purge, never deletes rows), `get_retention_report()`
- `src/api/governance.py` — LGPD dashboard API router at `/governance`
- `src/api/templates/dashboard.html` — Governance dashboard with Chart.js KPI cards, line chart, classification pie chart, audit log table

Governance API endpoints (all require `manager` role):
- `GET /governance/dashboard` — PII metrics, classification breakdown, retention alerts (last 30 days)
- `GET /governance/daily-stats` — Time-series data for line chart (last 30 days)
- `GET /governance/audit-log?limit=&offset=&agent=&has_pii=` — Paginated masked audit log
- `GET /governance/retention-report` — Retention status report
- `POST /governance/purge-expired` — Soft-purge PII records past retention date

Data classification rules:
- DataAgent + PII → `restricted`
- DataAgent without PII → `confidential`
- ActionAgent → `confidential`
- KnowledgeAgent → `public`

Retention periods (per Art. 23 CMN 4.893):
- `restricted` → 1 year (365 days)
- `confidential` → 2 years (730 days)
- `public`/`internal` → 5 years (1825 days)

### Phase 6 — JWT Authentication [COMPLETE]

Full JWT-based auth with role-based access control. All data endpoints require authentication.

```
POST /auth/login → JWT token (24h expiry)
Authorization: Bearer <token> → get_current_user() → TokenUser(user_id, username, role)
require_role("analyst", "manager") → FastAPI dependency
```

Modules:
- `src/api/auth.py` — `TokenUser`, `hash_password()`, `verify_password()`, `create_access_token()`, `get_current_user()`, `require_role()` (dependency factory)
- `src/api/auth_routes.py` — Auth router at `/auth`
- `src/api/templates/login.html` — Login page (redirects to chat UI on success)

Auth API endpoints:
- `POST /auth/login` — Returns `{"access_token": "...", "token_type": "bearer"}`
- `GET /auth/me` — Returns current user profile (all authenticated users)
- `POST /auth/register` — Create user (manager role only)
- `POST /auth/logout` — Stateless logout instruction

Role permissions:
- `analyst` — can chat, query agent, view documents, alerts, transactions, conversations
- `manager` — all analyst permissions + ingest PDFs, register users, view governance dashboard

Default seeded users: `analyst` / `analyst123` and `manager` / `manager123`

### Phase 7 — Conversation Memory [COMPLETE]

Persistent multi-turn conversation history with a collapsible sidebar.

```
User → POST /agent {conversation_id: N}
     → ConversationService.get_context_messages()  → last 10 msgs as history
     → ConversationService.add_message(user_msg)
     → CoordinatorAgent.process(conversation_history=history)
         → KnowledgeAgent.answer(conversation_history=history)
             → build_prompt(question, chunks, conversation_history=history)
     → ConversationService.add_message(assistant_msg)
```

Modules:
- `src/services/__init__.py`
- `src/services/conversation.py` — `ConversationService`: create, list_by_user, get_by_id, get_messages, add_message, update_title, delete (soft), get_context_messages (last 10 msgs), auto_title
- `src/api/conversation_routes.py` — CRUD router at `/conversations`

Conversation API endpoints (all require authentication, ownership enforced):
- `GET /conversations` — List user's conversations
- `POST /conversations` — Create conversation
- `GET /conversations/{id}` — Messages + metadata
- `DELETE /conversations/{id}` — Soft-delete
- `PATCH /conversations/{id}/title` — Rename

Frontend: 280px collapsible sidebar with date-grouped history, click-to-load, auto-title on first message, mobile hamburger toggle.

Context injection: last 10 messages fed into `build_prompt()` between system prompt and RAG chunks. RAG retrieval still uses current question only.

### Phase 8 — SSE Streaming [COMPLETE]

Token-by-token streaming via Server-Sent Events with thinking animation and route badge.

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
- `src/agents/knowledge_agent.py` → `prepare(question, conversation_history)` → `(prompt, chunks)`
- `src/agents/coordinator.py` → `process_stream(...)` — async generator

API endpoint:
- `POST /agent/stream` — Returns `text/event-stream` SSE; requires JWT; accepts `conversation_id`
- `POST /agent` — Unchanged, returns complete `CoordinatorResponse` JSON

Frontend: blinking gold cursor appears immediately on send; tokens render word-by-word; route badge appears on metadata event; source chips and SQL/action blocks appear after streaming completes; conversation sidebar refreshes after done.

### Phase 9 — Docker & CI/CD [COMPLETE]

One-command deployment and automated testing.

Files:
- `Dockerfile` — Python 3.11-slim, installs system deps (build-essential, gcc), copies code, runs `scripts/start.sh`
- `docker-compose.yml` — Two services: `app` (FastAPI) + `ollama` (Ollama server); named volumes for ChromaDB and Ollama models; `.env` mounted read-only
- `.dockerignore`
- `scripts/start.sh` — Startup script (DB init, model pull, uvicorn)
- `.github/workflows/ci.yml` — Runs pytest on Python 3.11 and 3.13 on push/PR to master/main; pip cache; excludes `tests/diagnose_rag.py`

```bash
# One-command startup
docker compose up --build

# API available at http://localhost:8000
# Ollama at http://localhost:11434
```

CI: 142 tests, all external services mocked (ChromaDB, Ollama, Anthropic).

## Architecture Decisions

- **Local-first:** Zero cloud dependency in default config. Ollama for LLM, sentence-transformers for embeddings, SQLite for data.
- **SQLite over PostgreSQL:** No server to manage. File-based, portable, sufficient for compliance demo data.
- **ChromaDB over Pinecone/Weaviate:** No API key, no network latency, portable.
- **Custom agent framework over LangChain:** No framework overhead. Coordinator+3 agents implemented directly with clear separation of concerns.
- **Keyword routing over LLM routing:** Keyword classifier handles 95%+ of queries with zero latency. LLM routing was removed after benchmarking showed it added 5+ seconds with no accuracy benefit.
- **Cross-encoder reranking:** Retrieves top-50, reranks to top-20. Better precision than pure vector search.
- **Reranker bypass:** When a named regulation has ≤30 chunks, all chunks are sent directly to the LLM (skipping reranking). Prevents over-compression of small documents.
- **Multilingual reranker:** Uses `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (trained on mMARCO multilingual data including Brazilian Portuguese). Switched from English-only `ms-marco-MiniLM-L-6-v2` after benchmark showed it discarded correct Portuguese chunks.
- **Portuguese prompts:** All system prompts, error messages, and API responses are in Brazilian Portuguese.
- **Pydantic Settings:** All config from environment variables with `.env` file support.
- **JWT stateless auth:** 24h tokens, bcrypt password hashing, role-based access via FastAPI dependency factory.
- **Soft-purge retention:** Audit records are never deleted. PII text fields are overwritten with `[DADO_EXPIRADO]`; metadata preserved for 5-year regulatory trail per CMN 4.893.
- **Vanilla frontend:** No build step, no npm. HTML + CSS + JS served directly by FastAPI as static HTML responses.

## Development Rules

- **NEVER use git worktrees.** Always work directly on `master` or create simple feature branches with `git checkout -b feature/xxx`. Worktrees cause environment fragmentation (missing `.env`, missing DB, missing indexed documents) and should not be used in this project.
- **Before pushing:** Run `python -m pytest tests/ --ignore=tests/diagnose_rag.py -v --tb=short` locally and confirm 0 failures.
- **diagnose_rag.py is excluded from CI:** It makes real Ollama/ChromaDB calls and is not a pytest test.

## CI/CD

GitHub Actions runs on every push to `master` and every pull request.

- **Workflow:** `.github/workflows/ci.yml`
- **What it does:** Runs `python -m pytest tests/ --ignore=tests/diagnose_rag.py -v --tb=short --timeout=60` on Python 3.11 and 3.13 with pip dependency caching
- **No secrets needed:** All config has safe defaults or Optional fallbacks; all external services (Ollama, ChromaDB, Anthropic) are mocked in tests
- **diagnose_rag.py is excluded:** It makes real Ollama/ChromaDB calls and is not a pytest test
- **Badge:** Add to README after setting up the GitHub remote: `![CI](https://github.com/YOUR_USER/YOUR_REPO/actions/workflows/ci.yml/badge.svg)`

## Coding Conventions

- **Type hints** on all function signatures and class attributes
- **Docstrings** on all public functions and classes (Google style)
- **Async** for all FastAPI endpoints and LLM clients
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
| src/llm/llm_router.py | ✅ Done |
| src/api/main.py | ✅ Done |
| src/api/auth.py | ✅ Done |
| src/api/auth_routes.py | ✅ Done |
| src/api/diagnostic.py | ✅ Done |
| src/api/evaluate.py | ✅ Done |
| src/api/governance.py | ✅ Done |
| src/api/conversation_routes.py | ✅ Done |
| src/api/templates/index.html | ✅ Done |
| src/api/templates/login.html | ✅ Done |
| src/api/templates/dashboard.html | ✅ Done |
| src/agents/base.py | ✅ Done |
| src/agents/coordinator.py | ✅ Done |
| src/agents/knowledge_agent.py | ✅ Done |
| src/agents/data_agent.py | ✅ Done |
| src/agents/action_agent.py | ✅ Done |
| src/database/connection.py | ✅ Done |
| src/database/setup.py | ✅ Done |
| src/database/seed.py | ✅ Done |
| src/governance/__init__.py | ✅ Done |
| src/governance/pii_detector.py | ✅ Done |
| src/governance/audit.py | ✅ Done |
| src/governance/retention.py | ✅ Done |
| src/services/__init__.py | ✅ Done |
| src/services/conversation.py | ✅ Done |
| src/evaluation/__init__.py | ✅ Done |
| src/evaluation/benchmark.py | ✅ Done |
| Dockerfile | ✅ Done |
| docker-compose.yml | ✅ Done |
| .dockerignore | ✅ Done |
| scripts/start.sh | ✅ Done |
| .github/workflows/ci.yml | ✅ Done |
| tests/test_api.py | ✅ Done |
| tests/test_agents.py | ✅ Done |
| tests/test_agent_provider.py | ✅ Done |
| tests/test_auth.py | ❌ Not yet written |
| tests/test_chunker.py | ✅ Done |
| tests/test_conversations.py | ✅ Done |
| tests/test_coordinator.py | ✅ Done |
| tests/test_database.py | ✅ Done |
| tests/test_embedder.py | ✅ Done |
| tests/test_llm_router.py | ✅ Done |
| tests/test_pdf_loader.py | ✅ Done |
| tests/test_query_engine.py | ✅ Done |
| tests/test_retrieval_fixes.py | ✅ Done |
| tests/test_streaming.py | ✅ Done |

## Running Locally

```bash
# Install deps
pip install -r requirements.txt

# Start Ollama separately (outside Docker for dev)
ollama serve
ollama pull llama3:8b

# Set Anthropic key for Claude features (optional)
export ANTHROPIC_API_KEY=sk-ant-...

# Start API
uvicorn src.api.main:app --reload

# Open browser
open http://localhost:8000/login
# Default credentials: analyst/analyst123 or manager/manager123

# Or use the API directly with a token:
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -d "username=analyst&password=analyst123" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"pergunta": "O que é política de conformidade?"}'

# Use Claude instead of Ollama for a single request:
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"pergunta": "O que é PLD?", "provider": "claude"}'

# Ingest PDFs (manager role required):
# Drop PDFs in data/raw/, then:
curl -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer $MANAGER_TOKEN"
```

## Docker Quick Start

```bash
# Build and start everything (FastAPI + Ollama)
docker compose up --build

# First run: pull the model (in a separate terminal)
docker compose exec ollama ollama pull llama3:8b

# API at http://localhost:8000
# Login at http://localhost:8000/login
# Governance dashboard at http://localhost:8000/dashboard (manager only)
```

Environment variables (`.env` file, mounted read-only into container):
```
ANTHROPIC_API_KEY=sk-ant-...   # optional, for Claude features
JWT_SECRET_KEY=your-secret     # change in production
LLM_PROVIDER=ollama            # or "claude"
```

## API Endpoints

All endpoints except `/`, `/login`, `/dashboard`, and `/auth/login` require `Authorization: Bearer <token>`.

### Auth
| Method | Path | Role | Description |
|--------|------|------|-------------|
| POST | /auth/login | — | Login, returns JWT token |
| GET | /auth/me | any | Current user profile |
| POST | /auth/register | manager | Create new user |
| POST | /auth/logout | any | Stateless logout |

### Chat & Agent
| Method | Path | Role | Description |
|--------|------|------|-------------|
| POST | /chat | analyst, manager | RAG answer with citations (no agent routing) |
| POST | /agent | analyst, manager | Multi-agent routing, full JSON response |
| POST | /agent/stream | analyst, manager | Multi-agent SSE streaming |

### Documents & Data
| Method | Path | Role | Description |
|--------|------|------|-------------|
| POST | /ingest | manager | Index PDFs from data/raw/ |
| GET | /documents | analyst, manager | List indexed documents |
| GET | /alerts | analyst, manager | Compliance alerts (filterable) |
| GET | /transactions | analyst, manager | Transaction list (filterable) |

### Conversations
| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | /conversations | analyst, manager | List user's conversations |
| POST | /conversations | analyst, manager | Create conversation |
| GET | /conversations/{id} | analyst, manager | Messages + metadata |
| DELETE | /conversations/{id} | analyst, manager | Soft-delete |
| PATCH | /conversations/{id}/title | analyst, manager | Rename |

### Governance (manager only)
| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | /governance/dashboard | manager | PII KPIs, classification breakdown, retention alerts |
| GET | /governance/daily-stats | manager | 30-day time-series for charts |
| GET | /governance/audit-log | manager | Paginated masked audit log |
| GET | /governance/retention-report | manager | Retention status report |
| POST | /governance/purge-expired | manager | Soft-purge PII past retention date |

### Diagnostic & Evaluation
| Method | Path | Role | Description |
|--------|------|------|-------------|
| POST | /diagnostic | any | RAG pipeline inspection without LLM |
| POST | /evaluate | any | Grade response with Claude as judge |
| POST | /test-pipeline | any | Run full pipeline + evaluate |

### Pages
| Method | Path | Description |
|--------|------|-------------|
| GET | / | Chat interface (index.html) |
| GET | /login | Login page |
| GET | /dashboard | Governance dashboard |

## Evaluation System

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
python -m src.evaluation.benchmark --provider claude
python -m src.evaluation.benchmark --compare  # Ollama vs Claude side-by-side
```

## Multi-LLM Support

ComplianceAgent supports two LLM backends for generation. The default is always Ollama (local, no cost). Claude is available for higher-quality demos and comparative benchmarking.

### Switching Providers

**Via API (per-request):**
```bash
# Chat endpoint with Claude
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "O que é PLD?", "provider": "claude"}'

# Agent endpoint with Claude
curl -X POST http://localhost:8000/agent \
  -H "Authorization: Bearer $TOKEN" \
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

`src/llm/llm_router.py` provides a unified `generate(prompt, provider)` and `generate_stream(prompt, provider)` interface used by all agents. Agents do not call `ollama_client` or `claude_client` directly.

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
