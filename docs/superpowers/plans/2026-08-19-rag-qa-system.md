# RAG Q&A System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a retrieval-augmented Q&A CLI over three Acme HR handbooks that correctly
resolves document-version conflicts and regional-precedence conflicts, cites its sources,
and explicitly hedges/answers `unknown` rather than fabricating when grounding fails.

**Architecture:** Documents are declared in a manifest, parsed from raw docx XML (not
`python-docx`, which drops table-nested content), chunked one-paragraph-at-a-time with
nearest-heading tagging, embedded locally with contextual metadata headers, and persisted to
a flat-file vector index. At query time, Claude drives a multi-hop `search_handbooks` tool
loop over that index, then a second grounding-verification pass checks the draft answer
against only the chunks actually retrieved before it's returned.

**Tech Stack:** Python 3.9, `anthropic` SDK (generation + verification), local
`sentence-transformers/all-MiniLM-L6-v2` (embeddings, no embeddings API), plain `numpy`
in-memory vector store (no FAISS/Chroma), `pyyaml` for the manifest, `pytest` for tests.

**Spec:** `docs/superpowers/specs/2026-08-19-rag-qa-system-design.md`

## Global Constraints

- Python 3.9 target — use `from __future__ import annotations` in every new module so
  modern type hints (`list[X]`, `X | None`) work without requiring 3.10.
- No `python-docx` dependency — `.docx` parsing goes through stdlib `zipfile` +
  `xml.etree.ElementTree` directly, reading `word/document.xml` and iterating `w:p` in
  document order (this is a deliberate spec requirement, not a style choice — see spec
  §`src/docx_reader.py`).
- No vector DB, no incremental indexing, no pluggable LLM/embedding providers, no web UI —
  per spec Non-goals.
- Every LLM call inside a function that's unit tested must be dependency-injected as a
  parameter (see `verify_answer`), so unit tests never hit the network or cost API tokens.
- True red/green TDD on every task with a `Test:` file: write the failing test, watch it
  fail for the right reason, write minimal code to pass, watch it pass, then commit.
- `eval.py` (real Claude API, end-to-end acceptance) is intentionally **not** named
  `test_*.py` and lives outside `tests/`, so `pytest` never collects it and never spends API
  tokens by accident.

---

### Task 1: Project setup + shared data model

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/models.py`
- Test: `tests/test_models.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/__init__.py`
- Create: `pytest.ini`

**Interfaces:**
- Produces: `DocMeta(file: str, doc_type: str, jurisdictions: list[str] | None, version_year: int | None, display_name: str)`, `Paragraph(text: str, style: str | None)`, `Chunk(text: str, section_title: str, doc: DocMeta)`, `ScoredChunk(chunk: Chunk, score: float)` — all `@dataclass`, all consumed by every later task.

- [ ] **Step 1: Create the venv and install the full dependency set**

```bash
cd /Users/kennywang/code/wisq
python3 -m venv .venv
source .venv/bin/activate
```

Write `requirements.txt`:

```
anthropic>=0.40.0
sentence-transformers>=3.0.0
numpy>=1.26.0
pyyaml>=6.0
pytest>=8.0.0
```

```bash
pip install -r requirements.txt
```

Expected: installs succeed (sentence-transformers pulls in torch; this can take a few
minutes on first install).

- [ ] **Step 2: Write `pytest.ini` so `pytest` finds `src` and `tests` on the path**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 3: Write the failing test for the data model**

`tests/__init__.py` and `tests/fixtures/__init__.py` are empty files.

`tests/test_models.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.models'` (or `ImportError`).

- [ ] **Step 5: Write the minimal implementation**

`src/__init__.py` is empty.

`src/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocMeta:
    file: str
    doc_type: str  # "global_handbook" | "regional_handbook"
    jurisdictions: list[str] | None
    version_year: int | None
    display_name: str


@dataclass(frozen=True)
class Paragraph:
    text: str
    style: str | None


@dataclass(frozen=True)
class Chunk:
    text: str
    section_title: str
    doc: DocMeta


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini src/__init__.py src/models.py tests/__init__.py tests/fixtures/__init__.py tests/test_models.py
git commit -m "$(cat <<'EOF'
Add project scaffolding and shared data model

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 2: Manifest loading

**Files:**
- Create: `src/manifest.py`
- Test: `tests/test_manifest.py`
- Create: `tests/fixtures/sample_manifest.yaml`

**Interfaces:**
- Consumes: `DocMeta` from Task 1 (`src/models.py`).
- Produces: `load_manifest(path: str) -> list[DocMeta]`, consumed by `ingest.py` (Task 8).

- [ ] **Step 1: Write the failing test**

`tests/fixtures/sample_manifest.yaml`:

```yaml
- file: "fake_a.docx"
  doc_type: global_handbook
  jurisdictions: null
  version_year: 2025
  display_name: "Fake Handbook 2025"
  active: true
- file: "fake_b.docx"
  doc_type: regional_handbook
  jurisdictions: ["Testland"]
  version_year: null
  display_name: "Fake Regional Handbook"
  active: false
```

`tests/test_manifest.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.manifest import load_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_manifest.yaml"


def test_load_manifest_filters_to_active_entries():
    docs = load_manifest(str(FIXTURE))
    assert len(docs) == 1
    assert docs[0].file == "fake_a.docx"
    assert docs[0].doc_type == "global_handbook"
    assert docs[0].jurisdictions is None
    assert docs[0].version_year == 2025
    assert docs[0].display_name == "Fake Handbook 2025"


def test_load_manifest_preserves_jurisdictions_list():
    import yaml

    raw = yaml.safe_load(FIXTURE.read_text())
    raw[1]["active"] = True
    tmp = FIXTURE.parent / "sample_manifest_all_active.yaml"
    tmp.write_text(yaml.safe_dump(raw))
    try:
        docs = load_manifest(str(tmp))
        regional = [d for d in docs if d.doc_type == "regional_handbook"][0]
        assert regional.jurisdictions == ["Testland"]
    finally:
        tmp.unlink()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.manifest'`.

- [ ] **Step 3: Write minimal implementation**

`src/manifest.py`:

```python
from __future__ import annotations

import yaml

from src.models import DocMeta


def load_manifest(path: str) -> list[DocMeta]:
    with open(path) as f:
        raw_entries = yaml.safe_load(f) or []

    docs = []
    for entry in raw_entries:
        if not entry.get("active", False):
            continue
        docs.append(
            DocMeta(
                file=entry["file"],
                doc_type=entry["doc_type"],
                jurisdictions=entry.get("jurisdictions"),
                version_year=entry.get("version_year"),
                display_name=entry["display_name"],
            )
        )
    return docs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/manifest.py tests/test_manifest.py tests/fixtures/sample_manifest.yaml
git commit -m "$(cat <<'EOF'
Add manifest loading for document metadata

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 3: docx paragraph reader (raw XML, table-safe)

**Files:**
- Create: `src/docx_reader.py`
- Create: `tests/fixtures/docx_builder.py`
- Test: `tests/test_docx_reader.py`

**Interfaces:**
- Consumes: `Paragraph` from Task 1.
- Produces: `read_docx_paragraphs(path: str) -> list[Paragraph]`, consumed by `ingest.py`
  (Task 8). Also produces the shared test helper `write_minimal_docx(path, body_xml)`,
  reused by Task 8's test.

- [ ] **Step 1: Write the shared fixture helper**

`tests/fixtures/docx_builder.py`:

```python
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
```

- [ ] **Step 2: Write the failing test**

`tests/test_docx_reader.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_docx_reader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.docx_reader'`.

- [ ] **Step 4: Write minimal implementation**

`src/docx_reader.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_docx_reader.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/docx_reader.py tests/test_docx_reader.py tests/fixtures/docx_builder.py
git commit -m "$(cat <<'EOF'
Add table-safe docx paragraph reader

Reads word/document.xml directly via stdlib zipfile+ElementTree instead
of python-docx, because the real handbooks' section headers live inside
single-cell banner tables that python-docx's Document.paragraphs
silently skips.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 4: Chunking with nearest-heading tagging

**Files:**
- Create: `src/chunking.py`
- Test: `tests/test_chunking.py`

**Interfaces:**
- Consumes: `Paragraph`, `Chunk`, `DocMeta` from Task 1.
- Produces: `chunk_document(paragraphs: list[Paragraph], doc_meta: DocMeta) -> list[Chunk]`,
  consumed by `ingest.py` (Task 8).

- [ ] **Step 1: Write the failing test**

`tests/test_chunking.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chunking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.chunking'`.

- [ ] **Step 3: Write minimal implementation**

`src/chunking.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chunking.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/chunking.py tests/test_chunking.py
git commit -m "$(cat <<'EOF'
Add paragraph-level chunking with nearest-heading tagging

One non-empty body paragraph per chunk, tagged with the nearest
preceding heading. Handles both documents' heading conventions
(Compact vs Heading2) with one detection rule instead of two
document-specific regexes, since neither document gives subsection
headers their own paragraph.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 5: Vector index (contextual embeddings + metadata filters)

**Files:**
- Create: `src/retrieval.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: `Chunk`, `DocMeta`, `ScoredChunk` from Task 1.
- Produces: `embed_text(chunk: Chunk) -> str`; `VectorIndex.build(chunks, model=None) -> VectorIndex`; `VectorIndex.save(dir_path: str) -> None`; `VectorIndex.load(dir_path: str, model=None) -> VectorIndex`; `VectorIndex.search(query: str, k: int = 5, doc_type: str | None = None, version_year: int | None = None) -> list[ScoredChunk]`. Consumed by `ingest.py` (Task 8), `agent.py` (Task 7), `main.py` (Task 9).

- [ ] **Step 1: Write the failing test**

`tests/test_retrieval.py`:

```python
from __future__ import annotations

import pytest
from sentence_transformers import SentenceTransformer

from src.models import Chunk, DocMeta
from src.retrieval import VectorIndex, embed_text

GLOBAL_2025 = DocMeta(file="g25.docx", doc_type="global_handbook", jurisdictions=None, version_year=2025, display_name="Global Handbook 2025")
GLOBAL_2026 = DocMeta(file="g26.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Global Handbook 2026")
REGIONAL = DocMeta(file="apac.docx", doc_type="regional_handbook", jurisdictions=["Taiwan"], version_year=None, display_name="APAC Benefits Handbook")


@pytest.fixture(scope="module")
def model():
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def sample_chunks():
    return [
        Chunk(text="The standard global PTO entitlement is 14 days per year.", section_title="4.2 PTO", doc=GLOBAL_2025),
        Chunk(text="The standard global PTO entitlement is 15 days per year.", section_title="4.2 PTO", doc=GLOBAL_2026),
        Chunk(text="Eligible employees in Taiwan are entitled to 12 days of PTO per year.", section_title="PTO", doc=REGIONAL),
        Chunk(text="The standard global gym membership benefit is $50 per month.", section_title="Section 3", doc=GLOBAL_2026),
    ]


def test_embed_text_includes_metadata_header():
    text = embed_text(sample_chunks()[1])
    assert "Global Handbook 2026" in text
    assert "2026" in text
    assert "4.2 PTO" in text
    assert "15 days per year" in text


def test_search_ranks_topically_relevant_chunk_first(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("gym membership reimbursement", k=1)
    assert results[0].chunk.text.startswith("The standard global gym")


def test_search_filters_by_doc_type(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("PTO entitlement", k=10, doc_type="regional_handbook")
    assert len(results) == 1
    assert results[0].chunk.doc.doc_type == "regional_handbook"


def test_search_filters_by_version_year(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("PTO entitlement", k=10, version_year=2025)
    assert len(results) == 1
    assert results[0].chunk.doc.version_year == 2025


def test_search_returns_empty_when_filters_match_nothing(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("PTO entitlement", k=10, version_year=1999)
    assert results == []


def test_save_and_load_round_trip(tmp_path, model):
    index = VectorIndex.build(sample_chunks(), model=model)
    index.save(str(tmp_path / "idx"))

    loaded = VectorIndex.load(str(tmp_path / "idx"), model=model)

    assert len(loaded.chunks) == len(index.chunks)
    assert loaded.chunks[0].text == index.chunks[0].text
    assert loaded.chunks[0].doc == index.chunks[0].doc
    results = loaded.search("gym membership reimbursement", k=1)
    assert results[0].chunk.text.startswith("The standard global gym")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retrieval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.retrieval'`.

- [ ] **Step 3: Write minimal implementation**

`src/retrieval.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from src.models import Chunk, DocMeta, ScoredChunk

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def embed_text(chunk: Chunk) -> str:
    """The string actually embedded for a chunk: its own text prefixed with a
    metadata header. The 2025 and 2026 PTO paragraphs are nearly identical
    except the number itself, so nothing in the raw text says which version
    it belongs to — embedding the header alongside the text makes the vector
    itself version/jurisdiction-aware. Queries are embedded raw (see
    VectorIndex.search); only chunk-side text gets this treatment."""
    jurisdictions = ", ".join(chunk.doc.jurisdictions) if chunk.doc.jurisdictions else "global"
    year = chunk.doc.version_year if chunk.doc.version_year is not None else "n/a"
    header = (
        f"[{chunk.doc.display_name} · {chunk.doc.doc_type} · "
        f"jurisdictions: {jurisdictions} · version_year: {year} · "
        f"Section: {chunk.section_title}]"
    )
    return f"{header}\n{chunk.text}"


class VectorIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, model: SentenceTransformer | None = None):
        self.chunks = chunks
        self.embeddings = embeddings
        self._model = model

    @classmethod
    def build(cls, chunks: list[Chunk], model: SentenceTransformer | None = None) -> "VectorIndex":
        model = model or SentenceTransformer(MODEL_NAME)
        texts = [embed_text(c) for c in chunks]
        vectors = np.array(model.encode(texts, normalize_embeddings=True))
        return cls(chunks, vectors, model=model)

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    def search(
        self,
        query: str,
        k: int = 5,
        doc_type: str | None = None,
        version_year: int | None = None,
    ) -> list[ScoredChunk]:
        candidate_indices = [
            i
            for i, c in enumerate(self.chunks)
            if (doc_type is None or c.doc.doc_type == doc_type)
            and (version_year is None or c.doc.version_year == version_year)
        ]
        if not candidate_indices:
            return []

        model = self._get_model()
        q_vec = np.array(model.encode([query], normalize_embeddings=True))[0]

        scored = [
            ScoredChunk(chunk=self.chunks[i], score=float(np.dot(self.embeddings[i], q_vec)))
            for i in candidate_indices
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return scored[:k]

    def save(self, dir_path: str) -> None:
        out = Path(dir_path)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "chunks.jsonl", "w") as f:
            for c in self.chunks:
                f.write(
                    json.dumps(
                        {
                            "text": c.text,
                            "section_title": c.section_title,
                            "doc": {
                                "file": c.doc.file,
                                "doc_type": c.doc.doc_type,
                                "jurisdictions": c.doc.jurisdictions,
                                "version_year": c.doc.version_year,
                                "display_name": c.doc.display_name,
                            },
                        }
                    )
                    + "\n"
                )
        np.save(out / "embeddings.npy", self.embeddings)

    @classmethod
    def load(cls, dir_path: str, model: SentenceTransformer | None = None) -> "VectorIndex":
        src = Path(dir_path)
        chunks = []
        with open(src / "chunks.jsonl") as f:
            for line in f:
                data = json.loads(line)
                doc = DocMeta(**data["doc"])
                chunks.append(Chunk(text=data["text"], section_title=data["section_title"], doc=doc))
        embeddings = np.load(src / "embeddings.npy")
        return cls(chunks, embeddings, model=model)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_retrieval.py -v`
Expected: PASS (6 passed). First run downloads the MiniLM model (~80MB); subsequent runs
use the local cache.

- [ ] **Step 5: Commit**

```bash
git add src/retrieval.py tests/test_retrieval.py
git commit -m "$(cat <<'EOF'
Add vector index with contextual embeddings and metadata filters

Chunk text is embedded with a prepended metadata header (doc,
version_year, jurisdictions, section) so near-duplicate text across
handbook versions is still distinguishable by embedding similarity.
search() also accepts explicit doc_type/version_year filters so the
agent can combine semantic search with structural filtering once it
has resolved those facts from a question.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 6: Grounding verification pass

**Files:**
- Create: `src/verification.py`
- Test: `tests/test_verification.py`

**Interfaces:**
- Consumes: `Chunk` from Task 1.
- Produces: `VerifiedAnswer(text: str, grounded: bool)`; `verify_answer(draft: str, cited_chunks: list[Chunk], llm_call: Callable[[str], str]) -> VerifiedAnswer`. Consumed by `agent.py` (Task 7).

- [ ] **Step 1: Write the failing test**

`tests/test_verification.py`:

```python
from __future__ import annotations

from src.models import Chunk, DocMeta
from src.verification import VerifiedAnswer, verify_answer

DOC = DocMeta(file="x.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Test Handbook")
CHUNK = Chunk(text="The standard global PTO entitlement is 15 days per year.", section_title="4.2 PTO", doc=DOC)


def test_verify_answer_passes_through_supported_draft():
    result = verify_answer("PTO is 15 days.", [CHUNK], llm_call=lambda prompt: "SUPPORTED")
    assert result == VerifiedAnswer(text="PTO is 15 days.", grounded=True)


def test_verify_answer_downgrades_unsupported_draft():
    result = verify_answer(
        "PTO is 20 days.",
        [CHUNK],
        llm_call=lambda prompt: "UNSUPPORTED: 20 days is not stated in the excerpts",
    )
    assert result.grounded is False
    assert "20 days is not stated" in result.text


def test_verify_answer_prompt_includes_draft_and_excerpts():
    captured = {}

    def fake_llm_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "SUPPORTED"

    verify_answer("PTO is 15 days.", [CHUNK], llm_call=fake_llm_call)

    assert "PTO is 15 days." in captured["prompt"]
    assert "15 days per year" in captured["prompt"]
    assert "Test Handbook" in captured["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_verification.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.verification'`.

- [ ] **Step 3: Write minimal implementation**

`src/verification.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.models import Chunk


@dataclass
class VerifiedAnswer:
    text: str
    grounded: bool


def build_verification_prompt(draft: str, cited_chunks: list[Chunk]) -> str:
    excerpts = "\n\n".join(f"[{c.doc.display_name} - {c.section_title}]\n{c.text}" for c in cited_chunks)
    return (
        "You are checking whether every factual claim in a draft answer is directly "
        "supported by the excerpts below. Respond with exactly 'SUPPORTED' if every claim "
        "is backed by the excerpts, or 'UNSUPPORTED: <reason>' if any claim is not directly "
        "backed by the excerpts.\n\n"
        f"Excerpts:\n{excerpts}\n\nDraft answer:\n{draft}"
    )


def verify_answer(draft: str, cited_chunks: list[Chunk], llm_call: Callable[[str], str]) -> VerifiedAnswer:
    prompt = build_verification_prompt(draft, cited_chunks)
    verdict = llm_call(prompt).strip()

    if verdict.startswith("SUPPORTED"):
        return VerifiedAnswer(text=draft, grounded=True)

    fallback = (
        "I can't confirm this from the retrieved policy text alone — "
        f"the verification check flagged: {verdict}"
    )
    return VerifiedAnswer(text=fallback, grounded=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_verification.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/verification.py tests/test_verification.py
git commit -m "$(cat <<'EOF'
Add grounding verification pass with injected LLM call

verify_answer checks a draft answer against only the chunks actually
retrieved and downgrades to a hedge when a claim isn't supported. The
LLM call is injected as a parameter so this is unit-testable offline
with a stub, no network or API cost.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 7: Agent — multi-hop search tool loop + Claude wiring

**Files:**
- Create: `src/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `VectorIndex` (Task 5), `verify_answer`/`VerifiedAnswer` (Task 6), `Chunk` (Task 1).
- Produces: `SYSTEM_PROMPT: str`, `SEARCH_TOOL: dict`, `MODEL: str`, `answer_question(question: str, index: VectorIndex, client: anthropic.Anthropic | None = None) -> VerifiedAnswer`. Consumed by `main.py` (Task 9) and `eval.py` (Task 11).

This task's orchestration logic makes real API calls by design (per spec, it's "thin glue,
not unit-tested in isolation") — the test here only guards the system prompt's required
rules so a future edit can't silently delete a grounding constraint. `answer_question`
itself is exercised for real in Task 9 (manually) and Task 11 (`eval.py`).

- [ ] **Step 1: Write the failing test**

`tests/test_agent.py`:

```python
from __future__ import annotations

from src.agent import SEARCH_TOOL, SYSTEM_PROMPT


def test_system_prompt_encodes_grounding_and_precedence_rules():
    lowered = SYSTEM_PROMPT.lower()
    assert "search_handbooks" in lowered
    assert "ambiguous" in lowered or "ambiguity" in lowered
    assert "unknown" in lowered
    assert "cite" in lowered
    assert "more generous" in lowered


def test_search_tool_schema_exposes_metadata_filters():
    props = SEARCH_TOOL["input_schema"]["properties"]
    assert "query" in props
    assert "doc_type" in props
    assert "version_year" in props
    assert SEARCH_TOOL["input_schema"]["required"] == ["query"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent'`.

- [ ] **Step 3: Write minimal implementation**

`src/agent.py`:

```python
from __future__ import annotations

import anthropic

from src.models import Chunk
from src.retrieval import VectorIndex
from src.verification import VerifiedAnswer, verify_answer

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are an HR policy assistant answering questions about Acme employee \
benefits using ONLY the excerpts returned by the search_handbooks tool. Never use outside \
knowledge about typical PTO or benefits norms, and never guess.

To answer well:
1. Resolve the person's stated country or state to a jurisdiction.
2. Resolve any year mentioned in the question to the applicable handbook version. If no \
year is stated, use the latest available version.
3. Check whether a regional handbook claims precedence for this specific benefit type \
(some regional handbooks only claim precedence for particular benefits, not all benefits).
4. If no regional precedence applies, use the global handbook's own precedence rule \
(commonly: the more generous benefit applies where policies conflict).
5. If the jurisdiction in the question is ambiguous and different candidate jurisdictions \
in the retrieved excerpts would give different answers, do not guess — explain the \
ambiguity and ask for clarification instead of picking one.
6. If the retrieved excerpts do not cover the time period or entity asked about, say the \
answer is unknown rather than estimating.

Call search_handbooks as many times as you need before answering — for example, to \
separately retrieve the regional policy, the correct-year global policy, and the \
precedence rules.

Every factual claim in your final answer must cite its source as (Document Name, Section). \
Do not state a figure or rule that isn't directly present in a retrieved excerpt."""

SEARCH_TOOL = {
    "name": "search_handbooks",
    "description": "Search the Acme handbooks for relevant policy excerpts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text search query, e.g. 'PTO entitlement' or 'gym membership reimbursement'",
            },
            "doc_type": {
                "type": "string",
                "enum": ["global_handbook", "regional_handbook"],
                "description": "Optional filter to only one kind of handbook",
            },
            "version_year": {
                "type": "integer",
                "description": "Optional filter to a specific handbook version year",
            },
        },
        "required": ["query"],
    },
}


def _format_excerpts(results) -> str:
    if not results:
        return "No matching excerpts found."
    return "\n\n".join(f"[{sc.chunk.doc.display_name} - {sc.chunk.section_title}]\n{sc.chunk.text}" for sc in results)


def answer_question(question: str, index: VectorIndex, client: anthropic.Anthropic | None = None) -> VerifiedAnswer:
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    cited_chunks: list[Chunk] = []
    draft = ""

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=[SEARCH_TOOL],
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            draft = "".join(block.text for block in response.content if block.type == "text")
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            results = index.search(
                block.input["query"],
                k=5,
                doc_type=block.input.get("doc_type"),
                version_year=block.input.get("version_year"),
            )
            cited_chunks.extend(sc.chunk for sc in results)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _format_excerpts(results),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    def llm_call(prompt: str) -> str:
        verify_response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in verify_response.content if b.type == "text")

    return verify_answer(draft, cited_chunks, llm_call)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/agent.py tests/test_agent.py
git commit -m "$(cat <<'EOF'
Add agentic multi-hop retrieval loop

Claude drives search_handbooks as a tool, calling it as many times as
needed (regional policy, correct-year global policy, precedence rules)
before drafting an answer, which then goes through verify_answer
before being returned. System prompt encodes the general rule
structure from the handbooks' own precedence sections, not the
specific expected answers.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 8: Ingestion CLI + real document manifest

**Files:**
- Create: `ingest.py`
- Create: `documents.yaml`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `load_manifest` (Task 2), `read_docx_paragraphs` (Task 3), `chunk_document` (Task 4), `VectorIndex` (Task 5), `write_minimal_docx` fixture helper (Task 3).
- Produces: `build_index(manifest_path: str) -> VectorIndex`, consumed by Task 10 (recall tests) and Task 11 (`eval.py`). Also produces the `index/` directory on disk when run as a script.

- [ ] **Step 1: Write the real document manifest**

`documents.yaml`:

```yaml
- file: "Take Home Test/Acme_Employee_Handbook_2025.docx"
  doc_type: global_handbook
  jurisdictions: null
  version_year: 2025
  display_name: "Acme Employee Handbook 2025"
  active: true
- file: "Take Home Test/Acme_Employee_Handbook_2026.docx"
  doc_type: global_handbook
  jurisdictions: null
  version_year: 2026
  display_name: "Acme Employee Handbook 2026"
  active: true
- file: "Take Home Test/APAC_Benefits_Handbook.docx"
  doc_type: regional_handbook
  jurisdictions: ["China", "Japan", "Taiwan"]
  version_year: null
  display_name: "APAC Benefits Handbook"
  active: true
```

- [ ] **Step 2: Write the failing test**

`tests/test_ingest.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest'`.

- [ ] **Step 4: Write minimal implementation**

`ingest.py`:

```python
from __future__ import annotations

import argparse

from src.chunking import chunk_document
from src.docx_reader import read_docx_paragraphs
from src.manifest import load_manifest
from src.models import Chunk
from src.retrieval import VectorIndex


def build_index(manifest_path: str) -> VectorIndex:
    docs = load_manifest(manifest_path)
    all_chunks: list[Chunk] = []
    for doc_meta in docs:
        paragraphs = read_docx_paragraphs(doc_meta.file)
        all_chunks.extend(chunk_document(paragraphs, doc_meta))
    return VectorIndex.build(all_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the RAG index from documents.yaml")
    parser.add_argument("--manifest", default="documents.yaml")
    parser.add_argument("--out", default="index")
    args = parser.parse_args()

    index = build_index(args.manifest)
    index.save(args.out)
    print(f"Indexed {len(index.chunks)} chunks from {args.manifest} into {args.out}/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Run the real ingestion against the actual handbooks**

Run: `python ingest.py`
Expected: prints `Indexed N chunks from documents.yaml into index/` with N in the
neighborhood of 20-30, and creates `index/chunks.jsonl` + `index/embeddings.npy`.

- [ ] **Step 7: Commit**

```bash
git add ingest.py documents.yaml tests/test_ingest.py
git commit -m "$(cat <<'EOF'
Add ingestion CLI and the real document manifest

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 9: Query CLI

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `VectorIndex.load` (Task 5), `answer_question` (Task 7).
- Produces: `EXAMPLE_QUERIES: list[str]`, `select_questions(ask: str | None) -> list[str]`.

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:

```python
from __future__ import annotations

from main import EXAMPLE_QUERIES, select_questions


def test_example_queries_match_the_take_home_pdf():
    assert len(EXAMPLE_QUERIES) == 8
    assert "Taiwanese employee" in EXAMPLE_QUERIES[0]


def test_select_questions_defaults_to_example_queries():
    assert select_questions(None) == EXAMPLE_QUERIES


def test_select_questions_uses_ask_override():
    assert select_questions("What is PTO in Germany?") == ["What is PTO in Germany?"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`.

- [ ] **Step 3: Write minimal implementation**

`main.py`:

```python
from __future__ import annotations

import argparse

from src.agent import answer_question
from src.retrieval import VectorIndex

EXAMPLE_QUERIES = [
    "What is the PTO allowance for a Taiwanese employee?",
    "What is the PTO allowance for a California employee?",
    "What is the PTO allowance for a California employee in 2025?",
    "What is the PTO allowance for a California employee in 2026?",
    "What is the PTO allowance for a California employee in 2021?",
    "What is the gym related benefits for a Taiwanese employee?",
    "What is the gym related benefits for a California employee?",
    "What is the gym related benefits for a employee living in Asia?",
]


def select_questions(ask: str | None) -> list[str]:
    return [ask] if ask else EXAMPLE_QUERIES


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the Acme benefits Q&A system a question")
    parser.add_argument("--ask", default=None, help="Ask a single ad hoc question instead of running the example set")
    parser.add_argument("--index", default="index", help="Path to the prebuilt index directory")
    args = parser.parse_args()

    index = VectorIndex.load(args.index)

    for question in select_questions(args.ask):
        print(f"Q: {question}\n")
        result = answer_question(question, index)
        print(result.text)
        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
Add query CLI (example query set + --ask mode)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 10: Offline retrieval recall checks against the real corpus

**Files:**
- Test: `tests/test_retrieval_recall.py`

**Interfaces:**
- Consumes: `build_index` (Task 8). No production code produced — this task is pure test,
  directly answering the brainstorming question about whether free-text search alone
  reliably surfaces the correct chunk.

- [ ] **Step 1: Write the test**

This test has no separate "make it pass" implementation step — it exercises code that
already exists (Task 5's filtered search + Task 8's real ingestion) against the real
corpus, entirely offline (local embeddings only, no Claude call).

`tests/test_retrieval_recall.py`:

```python
from __future__ import annotations

import pytest

from ingest import build_index


@pytest.fixture(scope="module")
def index():
    return build_index("documents.yaml")


def test_taiwan_pto_recalls_regional_figure(index):
    results = index.search("PTO allowance Taiwan employee", k=5, doc_type="regional_handbook")
    texts = " ".join(r.chunk.text for r in results)
    assert "12 days" in texts


def test_california_pto_2025_recalls_correct_year(index):
    results = index.search("PTO allowance 2025", k=5, doc_type="global_handbook", version_year=2025)
    texts = " ".join(r.chunk.text for r in results)
    assert "14 days" in texts


def test_california_pto_2026_recalls_correct_year(index):
    results = index.search("PTO allowance 2026", k=5, doc_type="global_handbook", version_year=2026)
    texts = " ".join(r.chunk.text for r in results)
    assert "15 days" in texts


def test_gym_benefit_recalls_both_regional_and_global_amounts(index):
    regional = index.search("gym membership reimbursement", k=5, doc_type="regional_handbook")
    global_2026 = index.search("gym membership reimbursement", k=5, doc_type="global_handbook", version_year=2026)
    assert any("$30" in r.chunk.text for r in regional)
    assert any("$50" in r.chunk.text for r in global_2026)


def test_precedence_rules_are_retrievable(index):
    global_results = index.search("conflicts and precedence more generous benefit applies", k=5, doc_type="global_handbook", version_year=2026)
    regional_results = index.search("conflicts and precedence PTO takes precedence over global", k=5, doc_type="regional_handbook")
    assert any("more generous" in r.chunk.text.lower() for r in global_results)
    assert any("takes precedence" in r.chunk.text.lower() for r in regional_results)


def test_apac_scope_is_retrievable_to_rule_out_california():
    """The agent needs to be able to find that APAC only covers China/Japan/Taiwan
    in order to correctly conclude California isn't covered by it."""
    index_ = build_index("documents.yaml")
    results = index_.search("which countries does this regional handbook apply to", k=5, doc_type="regional_handbook")
    texts = " ".join(r.chunk.text for r in results)
    assert "Taiwan" in texts
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_retrieval_recall.py -v`
Expected: PASS (6 passed). If any assertion fails, that's a real retrieval-quality bug —
increase `k`, revisit `embed_text`'s metadata header, or revisit the query text used by
the agent's tool calls, not a test to loosen.

- [ ] **Step 3: Commit**

```bash
git add tests/test_retrieval_recall.py
git commit -m "$(cat <<'EOF'
Add offline retrieval recall checks against the real corpus

Verifies, for each of the take-home's 8 example queries, that the
necessary ground-truth chunks (correct-year PTO figures, regional vs
global gym amounts, both precedence clauses, APAC's country scope)
actually surface in top-k via local embeddings alone — no Claude
call, so this runs in the normal fast test suite and catches
retrieval-precision regressions for free.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 11: End-to-end acceptance eval (real Claude API)

**Files:**
- Create: `eval.py`

**Interfaces:**
- Consumes: `build_index` (Task 8), `answer_question` (Task 7).
- Not collected by `pytest` (filename doesn't match `test_*.py` and it lives at repo root,
  not in `tests/`) — run manually, requires `ANTHROPIC_API_KEY`.

- [ ] **Step 1: Write `eval.py`**

```python
from __future__ import annotations

import sys

from ingest import build_index
from src.agent import answer_question

EXPECTED = [
    ("What is the PTO allowance for a Taiwanese employee?", "12"),
    ("What is the PTO allowance for a California employee?", "15"),
    ("What is the PTO allowance for a California employee in 2025?", "14"),
    ("What is the PTO allowance for a California employee in 2026?", "15"),
    ("What is the PTO allowance for a California employee in 2021?", "unknown"),
    ("What is the gym related benefits for a Taiwanese employee?", "$50"),
    ("What is the gym related benefits for a California employee?", "$50"),
    ("What is the gym related benefits for a employee living in Asia?", "hedge"),
]


def _matches(expected: str, result_text: str, grounded: bool) -> bool:
    lowered = result_text.lower()
    if expected == "unknown":
        return "unknown" in lowered or not grounded
    if expected == "hedge":
        return any(word in lowered for word in ["ambig", "clarif", "which country", "unclear", "depends on"])
    return expected in result_text


def main() -> None:
    index = build_index("documents.yaml")
    failures = []

    for question, expected in EXPECTED:
        result = answer_question(question, index)
        print(f"Q: {question}\n{result.text}\n{'-' * 80}")
        if not _matches(expected, result.text, result.grounded):
            failures.append((question, expected, result.text))

    if failures:
        print(f"\n{len(failures)} of {len(EXPECTED)} queries did not match expectations:")
        for q, exp, got in failures:
            print(f"  Q: {q}\n  expected marker: {exp!r}\n  got: {got}\n")
        sys.exit(1)

    print(f"\nAll {len(EXPECTED)} queries matched expectations.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it for real**

Run: `ANTHROPIC_API_KEY=... python eval.py`
Expected: prints all 8 Q&A pairs with citations, ends with
`All 8 queries matched expectations.` and exit code 0. If a query fails, read the printed
answer — this is a real correctness signal, not a flaky test; fix the system prompt,
`embed_text` header, or search filters in the relevant earlier task, then re-run.

- [ ] **Step 3: Commit**

```bash
git add eval.py
git commit -m "$(cat <<'EOF'
Add end-to-end acceptance eval against the real Claude API

Runs the take-home's 8 example queries through the real system and
checks each answer contains the expected figure/verdict. Deliberately
not named test_*.py and not in tests/, so pytest never collects it and
never spends API tokens by accident — it's the one thing that must
exercise real reasoning rather than a stub, run manually.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

### Task 12: README

**Files:**
- Create: `README.md`

**Interfaces:**
- None — documentation only, references commands from all prior tasks.

- [ ] **Step 1: Write `README.md`**

```markdown
# Acme Benefits Q&A (RAG)

Answers questions about Acme's employee handbooks using retrieval-augmented generation:
local embeddings for search, Claude for multi-hop reasoning over conflicting/versioned
policy documents, with a grounding-verification pass before any answer is returned.

See `docs/superpowers/specs/2026-08-19-rag-qa-system-design.md` for the design, and
`HISTORY.md` / `TRANSCRIPT.md` for the conversation that shaped it.

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-...

## Build the index

Run this once, and again whenever a document in `documents.yaml` is added, changed, or
deprecated:

    python ingest.py

## Ask questions

    python main.py                              # runs the 8 example queries from the take-home PDF
    python main.py --ask "What is the PTO allowance for a remote employee in Germany?"

## Tests

    pytest                    # fast, fully offline: unit tests + retrieval recall checks
    python eval.py            # slow, real Claude API calls: full end-to-end acceptance run
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
Add README

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ji6tdWBxvofbKxKYANRDfy
EOF
)"
```

---

## Not delegated to task execution: HISTORY.md and TRANSCRIPT.md

The take-home explicitly asks to see "what conversation/questions/definitions" shaped this
build. `HISTORY.md` (curated decision summary) and `TRANSCRIPT.md` (the actual brainstorming
+ build conversation) require the real conversation content, which only the orchestrating
session has — a fresh subagent executing a task in isolation has no access to it. These two
files are written directly by the orchestrating session after Task 12, not as a plan task,
and then committed on their own.
