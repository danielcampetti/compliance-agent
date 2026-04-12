"""Benchmark runner — batch RAG quality evaluation across 15 compliance questions.

Usage:
    python -m src.evaluation.benchmark
    python -m src.evaluation.benchmark --limit 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

import anthropic

from src.config import settings
from src.llm import ollama_client
from src.retrieval.prompt_builder import build_prompt
from src.retrieval.query_engine import retrieve

_DATASET = Path(__file__).parent / "test_dataset.json"
_REPORT  = Path("data/benchmark_report.json")

_SYS = """\
Você é um avaliador especialista em compliance regulatório financeiro brasileiro.
Avalie respostas de um sistema RAG sobre normativos do Banco Central do Brasil.
Seja rigoroso, preciso e justo."""

_PROMPT = """\
## PERGUNTA
{pergunta}

## TRECHOS RECUPERADOS
{chunks}

## RESPOSTA GERADA
{resposta}

## RESPOSTA ESPERADA (referência)
{esperada}

Compare a resposta gerada com a esperada. Avalie em 5 critérios (0-10 cada).
JSON apenas, sem markdown:
{{"precisao_normativa":<0-10>,"completude":<0-10>,"relevancia_chunks":<0-10>,"coerencia":<0-10>,"alucinacao":<0-10>,"nota_geral":<média com 1 casa>,"analise":"<breve parágrafo>","problemas_identificados":[],"sugestoes_melhoria":[],"veredicto":"<APROVADO se >= 7.0, REPROVADO se < 7.0>"}}"""


async def _evaluate_one(
    pergunta: str,
    resposta: str,
    chunks_text: list[str],
    resposta_esperada: str,
    api_key: str,
) -> dict:
    prompt = _PROMPT.format(
        pergunta=pergunta,
        chunks="\n\n".join(f"[{i+1}] {t}" for i, t in enumerate(chunks_text)),
        resposta=resposta,
        esperada=resposta_esperada,
    )
    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=[{"type": "text", "text": _SYS, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group()) if m else {
            "nota_geral": 0.0, "veredicto": "ERRO", "analise": raw[:200],
            "precisao_normativa": 0.0, "completude": 0.0,
            "relevancia_chunks": 0.0, "coerencia": 0.0, "alucinacao": 0.0,
            "problemas_identificados": [], "sugestoes_melhoria": [],
        }


async def run_benchmark(limit: int | None = None) -> None:
    api_key = settings.anthropic_api_key
    if not api_key:
        print("ERRO: ANTHROPIC_API_KEY não configurado. Benchmark requer acesso ao Claude.")
        return

    dataset = json.loads(_DATASET.read_text(encoding="utf-8"))
    if limit:
        dataset = dataset[:limit]

    total = len(dataset)
    results: list[dict] = []
    t_start = time.monotonic()

    print(f"\n  Iniciando benchmark: {total} questões...\n")

    for item in dataset:
        qid      = item["id"]
        pergunta = item["pergunta"]
        esperada = item["resposta_esperada"]
        categoria = item.get("categoria", "geral")

        try:
            chunks = retrieve(pergunta)
            if not chunks:
                raise RuntimeError("Nenhum chunk recuperado — execute /ingest primeiro")
            prompt   = build_prompt(pergunta, chunks)
            resposta = await ollama_client.generate(prompt)
            scores   = await _evaluate_one(
                pergunta, resposta, [c.content for c in chunks], esperada, api_key
            )
        except Exception as exc:
            print(f"  ✗ #{qid} ERRO: {exc}")
            results.append({
                "id": qid, "categoria": categoria, "pergunta": pergunta,
                "nota_geral": 0.0, "veredicto": "ERRO", "scores": {}, "elapsed": 0.0,
            })
            continue

        nota     = float(scores.get("nota_geral", 0.0))
        veredicto = scores.get("veredicto", "REPROVADO")
        symbol   = "✓" if veredicto == "APROVADO" else "✗"
        print(f"  {symbol} #{qid:<2} [{categoria[:4]}] nota={nota:.1f}")

        results.append({
            "id": qid, "categoria": categoria, "pergunta": pergunta,
            "nota_geral": nota, "veredicto": veredicto, "scores": scores, "elapsed": 0.0,
        })

    total_time = round(time.monotonic() - t_start, 1)

    # ── Summary ──────────────────────────────────────────────────────────────
    valid  = [r for r in results if r["veredicto"] not in ("ERRO",)]
    passed = [r for r in valid if r["veredicto"] == "APROVADO"]

    criteria = ["precisao_normativa", "completude", "relevancia_chunks", "coerencia", "alucinacao"]
    avgs: dict[str, float] = {}
    for c in criteria:
        vals = [float(r["scores"].get(c, 0.0)) for r in valid if r.get("scores")]
        avgs[c] = round(sum(vals) / len(vals), 1) if vals else 0.0

    avg_geral = round(sum(r["nota_geral"] for r in valid) / max(len(valid), 1), 1)

    by_cat: dict[str, list] = {}
    for r in valid:
        by_cat.setdefault(r["categoria"], []).append(r)

    W = 57
    print(f"\n{'═'*W}")
    print("  ComplianceAgent — Benchmark Report")
    print(f"  Data: {datetime.now().strftime('%Y-%m-%d')} | Modelo: {settings.ollama_model} | Questões: {total}")
    print(f"{'═'*W}\n")
    print(f"  Resultados:  {len(passed)}/{total} APROVADOS ({round(len(passed)/max(total,1)*100)}%)\n")

    labels = {
        "precisao_normativa": "Precisão Normativa ",
        "completude":         "Completude         ",
        "relevancia_chunks":  "Relevância Chunks  ",
        "coerencia":          "Coerência          ",
        "alucinacao":         "Alucinação         ",
    }
    print("  ┌─────────────────────┬───────┐")
    print("  │ Critério            │ Média │")
    print("  ├─────────────────────┼───────┤")
    for c, label in labels.items():
        print(f"  │ {label}│ {avgs[c]:<5.1f} │")
    print("  ├─────────────────────┼───────┤")
    print(f"  │ MÉDIA GERAL         │ {avg_geral:<5.1f} │")
    print("  └─────────────────────┴───────┘\n")

    if by_cat:
        print("  Por Categoria:")
        for cat, items in sorted(by_cat.items()):
            cat_avg  = round(sum(r["nota_geral"] for r in items) / len(items), 1)
            cat_pass = sum(1 for r in items if r["veredicto"] == "APROVADO")
            print(f"  - {cat:<32} {cat_avg} avg ({cat_pass}/{len(items)} aprovados)")

    failed = [r for r in valid if r["veredicto"] == "REPROVADO"]
    if failed:
        print(f"\n  Reprovados:")
        for r in sorted(failed, key=lambda x: x["nota_geral"]):
            preview = r["pergunta"][:55] + "..."
            print(f"  ✗ #{r['id']:<2} \"{preview}\" — {r['nota_geral']:.1f}")

    avg_time = round(total_time / max(total, 1), 1)
    print(f"\n  Tempo: {total_time}s total | {avg_time}s médio por questão")
    print(f"\n{'═'*W}\n")

    # ── Save report ───────────────────────────────────────────────────────────
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "date": datetime.now().isoformat(),
        "model": settings.ollama_model,
        "total_questions": total,
        "passed": len(passed),
        "failed": len(failed),
        "avg_scores": avgs,
        "avg_geral": avg_geral,
        "total_time_seconds": total_time,
        "results": results,
    }
    _REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  Relatório salvo em: {_REPORT}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ComplianceAgent Benchmark Runner")
    parser.add_argument("--limit", type=int, default=None, help="Limitar a N questões")
    args = parser.parse_args()
    asyncio.run(run_benchmark(limit=args.limit))
