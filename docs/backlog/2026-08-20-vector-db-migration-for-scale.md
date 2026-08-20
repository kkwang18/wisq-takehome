# BACKLOG: Migrate to a real vector DB (Chroma) — needed at scale, not needed today

**Status:** Investigated and designed in full; not implemented. Verified with a live
prototype that at this corpus's current size, migrating brings no measurable benefit. This
is infrastructure to build **when the corpus actually grows**, not before — treat the design
below as ready-to-implement, not as something requiring re-investigation first.

**Discovered/investigated:** 2026-08-20, following directly from the chunking/`SEARCH_K`
investigation the same day (see `TRANSCRIPT.md` § 15-16 and `CLAUDE.md`'s chunking
decisions) — the question that prompted this: "is there an open source vector DB we can use
for this project?"

## Summary

The current system (`src/retrieval.py`'s `VectorIndex`) is a deliberate, minimal design:
`numpy`, brute-force dot product over normalized embeddings, no vector database. That
decision was correct when made and is *still* correct today — verified, not assumed, via a
live prototype (see below). This ticket exists so the next session that considers this
question doesn't have to re-derive the design or re-run the prototype; it can start from
"has the corpus grown enough to revisit this" and go straight to implementation if so.

## Why this is deferred, not implemented (the prototype)

Two independent things were checked, both negative at current scale:

**1. Performance.** Brute-force `numpy` over 73 vectors × 384 dimensions is sub-millisecond.
Already established this session (the earlier latency investigation): ~97% of per-question
time is Claude API round-trips, not local search. No vector DB — ANN-indexed or not — would
be measurable in what a user experiences today.

**2. Accuracy (the more interesting question).** Built a real, working prototype: the actual
73-chunk corpus loaded into Chroma (schema exactly as designed below), combined with a
hand-rolled BM25 sparse pass and Reciprocal Rank Fusion for hybrid dense+sparse search — not
a toy, a working comparison against the real shipped `VectorIndex.search()`. Ran a 10-query
battery against all three (current system, Chroma-dense-only, Chroma+hybrid):

| Query | Why it was included |
|---|---|
| Taiwan PTO, gym reimbursement, US citizen PTO, Taiwan PTO in 2025 | Regression checks — the exact cases fixed earlier the same day |
| Conference budget, notice period, EAP/mental health, tuition reimbursement | Distinctive-keyword cases, where BM25 exact-term matching had a real shot at beating pure semantic similarity |
| "Can I work from home instead of the office" | Deliberately zero shared keywords with the source text ("remote and hybrid work... flexible work arrangements") — a paraphrase-only case testing dense embeddings' strength, and BM25 alone's weakness |
| "Does policy ever get overridden by local law" | The one remaining untested candidate from the same "general rule + exception" merged-chunk family that broke `SCOPE` (`SECTION 8`'s "nothing in this section overrides... local law" clause) |

**Result: `CURRENT == DENSE == HYBRID` on all 10 — zero cases where the current system
missed and hybrid caught it.** `DENSE` matching `CURRENT` exactly on every query is a useful
sanity check that the Chroma setup was a faithful replication (correct cosine metric,
identical embeddings) — the null result isn't from a broken prototype, and isn't
cherry-picked; the battery deliberately included hard/adversarial cases designed to find a
difference, not just easy sanity checks.

**Conclusion:** this corpus, at its current size and post-`SCOPE`-fix state, doesn't have a
demonstrated retrieval-accuracy gap that a different search algorithm would close. The one
real gap found this session was structural (chunk boundaries diluting an embedding) and was
already fixed at the chunking layer, not the retrieval-algorithm layer.

## When to revisit

- **Corpus grows large enough that brute-force `numpy` search becomes measurably slow** —
  not urgent at any size this project is likely to reach as a take-home, but real at
  "hundreds or thousands of documents" (see the earlier scaling discussion,
  `TRANSCRIPT.md` § 15, and `docs/backlog/2026-08-20-llm-assisted-semantic-chunking.md`,
  which was deferred for the identical reason: real capability, no demonstrated need yet).
- **A future document introduces a case pure embedding similarity actually gets wrong** —
  the 10-query battery above didn't find one, but it's not exhaustive; if a live query ever
  shows the same symptom `SCOPE` did (relevant chunk ranks far outside `SEARCH_K` despite
  containing the obviously right keywords), that's the trigger to re-run this prototype's
  methodology against the new case specifically, not to migrate speculatively.
- **Do not migrate "because it's more standard" or "because we can."** This project's
  established discipline (see the whole chunking investigation) is: test before switching,
  every time. Apply that here too.

## Full design (verified, ready to implement when triggered)

### Python 3.9 compatibility (checked against real PyPI wheel metadata, not just
`requires_python` headers, which are misleading for `abi3` wheels)

| Library | Latest version checked | 3.9-compatible? |
|---|---|---|
| **Chroma** | 1.5.9 | **Yes** — ships a genuine `cp39-abi3` wheel, installs today with no pinning |
| FAISS (`faiss-cpu`) | 1.15.0 | No — needs Python ≥3.10. Last 3.9-compatible release was **1.9.0** |
| LanceDB | 0.37.1 | No — `cp310-abi3` minimum |
| Qdrant (`qdrant-client`) | 1.19.0 | No — `>=3.10` |

Python 3.9 reached end-of-life in October 2025; most actively-developed libraries have
dropped it. **Chroma is the only realistic option without also upgrading this project's
Python version first** — a separate, bigger decision than "add a vector DB," and out of
scope for this ticket. If Python gets upgraded for other reasons, this table should be
re-checked, not assumed still accurate.

### Schema

One Chroma collection, mirroring the current `Chunk`/`DocMeta` model directly — no
restructuring needed:

| Chroma field | Maps from | Notes |
|---|---|---|
| `id` | `f"{doc.file}::{chunk_index}"` | Deterministic per (document, position) — see Lifecycle for why position-based, not content-hash |
| `embeddings` | `model.encode(embed_text(chunk))` | **Computed by this project, not Chroma** — see Indexing |
| `documents` | `chunk.text` | The verbatim excerpt text (what gets cited) |
| `metadatas.doc_type` | `chunk.doc.doc_type` | string, exact-match filter |
| `metadatas.display_name` | `chunk.doc.display_name` | string, for citations |
| `metadatas.section_title` | `chunk.section_title` | string, for citations |
| `metadatas.file` | `chunk.doc.file` | string — the lifecycle key |
| `metadatas.jurisdictions` | `chunk.doc.jurisdictions` | list of strings (Chroma metadata supports list-of-scalar values directly) |
| `metadatas.version_year` | `chunk.doc.version_year`, **or `-1` sentinel if `None`** | see critical filtering note below |

**Verified empirically, not assumed:** Chroma metadata values must be scalars or lists of
scalars — there is no native `null`. A record with a metadata key entirely *absent* is
**excluded** by `where={"version_year": 2025}` — confirmed by direct test. That is the exact
wrong-direction default `VectorIndex.search()` had *before* the fix earlier the same day (see
`CLAUDE.md`'s chunking decisions and commit `b7411e4`). A naive migration would silently
reintroduce that bug. Fix: store an explicit `-1` sentinel for evergreen documents (APAC)
instead of omitting the key, and always query with `$or` against both the requested year and
the sentinel (shown in Filtering below) — also verified empirically to work correctly.

### Indexing strategy

- **This project owns embedding computation, not Chroma.** Pass precomputed vectors via
  `embeddings=` (using the existing `sentence-transformers/all-MiniLM-L6-v2` +
  `embed_text()`'s contextual header), not Chroma's built-in embedding function. Chroma's
  default embedding function is a different model — swapping models would change every
  ranking tuned this session, and would lose the contextual-header technique (the reason
  2025-vs-2026 and global-vs-APAC disambiguation works at all).
- **Distance metric must be set explicitly to cosine.** Verified: `configuration={"hnsw":
  {"space": "cosine"}}` at collection creation. The unconfigured default is L2 distance,
  which would *not* match the current normalized-embeddings-dot-product approach and would
  silently produce different rankings than everything validated so far.
- Index type is HNSW under the hood regardless. At current corpus size this doesn't matter
  (confirmed no measurable performance difference from `numpy`) — the value is filtering
  ergonomics and, if ever needed, hybrid search infrastructure, not raw speed, until the
  corpus is genuinely large.

### Filtering strategy

Direct translation of `VectorIndex.search(doc_type=..., version_year=...)`, with the
evergreen-sentinel fix:

```python
where = {"doc_type": "regional_handbook"}  # exact match, same as today

# WRONG — reintroduces the version_year=None bug fixed earlier the same day:
# where["version_year"] = 2025

# Correct — replicates the fixed "None matches any year" semantics:
where = {
    "$and": [
        {"doc_type": "regional_handbook"},
        {"$or": [{"version_year": 2025}, {"version_year": -1}]},
    ]
}
```

`jurisdictions` filtering (if ever needed beyond `doc_type`) would use `$in` for
list-membership queries the same way.

### Document lifecycle (add / modify / delete)

The current system has no incremental model — `ingest.py` always does a full wipe-and-rebuild
from `documents.yaml`. Keep that as the default even after migrating (simplest, matches
what's tested, avoids orphaned-chunk bugs), but the schema is designed so a real incremental
path is possible later without a rewrite:

- **Add:** new `documents.yaml` entry → chunk + embed just that document → `collection.add()`
  for its chunks only. No rebuild needed for the rest of the corpus.
- **Modify:** (source `.docx` changed, or its `documents.yaml` config changed — e.g. a new
  `split_sentences_in_sections` entry) → `collection.delete(where={"file": doc.file})` **then**
  `collection.add()` fresh. Deliberately not a fine-grained upsert-by-ID: if a modification
  changes the chunk count for that document (exactly what happened with `SCOPE` earlier the
  same day), position-based IDs shift and stop lining up with old records — delete-then-readd
  for the whole file avoids leaving orphaned chunks behind from before the boundary changed.
- **Delete/deactivate:** `active: false` in `documents.yaml` →
  `collection.delete(where={"file": doc.file})`, no re-add.
- **Detecting "modified" without re-hashing everything every run:** would need a small
  manifest (file → content hash or mtime) tracked alongside the collection, checked before
  deciding add/skip/delete-and-readd. This doesn't exist today (full rebuild sidesteps the
  question entirely) — real new complexity this design introduces, not free. Build it only
  when incremental updates are actually needed (i.e., when full-rebuild cost becomes real),
  not preemptively.

## Prototype methodology (for reproducing or extending the test)

- Real corpus via `ingest.build_index("documents.yaml")` — the actual shipped 73-chunk
  index, not a synthetic fixture.
- Chroma loaded via `chromadb.EphemeralClient()` (in-memory, no persistence needed for a
  comparison run), collection configured with `{"hnsw": {"space": "cosine"}}`.
- BM25 hand-rolled (no new project dependency for a throwaway prototype) — standard
  `k1=1.5, b=0.75` formulation, tokenized on `[a-z0-9]+`.
- Hybrid fusion via standard Reciprocal Rank Fusion (`1/(60+rank)` summed across the dense
  and sparse rankings), a common, transparent choice — not Chroma's native (newer, less
  externally documented) `SparseEmbeddingFunction`/`Bm25EmbeddingFunction` API, which exists
  in this Chroma version but wasn't reverse-engineered blind for a prototype when a simpler,
  fully-visible approach answers the same question.
- Environment: dependencies installed directly into this project's `.venv` for the test run
  (guarantees identical embeddings to production, not a second, possibly-drifted
  environment), then fully uninstalled afterward — confirmed via `git status` (clean) and the
  full offline suite (43/43) that the exploration left no trace.

## Files involved (when implemented)

- New: a Chroma-backed implementation of the `VectorIndex` interface (`build`, `save`/`load`
  equivalent — Chroma's `PersistentClient` replaces the current `.npy`/`.jsonl` persistence —
  `search`), likely `src/retrieval_chroma.py` or a swapped implementation behind the same
  interface `src/agent.py` already consumes, so `answer_question()` doesn't need to change.
- `ingest.py`: routes to the new backend; decide whether to keep `numpy` as a fallback/option
  or fully replace it — not decided here, a call for whoever implements this once it's
  actually triggered.
- `requirements.txt`: add `chromadb` (confirmed 3.9-compatible, no other new dependency
  needed for the base migration; BM25/hybrid would need either a real dependency in place of
  the prototype's hand-rolled version, or continuing to hand-roll it deliberately).

## Context for whoever picks this up

Full investigation trail: the chunking/`SEARCH_K` fix that prompted this question
(`TRANSCRIPT.md` § 15-16, `CLAUDE.md`'s chunking decisions, commit `51c3dfd`), then this
vector-DB design and prototype (same session, same day). Read `CLAUDE.md`'s decisions section
for the one-paragraph version before diving into this ticket's full detail.
