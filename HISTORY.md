# Build History

Curated summary of the decisions, definitions, and course-corrections behind this system.
The full raw conversation is in `TRANSCRIPT.md`.

## The task

Build a Q&A system over three Acme HR documents (`Acme_Employee_Handbook_2025.docx`,
`Acme_Employee_Handbook_2026.docx`, `APAC_Benefits_Handbook.docx`) that must use retrieval
(chunk + embed + search) rather than stuffing full documents into every prompt, and must
answer 8 example queries correctly — including two queries with no clean numeric answer
(`unknown`, `hedge`).

## Definitions established during brainstorming

These are the business rules the system has to apply, extracted from the handbooks' own
"Conflicts and Precedence" sections, not invented for the test set:

- **Local wins, but only for PTO.** The APAC Benefits Handbook explicitly claims precedence
  over the global handbook specifically for PTO, and only PTO — for every other benefit it
  points back to the global handbook's own precedence rule.
- **More generous wins, for everything else.** The global handbook's default rule: where
  policies conflict, the option with the greater monetary value or entitlement applies.
- **Latest version wins when no year is specified.** Two global handbooks exist (2025, 2026)
  with different PTO numbers (14 vs 15 days); absent a stated year, the current/latest
  version applies.
- **Unknown, not a guess, when data doesn't exist.** A query about 2021 has no matching
  handbook — none of the provided documents cover a period before 2025 — so the system must
  say so rather than extrapolate.
- **Hedge, not a coin flip, when the entity is ambiguous.** "An employee living in Asia" is
  broader than "China, Japan, or Taiwan" (the APAC handbook's actual scope) — since a
  non-APAC Asian country would get a different (global-only) answer, the system must flag the
  ambiguity and ask, not pick one arbitrarily.
- **No hallucination, ever.** Every claim must be traceable to a retrieved excerpt with a
  citation; if retrieved excerpts don't support an answer, the system must say so rather than
  produce a fluent-sounding guess.

## Architecture decisions

- **Anthropic API for reasoning, local `sentence-transformers` for embeddings** — no
  embeddings API needed, no OpenAI dependency.
- **Agentic multi-hop retrieval**, not single-shot top-k: the questions require resolving a
  jurisdiction, resolving a document version, and then applying a precedence rule that
  itself lives in a different part of the document — a single fixed retrieval pass can't
  anticipate that combination for an arbitrary future question, so Claude gets a
  `search_handbooks` tool it can call multiple times before answering.
- **A separate grounding-verification pass** after the draft answer, checking every claim
  against only the chunks actually retrieved during that conversation — this is the concrete
  mechanism behind "no hallucination, ever," not just a prompt instruction.
- **Citations always shown to the end user**, inline in the answer text, not hidden.
- **Manifest-driven document set** (`documents.yaml`): adding or deprecating a document is a
  YAML edit plus a re-run of `ingest.py`, no code change.
- **Ingestion and querying are separate processes**: `ingest.py` builds and persists the
  index once; `main.py` and `eval.py` just load it, so no embedding-model cost at query time.

## Real-document surprises that changed the design mid-build

Two things were wrong in the original plan, both caught by inspecting the actual `.docx`
XML rather than trusting assumptions, and both fixed with evidence, not guesses:

1. **The handbooks' section headers live inside single-cell "banner" tables**, not top-level
   body paragraphs. `python-docx`'s `Document.paragraphs` API silently skips table-nested
   content, which would have dropped every section header. Fixed by reading
   `word/document.xml` directly via stdlib `zipfile` + `xml.etree.ElementTree`, dropping the
   `python-docx` dependency entirely.
2. **The two documents don't share one heading convention.** The global handbooks use
   `pStyle="Compact"` for real section headers; the APAC handbook uses `pStyle="Heading2"`.
   Worse — discovered only after real ingestion — APAC's "LOCAL LAW PROVISIONS" section has
   5 real body-content paragraphs that *also* carry `pStyle="Compact"`, which the original
   heading heuristic misclassified as headings and silently discarded. Fixed with a length
   guard (a paragraph counts as a heading only if it's both short-styled AND short, ≤60
   characters) rather than per-document special-casing.

## A retrieval-ranking near-miss found by the offline recall test

The offline retrieval-recall test suite (built specifically to answer the brainstorming
question "will free-text search alone reliably surface the correct chunk?") caught a real
near-miss: the APAC handbook's country-scope paragraph (naming China/Japan/Taiwan) ranked
7th of 13 candidates for a jurisdiction-scoping query, just outside the top-5 cutoff, because
an adjacent generic continuation paragraph out-ranked it lexically. Root-caused (not
guessed), then fixed by raising `k` from 5 to 8 — applied both in the test and in the real
agent's search tool, since the same risk existed in the live system, not just the test.

## Process

Built with the superpowers plugin: brainstorming → design spec → implementation plan →
subagent-driven execution (fresh implementer + fresh reviewer per task, true red/green TDD,
YAGNI, DRY — explicit user instruction, applied throughout). Every non-trivial judgment call
made during execution (the two chunking-heuristic fixes and the retrieval-k fix above) is
recorded with its reasoning in the SDD ledger at
`.superpowers/sdd/2026-08-19-rag-qa-system/progress.md`.
