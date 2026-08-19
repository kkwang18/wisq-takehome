from __future__ import annotations

from src.models import Chunk, DocMeta, Paragraph, ScoredChunk


def test_doc_meta_holds_declared_fields():
    doc = DocMeta(
        file="a.docx",
        doc_type="global_handbook",
        jurisdictions=None,
        version_year=2026,
        display_name="Test Handbook 2026",
    )
    assert doc.doc_type == "global_handbook"
    assert doc.version_year == 2026


def test_chunk_and_scored_chunk_reference_doc_meta():
    doc = DocMeta(
        file="a.docx",
        doc_type="regional_handbook",
        jurisdictions=["Taiwan"],
        version_year=None,
        display_name="APAC Benefits Handbook",
    )
    chunk = Chunk(text="12 days of PTO.", section_title="PTO", doc=doc)
    scored = ScoredChunk(chunk=chunk, score=0.87)

    assert chunk.doc is doc
    assert scored.chunk is chunk
    assert scored.score == 0.87


def test_paragraph_style_is_optional():
    p = Paragraph(text="hello", style=None)
    assert p.style is None
