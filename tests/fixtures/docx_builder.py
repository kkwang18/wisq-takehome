from __future__ import annotations

import zipfile
from pathlib import Path

DOCUMENT_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
{body}
  </w:body>
</w:document>"""


def write_minimal_docx(path: Path, body_xml: str) -> None:
    """Writes a .docx containing only what src/docx_reader.py actually reads:
    a zip with a word/document.xml entry. Not a Word-openable file, but a
    faithful fixture for our own narrow XML reader."""
    xml = DOCUMENT_XML_TEMPLATE.format(body=body_xml)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
