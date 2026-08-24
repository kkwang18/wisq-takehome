# BACKLOG: `Expectation.doc_type`/`version_year` checks are a weak precondition, not proof of precedence-source correctness

**Status:** Open, not fixed — deliberately deferred. Found during the final whole-branch
review of `docs/superpowers/plans/2026-08-24-eval-matcher-redesign.md`
(`docs/superpowers/specs/2026-08-24-eval-matcher-redesign-design.md`). The comment this
finding invalidated has already been corrected in place (see "Files involved" below); this
ticket is about the check's actual weak semantics, which the correction only documents, not
fixes.

**Discovered:** 2026-08-24, final review of the eval-matcher redesign branch. The reviewer
independently verified the mechanism against the real index (see "Investigation" below) before
flagging it — this is a confirmed root cause, not a hypothesis.

**Severity:** Low-to-medium. Nothing in production (`src/agent.py`, `src/verification.py`) is
affected — this is purely an eval-harness precision gap. The risk is entirely epistemic: the
`PRECEDENCE` category's `doc_type`/`version_year` checks look like they assert "the answer's
figure came from the right document" but actually only assert "a chunk from the right document
was retrieved somewhere in this conversation" — a much weaker claim that a future contributor
could easily over-trust.

## Summary

`VerifiedAnswer.cited_chunks` (added by this same branch, `src/verification.py`) is populated
from `answer_question()`'s `cited_chunks` accumulator in `src/agent.py`, which does
`cited_chunks.extend(sc.chunk for sc in results)` inside the tool-call loop — i.e. it
accumulates **every chunk returned by every `search_handbooks` call**, not just the chunk(s)
the model's final `citation` field actually names. For a multi-hop precedence question, the
model typically searches both the regional and global handbooks to reason about which one
governs, so `cited_chunks` ends up containing chunks from both documents/both years regardless
of which one the final answer actually cites.

`Expectation(doc_type="regional_handbook")` and `Expectation(version_year=2026)` use "any chunk
in `cited_chunks` matches" semantics (deliberately, to support compound-question answers that
legitimately cite only some of what was searched — see the spec's "Document/version
correctness" section). But combined with the accumulate-everything nature of `cited_chunks`,
this means the check is satisfied by nearly any retrieval for a precedence question, not just a
correct one.

## Investigation

The final reviewer checked this directly against the real index: a single unfiltered `k=10`
search for representative `PRECEDENCE` queries ("PTO for an employee based in China", "gym
benefit for an employee based in Japan", "annual conference and training budget Taiwan") each
returned chunks from **both** `doc_type`s and **all three** `version_year` values (`2025`,
`2026`, `None`) in one `k=10` call. This means the 15 migrated `PRECEDENCE` cases' `doc_type`/
`version_year` sub-checks are satisfied almost unconditionally — the `numeric=` field (present
on every one of those cases) is doing essentially all the real discriminating work today.

This was corroborated live during the plan's Task 9 verification: a *rejected* ("What is the
gym benefit for an employee based in Japan?", `grounded=False`) answer's `doc_type`/
`version_year` sub-checks silently passed — only the `numeric` sub-check (which is correctly
`grounded`-gated) caught the failure. (That specific gap — `doc_type`/`version_year` not being
`grounded`-gated at all — was a separate, smaller finding from the same review, already fixed
directly: both fields now require `grounded=True` too. This ticket is about the deeper
semantic gap that gating alone doesn't close: even on a *grounded*, correctly-accepted answer,
these checks still don't confirm the cited document is what the answer's figure actually came
from.)

## Suggested fix (sketch, not implemented)

Two viable directions, in increasing order of invasiveness:

1. **Narrow to the final turn's retrieval only.** Change `answer_question()` to track which
   chunks were returned by the *last* `search_handbooks` call before `submit_answer`, or —
   more precisely — track chunks per search call and let `verify_answer`/`VerifiedAnswer`
   expose which chunks correspond to the citation actually named. This is a real, if modest,
   production-code change (`src/agent.py`), not just an eval-harness one — worth weighing
   whether it's justified by eval-precision alone or should wait for a production need too.
2. **Parse the citation field and match `Chunk.doc.display_name` against it**, similar to how
   `verify_answer`'s own citation check works (`src/verification.py`'s `_extract_citation()`).
   This keeps the fix eval-harness-local (no production code change), but reintroduces
   citation-text parsing — the exact pattern this codebase has repeatedly moved away from in
   favor of structural guarantees (see `CLAUDE.md`'s "guarantee structurally, not by prompt
   request" principle). Would need to be scoped carefully to avoid the same fragility class.

Neither is a quick fix; both need their own design discussion and adversarial testing before
shipping, consistent with how every other `verify_answer`/eval-harness change in this project
has been handled. Not attempted as part of the eval-matcher redesign branch — that branch's
own scope was the matcher's expectation language, not retrieval-provenance tracking.

## Test plan (once a fix is designed)

1. A `PRECEDENCE` case where the model correctly cites the regional handbook but the global
   handbook was also retrieved (a realistic multi-hop precedence question) must still pass.
2. A deliberately-constructed case where the model cites the WRONG document (a genuinely
   incorrect precedence conclusion) but the RIGHT document was also retrieved along the way
   must FAIL under a fixed check — this is the actual regression the current check cannot
   catch, and is the sharpest test of whether a fix closes the gap.
3. Full offline suite + a live `evals.edge_cases` run to confirm no `PRECEDENCE` case that
   currently passes starts failing.

## Related finding (2026-08-24 final review): `cited_chunks` also carries unbounded duplicates

A separate, whole-tree code review (not scoped to this ticket) found that
`answer_question()`'s `cited_chunks.extend(sc.chunk for sc in results)` (`src/agent.py`) never
dedupes across search calls. With `SEARCH_K = 10` and `MAX_TOOL_ITERATIONS = 8`, a multi-hop
question can accumulate far more chunk entries than the ~73-chunk corpus actually has,
duplicates included — and `build_verification_prompt()` serializes all of them into the
verifier's context verbatim. Not a correctness bug (no wrong answer traced to it), but real
cost on every question and a signal-quality risk for the verifier (a repeated excerpt reads as
independent corroborating evidence). The reviewer's own recommendation, and the reason it's
recorded here rather than as a separate ticket: this is the same root tension as the rest of
this ticket — `cited_chunks` is being asked to serve three different consumers (the
verification prompt, the citation check, and the eval matcher's `doc_type`/`version_year`
checks) with three different implicit semantics. Whoever picks up either suggested-fix
direction above should dedupe at the same time, not patch it separately — `Chunk` can't go in
a `set` directly (`DocMeta` is `frozen=True` but holds a `list[str] | None` field, so
`hash()` raises `TypeError`), so any fix needs a derived dedup key (e.g.
`(chunk.doc.file, chunk.section_title, chunk.text)`).

## Files involved

- `evals/edge_cases.py` — the `PRECEDENCE` list's comment now documents this limitation
  in place (corrected during the final-review fix wave, commit TBD — see this ticket's
  reference from that comment).
- `evals/matching.py` — `_check_expectation()`'s `doc_type`/`version_year` blocks, the likely
  fix location for suggested-fix direction 2.
- `src/agent.py` — `answer_question()`'s `cited_chunks` accumulation, the likely fix location
  for suggested-fix direction 1.
- `src/verification.py` — `VerifiedAnswer.cited_chunks`, whose semantics this ticket is about.
