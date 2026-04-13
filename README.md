# ComplianceAgent 🏛️

![CI](https://github.com/danielcampetti/compliance-agent/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/Tests-142%20passing-brightgreen)

**Sistema multi-agente de compliance financeiro com RAG, LGPD e streaming em tempo real.**

Assistente inteligente que ingere normativos do Banco Central (BCB), CVM e CMN, processa em banco vetorial, e responde perguntas com citações precisas das fontes — orquestrando múltiplos agentes especializados para análise regulatória, consulta de dados e ações automatizadas.

---

## 📸 Screenshots

> Screenshots serão adicionados em breve. O sistema inclui:
> - Tela de login com autenticação JWT
> - Chat com streaming em tempo real (token por token)
> - Sidebar de histórico de conversas com agrupamento por data
> - Dashboard de governança com gráficos Chart.js
> - Badges de classificação LGPD (público / confidencial / restrito)

---

## 🎯 O que este projeto demonstra

| Competência | Implementação |
|-------------|--------------|
| RAG avançado | Reranking multilingual, document-aware retrieval, prompt anti-alucinação |
| Agentes autônomos | 4 agentes especializados + coordenador com roteamento por keywords |
| Multi-LLM sem lock-in | Ollama + Claude API com toggle, benchmark comparativo |
| LGPD / Governança | Detecção de PII, mascaramento, audit trail, retenção, dashboard |
| Avaliação sistemática (Evals) | 15 perguntas-teste, Claude como juiz, 5 critérios |
| SSE Streaming | Respostas token-por-token em tempo real |
| Autenticação JWT | Roles (analyst/manager), controle de acesso por endpoint |
| Memória conversacional | Histórico persistente, contexto injetado no prompt |
| Docker + CI/CD | Dockerfile, docker-compose, GitHub Actions (142 testes) |
| FastAPI + Python | API REST async, SSE streaming, Pydantic models |

---

## 🏗️ Arquitetura

```
┌─────────────┐     ┌──────────────────────────────────────────────────────┐
│   Frontend   │     │                      Backend                         │
│  (HTML/JS)   │────▶│                                                      │
│              │ SSE │  ┌─────────────┐    ┌──────────────────────────┐     │
│ • Login      │◀────│  │  FastAPI    │    │    CoordinatorAgent       │     │
│ • Chat+Stream│     │  │  + JWT Auth │───▶│   (keyword routing)      │     │
│ • Sidebar    │     │  └─────────────┘    └────────┬──────┬──────┬───┘     │
│ • Dashboard  │     │                              │      │      │         │
└─────────────┘     │                     ┌────────┘      │      └───────┐ │
                    │                     ▼               ▼              ▼ │
                    │              ┌────────────┐  ┌──────────┐  ┌─────────┐│
                    │              │ Knowledge  │  │  Data    │  │ Action  ││
                    │              │   Agent    │  │  Agent   │  │  Agent  ││
                    │              └──────┬─────┘  └────┬─────┘  └────┬────┘│
                    │                    │              │              │    │
                    │              ┌─────┴──────┐  ┌───┴────┐  ┌─────┴───┐ │
                    │              │  ChromaDB  │  │ SQLite │  │ SQLite  │ │
                    │              │ (vetores)  │  │ (dados)│  │(ações)  │ │
                    │              └────────────┘  └────────┘  └─────────┘ │
                    │                                                       │
                    │  ┌───────────────────────────────────────────────┐   │
                    │  │              Governança LGPD                   │   │
                    │  │  PII Detector → Audit Log → Retention Manager │   │
                    │  └───────────────────────────────────────────────┘   │
                    └───────────────────────────────────────────────────────┘
```

---

## ✨ Funcionalidades

### Pipeline RAG
- Ingestão de PDFs com PyMuPDF
- Chunking semântico com RecursiveCharacterTextSplitter
- Embeddings com Sentence Transformers (all-MiniLM-L6-v2)
- Busca vetorial ChromaDB (top-50) + reranking multilingual cross-encoder (top-20)
- Bypass de reranker para documentos pequenos (≤30 chunks)
- Prompt em português com 6 regras anti-alucinação

### Sistema Multi-Agente
- **KnowledgeAgent** — consulta regulatória via RAG + histórico de conversa
- **DataAgent** — NL→SQL sobre transações e alertas no SQLite
- **ActionAgent** — cria alertas, marca reportes ao COAF, loga ações
- **CoordinatorAgent** — roteamento por keywords accent-insensitive (zero latência de LLM)

### Streaming em Tempo Real (SSE)
- Tokens aparecem palavra por palavra via `POST /agent/stream`
- Animação "Analisando pergunta..." durante classificação
- Badges de rota, fontes e SQL exibidos ao finalizar

### Governança LGPD
- Detecção automática de PII: CPF, nomes brasileiros, valores ≥R$10k, telefone, email
- Mascaramento parcial (exibição) e total (armazenamento em logs)
- Audit trail com classificação: público / interno / confidencial / restrito
- Retenção automática com purge suave (Art. 23 CMN 4.893)
- Dashboard visual com KPIs, linha de tendência e tabela de audit log

### Autenticação e Autorização
- JWT 24h com roles: `analyst` (chat) e `manager` (chat + governança + ingestão)
- Login page, auth guard, `require_role()` como dependency FastAPI

### Memória Conversacional
- Sidebar com histórico agrupado por data
- Últimas 10 mensagens injetadas no contexto do LLM
- Auto-título gerado na primeira mensagem da conversa

### Avaliação e Benchmark
- Claude como juiz automático com 5 critérios de compliance
- Benchmark de 15 perguntas com relatório JSON
- Comparação Ollama vs Claude lado a lado (`--compare`)
- Diagnóstico do pipeline RAG sem chamar LLM (`POST /diagnostic`)

---

## 🛠️ Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python 3.11+ |
| LLM local | Ollama (llama3:8b) |
| LLM cloud | Claude Sonnet (anthropic SDK) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Reranking | cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 (multilingual) |
| Banco vetorial | ChromaDB |
| Banco de dados | SQLite |
| API | FastAPI + uvicorn |
| Auth | PyJWT + bcrypt |
| Frontend | HTML/JS/CSS (vanilla) + Chart.js |
| HTTP assíncrono | httpx |
| Container | Docker + Docker Compose |
| CI/CD | GitHub Actions (Python 3.11 + 3.13) |
| Testes | pytest (142 testes) |

---

## 🚀 Início Rápido (Docker)

```bash
# 1. Clonar o repositório
git clone https://github.com/danielcampetti/compliance-agent.git
cd compliance-agent

# 2. Configurar variáveis de ambiente
cp .env.example .env
# Edite .env — ANTHROPIC_API_KEY é opcional (necessário apenas para o provider Claude)

# 3. Adicionar PDFs regulatórios em data/raw/
# Baixe em https://www.bcb.gov.br e coloque os PDFs na pasta data/raw/

# 4. Subir tudo
docker compose up --build
```

O primeiro start baixa o modelo LLM (~4.7GB). Starts seguintes são rápidos.

Acesse **http://localhost:8000/login** — credenciais padrão: `analyst` / `analyst123` ou `manager` / `manager123`

> **Ingestão de PDFs** requer role `manager`. Após login como manager, acesse `POST /ingest`.

### Suporte a GPU (Opcional)

Se você tiver GPU NVIDIA com [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), descomente a seção `deploy.resources` em `docker-compose.yml`.

---

## 💻 Desenvolvimento Local (sem Docker)

```bash
pip install -r requirements.txt

# Iniciar Ollama localmente
ollama serve
ollama pull llama3:8b

# (Opcional) Chave Claude para features de avaliação
export ANTHROPIC_API_KEY=sk-ant-...

# Iniciar a API
uvicorn src.api.main:app --reload

# Abrir no browser
open http://localhost:8000/login

# Rodar os testes
python -m pytest tests/ --ignore=tests/diagnose_rag.py --tb=short -v
```

---

## 🔌 Endpoints da API

Todos os endpoints (exceto `/login`, `/auth/login`, e páginas estáticas) exigem `Authorization: Bearer <token>`.

### Auth
| Método | Rota | Role | Descrição |
|--------|------|------|-----------|
| POST | `/auth/login` | — | Login, retorna token JWT |
| GET | `/auth/me` | qualquer | Perfil do usuário atual |
| POST | `/auth/register` | manager | Criar novo usuário |
| POST | `/auth/logout` | qualquer | Logout stateless |

### Chat & Agente
| Método | Rota | Role | Descrição |
|--------|------|------|-----------|
| POST | `/chat` | analyst, manager | Resposta RAG com citações |
| POST | `/agent` | analyst, manager | Roteamento multi-agente, JSON completo |
| POST | `/agent/stream` | analyst, manager | Roteamento multi-agente, SSE streaming |

### Documentos & Dados
| Método | Rota | Role | Descrição |
|--------|------|------|-----------|
| POST | `/ingest` | manager | Indexar PDFs de `data/raw/` |
| GET | `/documents` | analyst, manager | Listar documentos indexados |
| GET | `/alerts` | analyst, manager | Alertas de compliance (filtrável) |
| GET | `/transactions` | analyst, manager | Lista de transações (filtrável) |

### Conversas
| Método | Rota | Role | Descrição |
|--------|------|------|-----------|
| GET | `/conversations` | analyst, manager | Listar conversas do usuário |
| POST | `/conversations` | analyst, manager | Criar conversa |
| GET | `/conversations/{id}` | analyst, manager | Mensagens + metadados |
| DELETE | `/conversations/{id}` | analyst, manager | Soft-delete |
| PATCH | `/conversations/{id}/title` | analyst, manager | Renomear |

### Governança (manager)
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/governance/dashboard` | KPIs de PII, classificação, alertas de retenção |
| GET | `/governance/daily-stats` | Série temporal de 30 dias para gráficos |
| GET | `/governance/audit-log` | Log de auditoria paginado (campos mascarados) |
| GET | `/governance/retention-report` | Relatório de status de retenção |
| POST | `/governance/purge-expired` | Purge suave de PII vencido |

### Diagnóstico & Avaliação
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/diagnostic` | Inspeção do pipeline RAG sem chamar LLM |
| POST | `/evaluate` | Avaliar resposta com Claude como juiz |
| POST | `/test-pipeline` | Pipeline completo + avaliação |

---

## 📊 Resultados do Benchmark

Mesmo pipeline RAG — mesmos chunks, mesmo retrieval, mesmo reranker. Diferença 100% na capacidade do modelo de interpretar português jurídico.

| Métrica | Ollama (llama3:8b) | Claude Sonnet |
|---------|:-----------------:|:-------------:|
| Aprovados | 3/15 (20%) | **15/15 (100%)** |
| Nota Geral | 3.7 | **9.7** |
| Precisão Normativa | 2.9 | **9.8** |
| Completude | 2.7 | **9.7** |
| Relevância dos Chunks | 3.5 | **9.9** |
| Coerência | 4.3 | **9.8** |
| Alucinação (10 = zero) | 5.3 | **9.5** |
| Custo | $0.00 | ~$0.34 |

```bash
# Reproduzir o benchmark
python -m src.evaluation.benchmark --compare --limit 3
```

---

## 📁 Estrutura do Projeto

```
compliance-agent/
├── src/
│   ├── agents/          # Multi-agent: coordinator, knowledge, data, action
│   ├── api/             # FastAPI: rotas, auth, governança, templates HTML
│   ├── database/        # SQLite: setup, connection, seed data
│   ├── evaluation/      # Benchmark runner, dataset de 15 perguntas
│   ├── governance/      # PII detector, audit logging, retention manager
│   ├── ingestion/       # PDF loading, chunking, embedding
│   ├── llm/             # LLM router, Ollama client, Claude client
│   ├── retrieval/       # Query engine (reranking), prompt builder
│   └── services/        # Conversation memory service
├── tests/               # 142 pytest tests (todos com mocks externos)
├── data/raw/            # PDFs regulatórios (não versionados)
├── scripts/start.sh     # Script de startup Docker
├── Dockerfile
├── docker-compose.yml
└── CLAUDE.md            # Documentação técnica completa do projeto
```

---

## 📄 Licença

MIT

## 👤 Autor

Daniel Campetti — Engenheiro Mecânico (UnB) | AI Engineer
