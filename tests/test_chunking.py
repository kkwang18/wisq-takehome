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


def test_chunk_document_treats_long_compact_paragraph_as_body_not_heading():
    # Regression test: APAC's "LOCAL LAW PROVISIONS" section has real body
    # paragraphs that carry the same "Compact" style used for real section
    # headers elsewhere. A long, full-sentence "Compact" paragraph must be
    # emitted as a chunk under the nearest real heading, not swallowed as a
    # false heading (which previously discarded it entirely).
    paragraphs = [
        Paragraph(text="LOCAL LAW PROVISIONS", style="Heading2"),
        Paragraph(
            text=(
                "Statutory Public Holidays: Employees observe the national and "
                "regional statutory public holidays of their respective "
                "jurisdiction (China, Japan, or Taiwan). These are in addition "
                "to PTO."
            ),
            style="Compact",
        ),
    ]

    chunks = chunk_document(paragraphs, DOC)

    assert len(chunks) == 1
    assert chunks[0].text.startswith("Statutory Public Holidays:")
    assert chunks[0].section_title == "LOCAL LAW PROVISIONS"


def test_chunk_document_still_treats_short_compact_and_heading2_as_headings():
    # Boundary check: short Compact/Heading2 paragraphs (real headings) must
    # still be treated as headings after the length guard is added.
    paragraphs = [
        Paragraph(text="SECTION 4: TIME AWAY FROM WORK", style="Compact"),
        Paragraph(text="4.2 Paid Time Off (PTO) The standard PTO is 15 days.", style="BodyText"),
        Paragraph(text="SCOPE", style="Heading2"),
        Paragraph(text="This handbook applies to China, Japan, and Taiwan.", style="FirstParagraph"),
    ]

    chunks = chunk_document(paragraphs, DOC)

    assert len(chunks) == 2
    assert chunks[0].section_title == "SECTION 4: TIME AWAY FROM WORK"
    assert chunks[1].section_title == "SCOPE"
