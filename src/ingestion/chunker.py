"""Text chunking utilities for compliance documents.

Splits extracted PDF pages into overlapping semantic chunks using
LangChain's RecursiveCharacterTextSplitter with regulatory-document-aware
separators (sections/articles, then paragraphs, then sentences).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.ingestion.pdf_loader import DocumentPage

# Lines that match any of these patterns are noise produced by browser-based
# PDF extraction (social media footers, cookie banners, timestamps, bare URLs).
_URL_LINE_RE = re.compile(r"^\s*<?https?://\S*>?\s*$")
_URL_FRAGMENT_RE = re.compile(r"^\s*[\w.-]+\.(com|gov|br|org|net)/\S*>?\s*$")
_ANGLE_CLOSE_RE = re.compile(r"^\s*\S+>\s*$")  # single token ending with >, e.g. "central-do-brasil>"
_TIMESTAMP_RE = re.compile(r"^\s*\d+/\d+/\d+,\s*\d+:\d+\s*[AP]M\s*$")
_PAGE_COUNTER_RE = re.compile(r"^\s*\d+/\d+\s*$")
_NOISE_LINE_STARTS = (
    "Siga o BC",
    "Usamos cookies",
    "Exibe Normativo",
    "Garantir a estabilidade",
    "Atendimento:",
    "Fale conosco",
    "© Banco Central",
    "expand_less",
    "expand_more",
    "Acessibilidade no Indeed",
    "BANCO CENTRAL DO BRASIL",
)


def clean_text(text: str) -> str:
    """Remove noise lines from extracted PDF text.

    Strips bare URLs, social media footers, cookie-consent banners,
    page timestamps, and browser-navigation headers that appear when
    PDF text is extracted from browser-rendered regulatory pages.

    Args:
        text: Raw extracted text, potentially containing noise lines.

    Returns:
        Cleaned text with noise lines removed, preserving legal content.
    """
    clean_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if _URL_LINE_RE.match(line):
            continue
        if _URL_FRAGMENT_RE.match(line):
            continue
        if _ANGLE_CLOSE_RE.match(line):
            continue
        if _TIMESTAMP_RE.match(line):
            continue
        if _PAGE_COUNTER_RE.match(line):
            continue
        if stripped.startswith(_NOISE_LINE_STARTS):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


@dataclass
class TextChunk:
    """A semantic chunk of text with source provenance."""

    content: str
    filename: str
    page_number: int
    title: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)


def chunk_pages(
    pages: List[DocumentPage],
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> List[TextChunk]:
    """Split document pages into overlapping text chunks.

    Uses hierarchical separators suited for regulatory documents:
    section breaks -> paragraph breaks -> newlines -> sentences -> words.

    Args:
        pages: List of DocumentPage objects to chunk.
        chunk_size: Target maximum characters per chunk.
        chunk_overlap: Number of overlapping characters between adjacent chunks.

    Returns:
        List of TextChunk objects preserving source metadata.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n\n", "\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )

    chunks: List[TextChunk] = []
    for page in pages:
        texts = splitter.split_text(clean_text(page.content))
        for i, text in enumerate(texts):
            if not text.strip():
                continue
            chunks.append(
                TextChunk(
                    content=text,
                    filename=page.filename,
                    page_number=page.page_number,
                    title=page.title,
                    chunk_index=i,
                    metadata={
                        **page.metadata,
                        "chunk_index": i,
                    },
                )
            )

    return chunks
