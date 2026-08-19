# RAG Q&A System — Design Spec

Date: 2026-08-19
Status: Approved for implementation

## Problem

Build a Q&A system over three Acme HR policy documents (`Acme_Employee_Handbook_2025.docx`,
`Acme_Employee_Handbook_2026.docx`, `APAC_Benefits_Handbook.docx`) that answers questions
about benefits (PTO, gym reimbursement, etc.) correctly even when:

- Two documents disagree and one must win (versioning: newer global handbook supersedes
  older; regional carve-outs override global for specific benefit types).
- The question specifies a point in time that predates any handbook we have (must answer
  `unknown`, not guess).
- The question's entity (a country/region) is ambiguous and maps to jurisdictions with
  *different* answers (must hedge and ask for clarification, not pick one arbitrarily).

The system **must retrieve** (chunk + embed + search) rather than stuff full documents into
every prompt, and **must never fabricate** an answer not directly supported by retrieved text.

Full query set and expected answers are documented in `Take Home Test/Take Home Test 2026.pdf`.

## Non-goals (YAGNI)

- No vector DB (FAISS/Chroma) — corpus is ~20-30 chunks, an in-memory numpy array is
  sufficient and simpler.
- No incremental/diff-based re-indexing — full rebuild on `ingest.py` run is fast enough
  at this corpus size.
- No pluggable multi-provider LLM/embedding abstraction — Anthropic for generation,
  local `sentence-transformers` for embeddings, hardcoded.
- No web UI — CLI only.
- No retry/backoff/observability infrastructure.

## Architecture

```
docx files ─▶ ingest.py ─▶ chunks + metadata ─▶ index/ (persisted: chunks.jsonl, embeddings.npy)
                                                          │
question ──▶ main.py ──▶ agent.py (Claude + search tool, multi-hop) ──▶ verification ──▶ answer + citations
                                    │
                                    └─▶ retrieval.py.search() reads index/ at process start
```

Ingestion and querying are separate processes. `ingest.py` is run once (and re-run whenever
a document is added, changed, or deprecated); `main.py` loads the prebuilt index at startup
with no embedding-model inference needed to answer a question.

## Components

### `documents.yaml`

Declarative manifest — one entry per source file:

```yaml
- file: "Take Home Test/Acme_Employee_Handbook_2025.docx"
  doc_type: global_handbook
  jurisdictions: null        # null = applies everywhere unless overridden
  version_year: 2025
  active: true
- file: "Take Home Test/Acme_Employee_Handbook_2026.docx"
  doc_type: global_handbook
  jurisdictions: null
  version_year: 2026
  active: true
- file: "Take Home Test/APAC_Benefits_Handbook.docx"
  doc_type: regional_handbook
  jurisdictions: [China, Japan, Taiwan]
  version_year: null
  active: true
```

Adding a document = new file + new manifest entry, no code changes. Deprecating one =
`active: false` (or remove the entry) + re-run `ingest.py`.

### `src/manifest.py`

`load_manifest(path) -> list[DocMeta]` — pure parsing of the YAML above into a `DocMeta`
dataclass. Filters to `active: true` entries.

### `src/chunking.py`

`chunk_document(text: str, doc_meta: DocMeta) -> list[Chunk]` — pure function. Splits on the
documents' own structural headers (`SECTION N: ...`, `N.N Subheading`) so each chunk is one
coherent policy point (e.g. "4.2 Paid Time Off (PTO)" is its own chunk), not a fixed-size
sliding window. Each `Chunk` carries `text`, `section_title`, and the parent `DocMeta`.

### `src/docx_reader.py`

`read_docx_text(path) -> str` — extracts raw paragraph text from a `.docx` file (via
`python-docx`). Thin I/O wrapper, not unit-tested beyond a smoke test (real dependency is
external).

### `src/retrieval.py`

- `VectorIndex.build(chunks) -> VectorIndex` — embeds all chunks with
  `sentence-transformers/all-MiniLM-L6-v2` and holds vectors in a numpy array.
- `VectorIndex.save(dir) / VectorIndex.load(dir)` — persists/loads chunks.jsonl +
  embeddings.npy so `main.py` never re-embeds at query time.
- `VectorIndex.search(query: str, k: int) -> list[ScoredChunk]` — cosine similarity top-k.

### `src/agent.py`

The core reasoning loop. Claude is given:
- A `search_handbooks(query: str)` tool bound to `VectorIndex.search`.
- A system prompt encoding the *general* rule structure found in the handbooks' own
  "Conflicts and Precedence" sections — not the 8 example answers:
  - Resolve the person's stated country/state to a jurisdiction.
  - Resolve any year mentioned to the applicable handbook version; if no year is stated,
    use the latest version.
  - Check whether a regional handbook claims precedence for this specific benefit type
    (e.g. APAC claims precedence for PTO specifically, not benefits generally).
  - Otherwise apply the global "more generous benefit wins" default rule.
  - If the jurisdiction is ambiguous and different candidate jurisdictions would yield
    different answers, hedge and ask for clarification instead of guessing.
  - If no retrieved text covers the requested time period/entity, answer `unknown`.
- A hard grounding constraint: only use retrieved excerpts, never general knowledge about
  typical PTO/benefits norms; every factual claim must cite `(source doc, section)`.

Claude may call `search_handbooks` multiple times (multi-hop) before answering — e.g.
separately pulling the regional PTO clause, the correct-year global PTO clause, and the
precedence clause.

`verify_answer(draft: str, cited_chunks: list[Chunk]) -> VerifiedAnswer` — a second pass
(separate Claude call) that checks every factual claim in the draft against the chunks
actually retrieved during the conversation. Unsupported claims cause the answer to be
downgraded to a hedge/unknown rather than returned as-is.

### `main.py`

- No args: runs the 8 example queries from the PDF, prints each Q + grounded answer +
  citations.
- `--ask "question"`: answers one ad hoc question the same way.

### `ingest.py`

Reads `documents.yaml`, parses active `.docx` files, chunks them, builds and persists the
`VectorIndex` to `index/`.

### `eval.py`

Runs the 8 example queries and asserts the answer contains the expected figure/verdict
(12, 15, 14, 15, unknown, $50, $50, hedge) — the executable form of the take-home's own
spec; doubles as a regression check.

## Data model (DRY: defined once, reused everywhere)

```python
@dataclass
class DocMeta:
    file: str
    doc_type: str          # "global_handbook" | "regional_handbook"
    jurisdictions: list[str] | None
    version_year: int | None

@dataclass
class Chunk:
    text: str
    section_title: str
    doc: DocMeta

@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
```

## Testing strategy (red/green TDD)

Each unit below is built test-first:

| Unit | Test approach |
|---|---|
| `chunk_document` | Fixture section text in → assert chunk boundaries/titles/count out |
| `load_manifest` | Fixture YAML in → assert parsed `DocMeta` list, `active:false` filtered |
| `VectorIndex.search` | Tiny hand-built fixture index (not the real corpus) → assert known ranking |
| `verify_answer` | Fixture draft fully supported → pass unchanged; fixture draft with an unsupported claim → downgraded |
| `agent` orchestration | Thin glue, not unit-tested in isolation |
| End-to-end | `eval.py` against the real corpus + real Claude calls, the 8 PDF queries as acceptance criteria |

## Error handling

Minimal, honest, no speculative resilience:
- Missing `ANTHROPIC_API_KEY` → fail fast at startup with a clear message.
- Malformed manifest entry → fail fast at ingest time.
- The agent's only real "failure" mode is answering `unknown`/hedge when grounding fails —
  that's a normal return value, not an exception.

## File layout

```
wisq/
  Take Home Test/                          (given materials, unchanged)
  documents.yaml
  src/
    manifest.py
    chunking.py
    docx_reader.py
    retrieval.py
    agent.py
  tests/
    test_manifest.py
    test_chunking.py
    test_retrieval.py
    test_agent_verification.py
  ingest.py
  main.py
  eval.py
  requirements.txt
  README.md
  HISTORY.md            (curated decisions/definitions summary)
  TRANSCRIPT.md          (raw brainstorming + build conversation)
  docs/superpowers/specs/2026-08-19-rag-qa-system-design.md
  index/                 (generated, gitignored)
```

## Deliverables (per take-home requirements)

1. Working code (above).
2. `HISTORY.md` + `TRANSCRIPT.md` — coding agent history, per the take-home's explicit
   request to see "what conversation/questions/definitions" shaped the build.
