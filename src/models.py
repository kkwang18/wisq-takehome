from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocMeta:
    file: str
    doc_type: str  # "global_handbook" | "regional_handbook"
    jurisdictions: list[str] | None
    version_year: int | None
    display_name: str
    # Section headings (exact match to Chunk.section_title) where chunk_document() should
    # split paragraphs into one chunk per sentence instead of one chunk per paragraph. A
    # deliberate, per-document, per-section opt-in — not a corpus-wide default — see
    # src/chunking.py and CLAUDE.md's chunking decisions for why.
    split_sentences_in_sections: list[str] | None = None


@dataclass(frozen=True)
class Paragraph:
    text: str
    style: str | None


@dataclass(frozen=True)
class Chunk:
    text: str
    section_title: str
    doc: DocMeta


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
