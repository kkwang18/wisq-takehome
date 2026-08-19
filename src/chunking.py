from __future__ import annotations

import re

from src.models import Chunk, DocMeta, Paragraph

HEADING_STYLES = {"Compact", "Heading2"}
NOISE_PATTERN = re.compile(r"^=+$|^Page \d+$|^END OF HANDBOOK$")


def chunk_document(paragraphs: list[Paragraph], doc_meta: DocMeta) -> list[Chunk]:
    chunks = []
    current_heading = doc_meta.display_name

    for p in paragraphs:
        if NOISE_PATTERN.match(p.text):
            continue
        if p.style in HEADING_STYLES:
            current_heading = p.text
            continue
        chunks.append(Chunk(text=p.text, section_title=current_heading, doc=doc_meta))

    return chunks
