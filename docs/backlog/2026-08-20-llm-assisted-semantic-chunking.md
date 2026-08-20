# BACKLOG: LLM-assisted semantic chunking (for when the corpus actually grows)

**Status:** Not started — deliberately deferred. Two narrow prototypes were run and the
findings are conclusive enough to document a recommendation, but no infrastructure exists
yet. This ticket exists so a future session doesn't have to re-run the same experiments.

**Discovered/investigated:** 2026-08-20, during a live debugging session that started from a
user-reported nondeterminism bug and worked backward through chunking-strategy design.

## Summary

The current chunking pipeline (`src/chunking.py`) is one-paragraph-per-chunk by default,
with a manifest-driven, per-document, per-section opt-in for sentence-level splitting
(`documents.yaml`'s `split_sentences_in_sections`, added the same day this ticket was
written — see `CLAUDE.md`'s chunking decisions for the full story of why it's scoped, not
corpus-wide). That mechanism is purely syntactic: it can split on sentence boundaries but
can never merge content across paragraphs, and can never split *within* a sentence that has
no internal punctuation. This ticket is about the next tier up: using an LLM at ingest time
to group content by meaning rather than syntax — relevant once this corpus grows large
enough, or diverse enough in authorship/style, that syntactic rules stop being a safe
assumption (see the "hundreds or thousands of documents" scaling discussion, `TRANSCRIPT.md`
§ 15).

## What was actually tested, and what it showed

**Prototype 1 — real corpus, narrow scope (APAC `SCOPE` section).** An LLM (Haiku-tier) was
given the two `SCOPE` paragraphs and asked to split them into semantically coherent,
verbatim chunks. Result: it produced *exactly* the same 3+1 sentence boundaries a mechanical
sentence-splitter would have produced for this specific paragraph — no cross-paragraph
merging, no sub-sentence splitting, nothing a regex couldn't do. The retrieval improvement
observed was real, but attributable to the fix being *narrowly scoped* (2 paragraphs
touched, not the whole corpus), not to any semantic intelligence the LLM brought to the
boundary decision. **This is the actual reason the shipped fix uses a mechanical
`_split_sentences()` behind a manifest opt-in flag, not an LLM call** — for this specific
case, they were equivalent, so the cheaper, dependency-free, fully-deterministic mechanism
won.

**Checked but not needed:** two other real-corpus candidates for cross-paragraph or
sub-sentence dependency (the `SCOPE` "supplements... APAC markets listed above" backward
reference, and `LOCAL LAW PROVISIONS`'s single-sentence "where local labor law mandates X,
the statutory minimum always applies" exception) were both already retrieving correctly
today (ranks #1-3 for queries that would need them) — so this corpus does not currently
demonstrate a *second* real problem requiring the LLM's differentiating capability.

**Prototype 2 — synthetic, designed to isolate the LLM's actual differentiating value.** A
constructed single-sentence paragraph with an embedded exception and no internal punctuation
("Employees are entitled to the standard reimbursement amount... except where a more
specific written agreement... controls and this policy's figure does not apply") — a
mechanical splitter cannot touch this at all (zero split points). The LLM correctly
separated it into two verbatim, semantically distinct chunks (general rule / exception
clause). **This is a clean, real demonstration that the capability gap is genuine** — it
just isn't exercised anywhere in this specific 3-document corpus today.

## Why this is deferred, not implemented

Not because the mechanism doesn't work — prototype 2 proves it does. Deferred because:
1. **No demonstrated need in the current corpus.** Every real gap found so far (`SCOPE`) was
   fixable with the cheaper mechanical approach. Building LLM-assisted chunking now would be
   solving a problem this corpus doesn't currently have.
2. **Real architectural cost.** `ingest.py` is currently fully local — no `ANTHROPIC_API_KEY`
   needed to build the index. An LLM-assisted ingest step breaks that separation
   deliberately, not by accident, and that's a decision to make consciously when there's an
   actual document that needs it, not preemptively.
3. **New failure surface at exactly the point nobody can check it.** The entire point of
   this tier is handling documents nobody's reading — which means chunking mistakes are
   invisible until a query fails. See the decision-log requirement below; it's not optional
   for this tier the way it would be for the mechanical one.

## What to build when this is picked up

- An ingest-time LLM chunking pass (cheap/fast model, e.g. Haiku-tier — see prototype
  scripts for a working prompt shape), scoped per-document or per-section the same way the
  mechanical opt-in is (`documents.yaml`-driven), not applied blanket across the whole
  corpus — same reasoning as why the mechanical fix is scoped, still applies here.
- **A mandatory decision-log output alongside the chunks** — one rationale per chunking
  decision (why split here, why kept together), the same shape used in the prototype
  scripts. This is the review mechanism for a tier where nobody reads the source documents;
  treat it as a hard requirement, not a nice-to-have.
- **Verbatim-fidelity verification**, automated, not manual. Prototype 1 caught the LLM
  silently normalizing a curly apostrophe (`'`) to a straight one (`'`) — not a paraphrase,
  but not byte-identical either. Whatever ships needs an automated check that every emitted
  chunk is an exact substring of its source paragraph (or an explicit, logged exception if
  not), given citations depend on exact text.
- **Idempotency check across re-ingests.** Same model family as the rest of this system, no
  `temperature=0` available — decide whether re-running ingestion on an unchanged document
  should be expected to produce byte-identical chunks, and if not, what that means for the
  persisted index's stability across rebuilds.
- Validation via automated recall testing (the same `test_retrieval_recall.py` pattern,
  extended with cases for whatever document motivated building this tier) — never manual
  document reading, consistent with the "system should always consider scale" principle this
  investigation was scoped around.

## Files involved (when implemented)

- New: an ingest-time LLM chunking module, parallel to but distinct from
  `src/chunking.py`'s mechanical path.
- `documents.yaml` / `src/manifest.py` / `src/models.py`: extend the existing
  `split_sentences_in_sections`-style opt-in pattern rather than inventing a new
  configuration mechanism.
- `ingest.py`: would need to route to the LLM-assisted path per-document/section, and would
  need `ANTHROPIC_API_KEY` at ingest time for any document using it — a real, visible
  architecture change from today's fully-local ingestion.

## Context for whoever picks this up

Full investigation, including the live nondeterminism report that started this thread, the
`SCOPE` ranking finding (#19-21 of 71 chunks), the corpus-wide sentence-split regression that
was tried and reverted, and both prototypes described above in full: `TRANSCRIPT.md` § 15.
The mechanical fix that shipped instead is documented in `CLAUDE.md`'s chunking decisions.
