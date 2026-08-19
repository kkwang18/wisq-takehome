# CLAUDE.md

## 1. Project summary

A RAG Q&A CLI over three Acme HR handbook `.docx` files (a take-home deliverable). Core
constraint: **retrieve, don't stuff** — answers must come from chunked/embedded/searched
excerpts, never full documents pasted into the prompt — and **never fabricate**: every claim
must cite a retrieved excerpt, and the system must explicitly answer `unknown` or hedge
rather than guess when the excerpts don't resolve the question. The hard cases are
version conflicts (2025 vs 2026 global handbook), regional precedence (APAC overrides global
for PTO only, not other benefits), and jurisdiction ambiguity ("Asia" vs the three countries
an APAC handbook actually covers).

## 2. Architecture

```
documents.yaml → ingest.py → index/{chunks.jsonl,embeddings.npy}
                                        ↓
question → main.py / eval.py → src/agent.py (Claude + search tool loop) → src/verification.py → answer
```

- `documents.yaml` — declares each source doc's metadata (`doc_type`, `jurisdictions`,
  `version_year`, `active`). Add/deprecate a document here, not in code.
- `src/docx_reader.py` — reads `word/document.xml` directly (stdlib `zipfile` +
  `ElementTree`), no `python-docx`.
- `src/chunking.py` — one non-empty paragraph = one chunk, tagged with nearest preceding
  heading. `HEADING_STYLES = {"Compact", "Heading2"}` + a `MAX_HEADING_LENGTH = 60` guard.
- `src/retrieval.py` — `embed_text()` (contextual header + chunk text),
  `VectorIndex` (build/save/load/search, local `sentence-transformers`, plain numpy, no
  vector DB), `SEARCH_K = 8` (shared constant, also imported by `src/agent.py`).
- `src/agent.py` — `answer_question()`: Claude + a `search_handbooks` tool, multi-hop
  (calls the tool as many times as needed), `MODEL = "claude-sonnet-5"`. No `temperature`
  param anywhere (rejected by this model). Main loop leaves adaptive thinking on
  (`max_tokens=8000`); the verification call disables thinking (`max_tokens=1000`).
- `src/verification.py` — `verify_answer()`: hard-fails (`grounded=False`, no LLM call) if
  `cited_chunks` is empty; otherwise asks the LLM to check the draft against only the cited
  excerpts. `VerifiedAnswer.rejected_draft` preserves a downgraded draft (currently unread
  by any caller).
- `ingest.py` — `build_index(manifest_path)`, and a CLI that persists to `index/`.
- `main.py` — CLI: no args runs the 8 take-home example queries, `--ask "..."` runs one.
- `eval.py` — separate real-API acceptance script (the 8 example queries against a fresh
  `build_index`, not the persisted `index/`). Not named `test_*.py`, not in `tests/`, so
  `pytest` never runs it. `_matches()` does substring/keyword matching against expected
  markers (`"12"`, `"unknown"`, `"hedge"`, etc.) — see gaps below.
- `tests/` — offline only (real local embeddings, zero API calls, zero mocks).
  `test_retrieval_recall.py` checks real-corpus retrieval quality against the take-home's
  actual queries — this is the regression guard for chunking/embedding/`k` changes.

## 3. Key decisions and why

- **Raw XML instead of `python-docx`.** The handbooks' section headers live inside
  single-cell "banner" tables; `python-docx`'s `Document.paragraphs` silently skips
  table-nested content and would drop every header.
- **One-paragraph-per-chunk instead of header-regex splitting.** The two global handbooks
  use `pStyle="Compact"` for real headers; the APAC handbook uses `pStyle="Heading2"` — no
  shared convention. Worse, APAC's "LOCAL LAW PROVISIONS" section has 5 real body paragraphs
  that *also* use `Compact`, which a naive style-only rule misclassified as headings and
  silently dropped. Fixed with the length guard, not per-document special-casing.
- **Contextual embedding headers + structured `doc_type`/`version_year` search filters.**
  The 2025 and 2026 PTO paragraphs are nearly word-for-word identical except the day count —
  nothing in the raw text says which version it is, so embedding similarity alone can't
  reliably disambiguate. `embed_text()` prepends doc metadata before embedding; the search
  tool also exposes explicit filters so Claude can narrow structurally once it's resolved a
  year/jurisdiction, not just hope similarity gets it right.
- **`SEARCH_K = 8`, not the more typical 5.** Found via the real-corpus recall test: the
  APAC scope paragraph (naming the 3 covered countries) ranked 7th of 13 for a jurisdiction
  query — an adjacent generic continuation paragraph outranked it. This is a live-system
  risk, not just a test-tuning issue, so `k` is one shared constant used by both.
- **No `temperature` param on any Claude call; verification call disables thinking.**
  `claude-sonnet-5` rejects non-default sampling params (400). It also runs adaptive
  thinking by default when `thinking` is omitted, and thinking tokens count against the same
  `max_tokens` ceiling as text — a low `max_tokens` on the verification call was silently
  returning empty text and downgrading every answer. Both only surfaced on the first live
  API run, late in the build (no key was available earlier).
- **Ambiguity hedging is decoupled from whether the final number would differ.** Originally
  the hedge rule only fired if different candidate jurisdictions gave different figures — but
  "gym benefits in Asia" converges to $50 regardless of country, and the model sometimes
  answered definitively instead of asking which country, which isn't the take-home's
  expected behavior. The rule now hedges on the ambiguity itself.

## 4. Open questions / known gaps

- **A policy split across consecutive paragraphs under one heading can lose its second
  half.** Chunking is strictly one-paragraph-per-chunk; if a section splits meaning across
  two adjacent paragraphs (like APAC's SCOPE section did — the near-miss `SEARCH_K` fix
  addressed *that specific* case by widening `k`, not by merging chunks), a future section
  with the same shape could still rank its continuation paragraph out of the search window.
  Not currently tested for beyond the SCOPE case in `test_retrieval_recall.py`.
- **`eval.py`'s `_matches()` is a substring/keyword heuristic on free-form model output**,
  not a semantic check. It was tuned reactively against 3 live runs' actual phrasing (see
  `HISTORY.md`/`TRANSCRIPT.md`) and is inherently gameable — a hedge-then-guess answer could
  plausibly trip an "unknown" marker. Treat it as a smoke test, not a strict regression gate.
- **No iteration cap on `answer_question`'s tool-use loop.** A non-converging model could
  loop indefinitely (unbounded API cost). Deferred as low-risk for this corpus size.
- **`VerifiedAnswer.rejected_draft` has no reader yet** — written on downgrade, never
  surfaced by `main.py`/`eval.py`. Fine as-is, but if you add a `--debug` flag or similar,
  this is where a rejected draft already lives.

## 5. Current status

Implemented and merged to `main`: full pipeline, all 12 original plan tasks, a
whole-branch review (2 Critical + 5 Important findings fixed), and 3 live-run-only fixes
(2 eval.py matcher gaps, 1 hedging-behavior gap). 34 offline tests pass. `eval.py` passes
8/8 against the real Claude API (last verified live during the build session — re-run it if
handbook content or retrieval logic changes). Nothing currently in progress.
