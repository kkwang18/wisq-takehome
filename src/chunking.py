from __future__ import annotations

import re

from src.models import Chunk, DocMeta, Paragraph

HEADING_STYLES = {"Compact", "Heading2"}
MAX_HEADING_LENGTH = 60
NOISE_PATTERN = re.compile(r"^=+$|^Page \d+$|^END OF HANDBOOK$")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_SPLIT_PATTERN.split(text.strip()) if s]


def chunk_document(paragraphs: list[Paragraph], doc_meta: DocMeta) -> list[Chunk]:
    # Sentence-level splitting is opt-in per document/section (documents.yaml's
    # split_sentences_in_sections), not a corpus-wide default. A corpus-wide version was
    # tried and reverted: it regressed an already-passing retrieval-quality test (more
    # fragments compete for a fixed SEARCH_K everywhere) to fix a problem confirmed in
    # exactly one section. See CLAUDE.md's chunking decisions for the full story.
    split_sections = set(doc_meta.split_sentences_in_sections or [])
    seen_headings = set()
    chunks = []
    current_heading = doc_meta.display_name

    for p in paragraphs:
        if NOISE_PATTERN.match(p.text):
            continue
        if p.style in HEADING_STYLES and len(p.text) <= MAX_HEADING_LENGTH:
            current_heading = p.text
            seen_headings.add(p.text)
            continue
        texts = _split_sentences(p.text) if current_heading in split_sections else [p.text]
        for text in texts:
            chunks.append(Chunk(text=text, section_title=current_heading, doc=doc_meta))

    # A typo'd or renamed section name here would otherwise silently fall back to
    # paragraph-level chunking instead of erroring — the worst failure mode for a manifest
    # setting that exists specifically to fix a real retrieval gap (see CLAUDE.md).
    unmatched = split_sections - seen_headings
    if unmatched:
        raise ValueError(
            f"{doc_meta.display_name}: split_sentences_in_sections names section(s) "
            f"{sorted(unmatched)} that were never found as a heading in the document "
            "(check documents.yaml for a typo or a renamed/removed section)"
        )

    return chunks
