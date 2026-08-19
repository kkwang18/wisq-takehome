from __future__ import annotations

from src.docx_reader import read_docx_paragraphs
from tests.fixtures.docx_builder import write_minimal_docx

BODY_XML = """
    <w:tbl>
      <w:tr>
        <w:tc>
          <w:p>
            <w:pPr><w:pStyle w:val="Compact"/></w:pPr>
            <w:r><w:t>SECTION 1: TEST SECTION</w:t></w:r>
          </w:p>
        </w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <w:pPr><w:pStyle w:val="BodyText"/></w:pPr>
      <w:r><w:t>1.1 Some Policy This is the body text of the policy.</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="FirstParagraph"/></w:pPr>
      <w:r><w:t>============================================================</w:t></w:r>
    </w:p>
"""


def test_read_docx_paragraphs_includes_table_text_in_document_order(tmp_path):
    docx_path = tmp_path / "sample.docx"
    write_minimal_docx(docx_path, BODY_XML)

    paragraphs = read_docx_paragraphs(str(docx_path))

    assert [p.text for p in paragraphs] == [
        "SECTION 1: TEST SECTION",
        "1.1 Some Policy This is the body text of the policy.",
        "============================================================",
    ]
    assert paragraphs[0].style == "Compact"
    assert paragraphs[1].style == "BodyText"


def test_read_docx_paragraphs_skips_empty_paragraphs(tmp_path):
    docx_path = tmp_path / "sample.docx"
    write_minimal_docx(docx_path, '<w:p><w:r><w:t></w:t></w:r></w:p>')

    paragraphs = read_docx_paragraphs(str(docx_path))

    assert paragraphs == []
