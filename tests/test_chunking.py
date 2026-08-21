from __future__ import annotations

import pytest

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


def test_chunk_document_splits_sentences_only_in_flagged_sections():
    # Sentence-level splitting is a manifest-driven, per-document, per-section opt-in
    # (documents.yaml's split_sentences_in_sections), not a corpus-wide default. This
    # was deliberately narrowed after a corpus-wide sentence-split experiment regressed
    # an already-passing retrieval-quality test (see CLAUDE.md's chunking decisions):
    # more fragments compete for a fixed SEARCH_K everywhere, for a problem that was
    # confirmed to exist in exactly one section. A DocMeta with no
    # split_sentences_in_sections (the default) must chunk every paragraph exactly as
    # before, one paragraph = one chunk.
    doc = DocMeta(
        file="x.docx",
        doc_type="regional_handbook",
        jurisdictions=["Taiwan"],
        version_year=None,
        display_name="Test Regional Handbook",
        split_sentences_in_sections=["SCOPE"],
    )
    paragraphs = [
        Paragraph(text="SCOPE", style="Heading2"),
        Paragraph(
            text=(
                "This handbook applies to employees in Taiwan. It does NOT apply to "
                "contractors, nor to personnel working in any other location. "
                "Contractors and personnel outside Taiwan should refer to the global "
                "handbook."
            ),
            style="FirstParagraph",
        ),
        Paragraph(text="REGIONAL BENEFITS", style="Heading2"),
        Paragraph(
            text="Eligible employees in Taiwan are entitled to 12 days of PTO per year. PTO is requested through the standard tools.",
            style="FirstParagraph",
        ),
    ]

    chunks = chunk_document(paragraphs, doc)

    scope_chunks = [c for c in chunks if c.section_title == "SCOPE"]
    benefits_chunks = [c for c in chunks if c.section_title == "REGIONAL BENEFITS"]

    assert [c.text for c in scope_chunks] == [
        "This handbook applies to employees in Taiwan.",
        "It does NOT apply to contractors, nor to personnel working in any other location.",
        "Contractors and personnel outside Taiwan should refer to the global handbook.",
    ]
    # REGIONAL BENEFITS is not in split_sentences_in_sections, so it stays one chunk per
    # paragraph even though it also has multiple sentences.
    assert len(benefits_chunks) == 1
    assert benefits_chunks[0].text == (
        "Eligible employees in Taiwan are entitled to 12 days of PTO per year. "
        "PTO is requested through the standard tools."
    )


def test_chunk_document_raises_when_split_sentences_in_sections_names_a_missing_heading():
    # A typo'd (or renamed/removed) section name in documents.yaml's
    # split_sentences_in_sections must fail loudly, not silently no-op back to
    # paragraph-level chunking — the same failure shape as a typo silently reverting the
    # SCOPE fix this feature exists for.
    doc = DocMeta(
        file="x.docx",
        doc_type="regional_handbook",
        jurisdictions=["Taiwan"],
        version_year=None,
        display_name="Test Regional Handbook",
        split_sentences_in_sections=["SCOPEE"],  # typo: real heading below is "SCOPE"
    )
    paragraphs = [
        Paragraph(text="SCOPE", style="Heading2"),
        Paragraph(text="This handbook applies to employees in Taiwan.", style="FirstParagraph"),
    ]

    with pytest.raises(ValueError, match="SCOPEE"):
        chunk_document(paragraphs, doc)


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
