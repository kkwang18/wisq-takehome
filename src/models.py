from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocMeta:
    file: str
    doc_type: str  # "global_handbook" | "regional_handbook"
    jurisdictions: list[str] | None
    version_year: int | None
    display_name: str


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
