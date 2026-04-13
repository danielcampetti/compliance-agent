# ComplianceAgent

![CI](https://github.com/danielcampetti/compliance-agent/actions/workflows/ci.yml/badge.svg)

Sistema RAG para compliance e regulamentacao financeira brasileira.
Ingere PDFs do Banco Central do Brasil (BCB), CVM e outros orgaos regulatorios, indexa em um banco vetorial e responde perguntas com citacoes das fontes.

## Pre-requisitos

- Docker + Docker Compose
- NVIDIA GPU com nvidia-container-toolkit (opcional, mas recomendado)
- PDFs regulatorios adicionados em `data/raw/`

## Inicio Rapido (Docker)

```bash
# 1. Clonar o repositorio
git clone <repo-url>
cd compliance-agent

# 2. Copiar variaveis de ambiente
cp .env.example .env

# 3. Subir os servicos
docker-compose up -d

# 4. Baixar o modelo LLM (execute uma vez)
docker exec -it compliance-agent-ollama-1 ollama pull llama3:8b

# 5. Adicionar PDFs em data/raw/ e indexar
curl -X POST http://localhost:8000/ingest

# 6. Fazer uma pergunta
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "O que e politica de conformidade segundo a CMN 4.968?"}'
```

## Desenvolvimento Local (sem Docker)

```bash
pip install -r requirements.txt

# Iniciar Ollama localmente
ollama serve
ollama pull llama3:8b

# Iniciar a API
uvicorn src.api.main:app --reload

# Rodar os testes
python -m pytest --tb=short -v
```

## Endpoints da API

| Metodo | Rota | Descricao |
|--------|------|-----------|
| POST | `/ingest` | Indexa todos os PDFs em `data/raw/` |
| POST | `/chat` | Responde uma pergunta com citacoes de fontes |
| GET | `/documents` | Lista todos os documentos indexados |
| GET | `/docs` | Documentacao interativa (Swagger UI) |

### Exemplo: POST /chat

**Request:**
```json
{
  "pergunta": "Quais sao as obrigacoes de gerenciamento de riscos ciberneticos?"
}
```

**Response:**
```json
{
  "resposta": "De acordo com a Resolucao BCB no 338, as instituicoes...",
  "fontes": [
    {
      "arquivo": "resolucao_bcb_338.pdf",
      "pagina": 4,
      "score": 0.9231
    }
  ]
}
```

## Documentos de Exemplo

Baixe em [bcb.gov.br/estabilidadefinanceira/buscanormas](https://www.bcb.gov.br/estabilidadefinanceira/buscanormas):

| Documento | Tema |
|-----------|------|
| Resolucao BCB no 338 | Politica de ciberseguranca |
| Resolucao CMN no 4.968 | Politica de conformidade (compliance) |
| Circular BCB no 3.978 | Prevencao a lavagem de dinheiro (PLD/FT) |

## Arquitetura (Fase 1)

```
PDFs → PyMuPDF → RecursiveTextSplitter → SentenceTransformers → ChromaDB
                                                                     ↓
Pergunta → embed → vector search (top-20) → cross-encoder rerank (top-5)
                                                                     ↓
                                              Prompt (PT-BR) → Ollama → Resposta
```

## Fases do Projeto

| Fase | Descricao | Status |
|------|-----------|--------|
| 1 | Pipeline RAG basico — ingestion, vector store, API REST | Implementado |
| 2 | Sistema multi-agente com MCP (LangGraph) | Futuro |
| 3 | Frontend React + streaming SSE | Futuro |
| 4 | Governanca LGPD, evals automatizados, CI/CD | Futuro |

## Stack Tecnologica

- **LLM:** Ollama (llama3:8b) — local, zero custo
- **Embeddings:** sentence-transformers (all-MiniLM-L6-v2) — local
- **Reranking:** cross-encoder/ms-marco-MiniLM-L-6-v2 — local
- **Vector Store:** ChromaDB (persistido em disco)
- **API:** FastAPI + uvicorn
- **Testes:** pytest (23 testes unitarios)
- **Infraestrutura:** Docker + Docker Compose (suporte GPU NVIDIA)
