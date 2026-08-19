from __future__ import annotations

from src.chunking import chunk_document
from src.models import DocMeta, Paragraph

DOC = DocMeta(
    file="x.docx",
    doc_type="global_handbook",
    jurisdictions=None,
    version_year=2026,
    display_name="Test Handbook 2026",
)


def test_chunk_document_tags_body_paragraphs_with_nearest_heading():
    paragraphs = [
        Paragraph(text="============================================================", style="FirstParagraph"),
        Paragraph(text="SECTION 4: TIME AWAY FROM WORK", style="Compact"),
        Paragraph(text="4.2 Paid Time Off (PTO) The standard PTO is 15 days.", style="BodyText"),
        Paragraph(text="Page 1", style="Heading1"),
        Paragraph(text="SECTION 5: LEARNING", style="Compact"),
        Paragraph(text="5.1 Growth Mindset We want people to keep learning.", style="BodyText"),
        Paragraph(text="END OF HANDBOOK", style="Heading1"),
    ]

    chunks = chunk_document(paragraphs, DOC)

    assert [c.text for c in chunks] == [
        "4.2 Paid Time Off (PTO) The standard PTO is 15 days.",
        "5.1 Growth Mindset We want people to keep learning.",
    ]
    assert chunks[0].section_title == "SECTION 4: TIME AWAY FROM WORK"
    assert chunks[1].section_title == "SECTION 5: LEARNING"
    assert all(c.doc == DOC for c in chunks)


def test_chunk_document_handles_apac_heading2_style():
    paragraphs = [
        Paragraph(text="SCOPE", style="Heading2"),
        Paragraph(text="This handbook applies to China, Japan, and Taiwan.", style="FirstParagraph"),
    ]

    chunks = chunk_document(paragraphs, DOC)

    assert len(chunks) == 1
    assert chunks[0].section_title == "SCOPE"


def test_chunk_document_uses_display_name_before_any_heading_seen():
    paragraphs = [
        Paragraph(text="A stray intro paragraph before any heading.", style="BodyText"),
    ]

    chunks = chunk_document(paragraphs, DOC)

    assert chunks[0].section_title == "Test Handbook 2026"
