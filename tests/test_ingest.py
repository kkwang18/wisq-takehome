from __future__ import annotations

import yaml

from ingest import build_index
from tests.fixtures.docx_builder import write_minimal_docx

BODY_XML = """
    <w:p><w:pPr><w:pStyle w:val="Compact"/></w:pPr><w:r><w:t>SECTION 1: TEST</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr><w:r><w:t>1.1 Test Policy The value is 42.</w:t></w:r></w:p>
"""


def test_build_index_from_manifest(tmp_path):
    docx_path = tmp_path / "fake.docx"
    write_minimal_docx(docx_path, BODY_XML)

    manifest_path = tmp_path / "documents.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            [
                {
                    "file": str(docx_path),
                    "doc_type": "global_handbook",
                    "jurisdictions": None,
                    "version_year": 2026,
                    "display_name": "Fake Handbook",
                    "active": True,
                },
                {
                    "file": str(docx_path),
                    "doc_type": "global_handbook",
                    "jurisdictions": None,
                    "version_year": 2099,
                    "display_name": "Should Be Skipped",
                    "active": False,
                },
            ]
        )
    )

    index = build_index(str(manifest_path))

    assert len(index.chunks) == 1
    assert index.chunks[0].text == "1.1 Test Policy The value is 42."
    assert index.chunks[0].section_title == "SECTION 1: TEST"
