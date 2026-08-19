from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

from src.models import Paragraph

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx_paragraphs(path: str) -> list[Paragraph]:
    """Reads word/document.xml directly (not via python-docx). python-docx's
    Document.paragraphs only returns top-level body paragraphs and silently
    skips paragraphs nested inside tables — and the real handbooks' section
    headers live inside single-cell banner tables. Walking the raw XML tree
    with ElementTree.iter() visits every w:p in document order regardless of
    table nesting, so nothing is silently dropped."""
    with zipfile.ZipFile(path) as z:
        xml_bytes = z.read("word/document.xml")
    tree = ET.fromstring(xml_bytes)

    paragraphs = []
    for p in tree.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if not text:
            continue
        style_el = p.find(f"{W}pPr/{W}pStyle")
        style = style_el.get(f"{W}val") if style_el is not None else None
        paragraphs.append(Paragraph(text=text, style=style))
    return paragraphs
