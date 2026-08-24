# BACKLOG: Draft-time hallucination of named entities not in any excerpt

**Status:** Fix implemented and committed (SYSTEM_PROMPT addition in `src/agent.py`). Kept
as a backlog entry rather than closed silently because the fix is unverified against the
rare event it targets — see "Confidence in the fix" below. Re-open / escalate if a
recurrence is ever observed.

**Discovered:** 2026-08-20, live user testing (not part of the planned edge-case matrix —
found by chance during normal use).

**Severity:** Low-frequency but high-severity in kind: a genuine fabrication (not a
retrieval mix-up or a verifier misjudgment) that happened to be caught by `verify_answer`
before reaching the user. If `verify_answer` had missed it, this would have been an
undetected hallucination — the system's core guarantee failing silently.

## Summary

Running `python main.py --ask "Do employees have any sick days? What aboout 401k? What
about vision ,dental or medical insurance?"` produced a draft answer that stated the APAC
Benefits Handbook's jurisdictions are "Hong Kong/Singapore/etc. type jurisdictions." This is
factually wrong: the APAC handbook covers only China, Japan, and Taiwan. Neither "Hong Kong"
nor "Singapore" appears anywhere in the corpus (confirmed directly against
`index/chunks.jsonl` — zero matches for either string). `verify_answer` correctly rejected
the draft as UNSUPPORTED, so the user never saw a wrong answer — but the draft-time
generation step fabricated named entities that were never retrieved at all.

## Why this is a different bug class from the two existing `verify_answer` tickets

The two open tickets
(`2026-08-20-verify-answer-precedence-false-rejection.md`,
`2026-08-20-verify-answer-absence-inference-false-rejection.md`) are both about
`verify_answer` **misreading text that was actually retrieved** — over-rejecting a correct
draft because the verifier's own reasoning about the cited excerpts is flawed. Both are
false-positive risks (correct answers wrongly downgraded), and both leave the "never
fabricate" guarantee intact.

This finding is the opposite shape: the **draft-generation step itself invented content that
was never in `cited_chunks`**. `verify_answer` did its job and caught it. This is a
draft-time grounding gap, not a verification-time reading gap — the fix belongs in
`SYSTEM_PROMPT` (what the drafting model is told to do), not in
`build_verification_prompt`.

## Investigation

1. Confirmed via direct corpus check: `Hong Kong` and `Singapore` appear in zero chunks in
   `index/chunks.jsonl`. The APAC handbook's actual scope is China, Japan, Taiwan only.
2. Added temporary debug instrumentation to `src/agent.py` (printing each `search_handbooks`
   call and the raw draft text before verification) and reproduced the exact question live.
3. Reproduced the exact question **7 times total** across this investigation (3 before the
   fix, 4 after) — every reproduction came back correct and properly grounded, with two
   post-fix runs explicitly and correctly naming "China, Japan, and Taiwan." The original
   fabrication was not reproduced even once outside the user's initial live report.
4. Hypothesized root cause: outside/pretrained-knowledge contamination on named entities.
   Hong Kong and Singapore are common real-world APAC business hubs — plausible the model's
   pretraining leaked a "typical APAC jurisdictions" association despite the existing
   "never use outside knowledge about typical PTO or benefits norms" instruction, which was
   scoped to norms/figures and didn't explicitly cover named entities.

## Fix applied

Added to `SYSTEM_PROMPT` in `src/agent.py`, directly after the existing "never use outside
knowledge... never guess" sentence:

> "This includes named entities, not just figures: never state a specific country, city, or
> other named entity unless it appears verbatim in a retrieved excerpt. If an excerpt refers
> to something without naming it (e.g. 'these three jurisdictions'), do not supply the name
> from your own knowledge — describe it only as the excerpt does, or say the specific name
> isn't given."

This is a purely restrictive addition — it only prohibits the model from doing something it
was already never supposed to do. Unlike the two `verify_answer` tickets above (where adding
leniency carries a real false-negative risk), tightening a draft-time grounding instruction
has no symmetric downside: it can only make the model more conservative, never more likely
to fabricate.

## Confidence in the fix

Honest caveat: the fabrication was observed once, in casual sampling, at an estimated
~1-in-4 to ~1-in-8 rate (1 fabrication across roughly 5-9 total attempts at this question,
depending how the count is framed). 7 post-discovery reproductions (3 pre-fix, 4 post-fix)
all came back clean, but a sample this small cannot statistically distinguish "the fix
worked" from "the rare event just didn't recur." No regression was introduced — full
regression evidence below — so the fix is being kept regardless of whether it's provably the
cause of the clean streak.

## Regression evidence

- Offline suite: 49/49 passed after the fix.
- `python -m evals.eval` (live, real API): 8/8 passed after the fix.
- No other files touched; `src/agent.py` diff is the `SYSTEM_PROMPT` addition only.

## Suggested follow-up (not yet done)

If this recurs, the next diagnostic step would be to log every draft `verify_answer`
rejects (not just print during ad hoc debugging) so real-world fabrication rate and pattern
can be measured over time without manual reproduction — this would also make it possible to
tell, on a larger sample, whether the fix meaningfully changed the rate. Not implemented now.
(`VerifiedAnswer` previously carried a `rejected_draft` field for exactly this purpose, but it
was removed 2026-08-24 — written on every downgrade, never read by any caller, confirmed dead
code by a repo-wide grep. If this follow-up is picked up, a similar field/logger would need to
be reintroduced, this time with a real reader wired up from the start.)

## Files involved

- `src/agent.py` — `SYSTEM_PROMPT`, the fix location (committed).
- `index/chunks.jsonl` — used to confirm corpus-absence of the fabricated entities (no code
  changes here; investigation only).
