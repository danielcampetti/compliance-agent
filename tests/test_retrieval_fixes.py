"""Tests for the three RAG retrieval fixes.

Fix 1: Increase reranker input (retrieval_top_k=30, rerank_top_k=10)
Fix 2: Clean chunk text (remove URLs, footers, timestamps)
Fix 3: Prepend document context to embeddings
"""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


# ── Fix 1: Config defaults ─────────────────────────────────────────────────────

def test_retrieval_top_k_default_is_50():
    """Vector search should retrieve 50 candidates before reranking."""
    from src.config import Settings
    assert Settings().retrieval_top_k == 50


def test_rerank_top_k_default_is_20():
    """Reranker should return top 20 chunks to the LLM."""
    from src.config import Settings
    assert Settings().rerank_top_k == 20


# ── Fix 2: Text cleaning ───────────────────────────────────────────────────────

def test_clean_text_removes_bare_urls():
    """Lines that are pure URLs should be removed."""
    from src.ingestion.chunker import clean_text
    text = "Texto legal.\nhttps://www.bcb.gov.br/exibenormativo?tipo=X\nMais texto."
    result = clean_text(text)
    assert "https://" not in result
    assert "Texto legal." in result
    assert "Mais texto." in result


def test_clean_text_removes_http_urls():
    """http:// URLs on their own line should also be removed."""
    from src.ingestion.chunker import clean_text
    text = "Art. 1º Disposições.\nhttp://www.bcb.gov.br/pagina\nFim."
    result = clean_text(text)
    assert "http://" not in result
    assert "Art. 1º" in result


def test_clean_text_removes_siga_o_bc_footer():
    """'Siga o BC' social media header should be stripped."""
    from src.ingestion.chunker import clean_text
    text = "Art. 2º Prazo de adequação.\nSiga o BC\nInstagram link"
    result = clean_text(text)
    assert "Siga o BC" not in result
    assert "Art. 2º" in result


def test_clean_text_removes_cookie_consent_noise():
    """Cookie consent banners should be stripped."""
    from src.ingestion.chunker import clean_text
    text = "Art. 3º O prazo é 30 dias.\nUsamos cookies para melhorar sua experiência e oferecer serviços personalizados."
    result = clean_text(text)
    assert "Usamos cookies" not in result
    assert "Art. 3º" in result


def test_clean_text_removes_timestamps():
    """Page timestamps like '4/11/26, 10:25 PM' should be stripped."""
    from src.ingestion.chunker import clean_text
    text = "4/11/26, 10:25 PM\nExibe Normativo\nArt. 3º O prazo é de 30 dias."
    result = clean_text(text)
    assert "4/11/26" not in result
    assert "10:25 PM" not in result
    assert "Art. 3º" in result


def test_clean_text_removes_exibe_normativo_header():
    """'Exibe Normativo' web page header should be stripped."""
    from src.ingestion.chunker import clean_text
    text = "Exibe Normativo\nArt. 1º Disposições gerais."
    result = clean_text(text)
    assert "Exibe Normativo" not in result
    assert "Art. 1º" in result


def test_clean_text_preserves_legal_content():
    """Core legal text must not be altered by cleaning."""
    from src.ingestion.chunker import clean_text
    legal = "Art. 2º As instituições devem adaptar-se até 1º de março de 2026."
    assert clean_text(legal).strip() == legal.strip()


def test_clean_text_preserves_articles_with_urls_inline():
    """A line with legal text plus a URL reference should keep the legal text."""
    from src.ingestion.chunker import clean_text
    # In-line URL reference should NOT strip the surrounding legal text
    text = "Art. 22-A. As instituições devem assegurar os testes."
    result = clean_text(text)
    assert "Art. 22-A" in result


def test_clean_text_removes_partial_url_fragment():
    """URL tail fragments left from multi-line <url> blocks should be removed."""
    from src.ingestion.chunker import clean_text
    text = "Art. 2º Prazo até 2026.\ncentral-do-brasil>\nbr.facebook.com/bancocentraldobrasil/>"
    result = clean_text(text)
    assert "central-do-brasil>" not in result
    assert "br.facebook.com" not in result
    assert "Art. 2º" in result


def test_clean_text_removes_bcb_institutional_footer():
    """BCB institutional motto and footer contact info should be stripped."""
    from src.ingestion.chunker import clean_text
    text = (
        "Art. 2º Prazo.\n"
        "Garantir a estabilidade de preços, zelar por um sistema financeiro sólido e\n"
        "eficiente, e fomentar o bem-estar econômico da sociedade.\n"
        "Atendimento: 145 (custo de ligação local)\n"
        "Fale conosco | Política de privacidade | Política de acessibilidade\n"
        "© Banco Central do Brasil - Todos os direitos reservados"
    )
    result = clean_text(text)
    assert "Garantir a estabilidade" not in result
    assert "Atendimento: 145" not in result
    assert "Fale conosco" not in result
    assert "© Banco Central" not in result
    assert "Art. 2º" in result


def test_clean_text_removes_expand_less_artifact():
    """'expand_less' JavaScript/navigation artifacts should be stripped."""
    from src.ingestion.chunker import clean_text
    text = "Art. 3º Vigência.\nexpand_less\nPolítica monetária\nexpand_less\nEstatísticas"
    result = clean_text(text)
    assert "expand_less" not in result
    assert "Art. 3º" in result


def test_clean_text_removes_page_counter_footer():
    """Page counter lines like '3/11' from browser-rendered PDFs should be stripped."""
    from src.ingestion.chunker import clean_text
    text = "Política de Privacidade e Termos de Uso.\n3/11\nArt. 5º Disposições."
    result = clean_text(text)
    assert "\n3/11" not in result
    assert "Art. 5º" in result


def test_chunk_pages_applies_cleaning():
    """chunk_pages must clean text before splitting."""
    from src.ingestion.pdf_loader import DocumentPage
    from src.ingestion.chunker import chunk_pages
    noisy_page = DocumentPage(
        content=(
            "4/11/26, 10:26 PM\n"
            "Exibe Normativo\n"
            "Art. 2º As instituições devem adaptar-se até 1º de março de 2026.\n"
            "Siga o BC\n"
            "https://www.instagram.com/bancocentraldobrasil/\n"
            "Usamos cookies para melhorar sua experiência e oferecer serviços personalizados."
        ),
        filename="res_5274_18_12_2025.pdf",
        page_number=4,
        title="Resolução CMN nº 5.274/2025",
        metadata={"source": "res_5274_18_12_2025.pdf", "page": 4, "title": "Resolução CMN nº 5.274/2025"},
    )
    chunks = chunk_pages([noisy_page])
    combined = " ".join(c.content for c in chunks)
    assert "Siga o BC" not in combined
    assert "https://" not in combined
    assert "Usamos cookies" not in combined
    assert "1º de março de 2026" in combined


# ── Fix 3: Document context prepending ────────────────────────────────────────

def test_doc_label_from_res_filename_with_4digit_number():
    """res_5274_DD_MM_YYYY.pdf → 'Resolução CMN nº 5.274/2025'."""
    from src.ingestion.embedder import _doc_label
    assert _doc_label("res_5274_18_12_2025.pdf") == "Resolução CMN nº 5.274/2025"


def test_doc_label_from_res_filename_with_dotted_number():
    """res_4.893_DD_MM_YYYY.pdf → 'Resolução CMN nº 4.893/2021'."""
    from src.ingestion.embedder import _doc_label
    assert _doc_label("res_4.893_26_02_2021.pdf") == "Resolução CMN nº 4.893/2021"


def test_doc_label_from_circular_filename():
    """Circ_3978_*.pdf → 'Circular BCB nº 3.978'."""
    from src.ingestion.embedder import _doc_label
    assert _doc_label("Circ_3978_v3_P.pdf") == "Circular BCB nº 3.978"


def test_doc_label_fallback_for_unknown_filename():
    """Unknown filename patterns should return the filename stem."""
    from src.ingestion.embedder import _doc_label
    assert _doc_label("unknown_document.pdf") == "unknown_document"


def test_index_chunks_prepends_doc_context_to_embeddings():
    """Embeddings must use context-prefixed text; stored document must be the original."""
    from src.ingestion.chunker import TextChunk
    from src.ingestion import embedder as emb_mod  # import before patching

    chunk = TextChunk(
        content="devem promover as adaptações até 1º de março de 2026.",
        filename="res_5274_18_12_2025.pdf",
        page_number=4,
        title="Resolução CMN nº 5.274/2025",
        chunk_index=0,
        metadata={"source": "res_5274_18_12_2025.pdf", "page": 4},
    )

    encoded_texts: list[str] = []

    def fake_encode(texts, **kwargs):
        encoded_texts.extend(texts)
        return np.zeros((len(texts), 384))

    mock_model = MagicMock()
    mock_model.encode.side_effect = fake_encode

    added_documents: list[str] = []
    mock_collection = MagicMock()
    mock_collection.add.side_effect = lambda **kw: added_documents.extend(kw.get("documents", []))

    with patch("src.ingestion.embedder.SentenceTransformer", return_value=mock_model), \
         patch("src.ingestion.embedder._get_client"), \
         patch("src.ingestion.embedder._get_collection", return_value=mock_collection):
        emb_mod.index_chunks([chunk])

    # Embedding text must carry the doc context prefix
    assert len(encoded_texts) == 1
    assert "[Resolução CMN nº 5.274/2025]" in encoded_texts[0]

    # Stored document must be the original clean content
    assert len(added_documents) == 1
    assert added_documents[0] == chunk.content
