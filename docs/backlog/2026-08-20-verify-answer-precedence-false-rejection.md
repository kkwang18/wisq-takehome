# BACKLOG: `verify_answer` over-rejects correct specific-vs-general precedence answers

**Status:** Fixed (2026-08-21), together with the sibling absence-inference ticket below, via
one shared addition to `build_verification_prompt` rather than two separate patches (the
option both tickets flagged as worth evaluating). See "Fix implemented" at the bottom for
what shipped and how the previously-open false-negative risk was resolved before landing it.

**Discovered:** 2026-08-20, live testing during a "production readiness" edge-case
investigation session.

**Severity:** Medium. Degrades reliability (correct answers intermittently get downgraded
to an unhelpful "can't confirm" fallback) but does **not** cause fabrication — the failure
mode is conservative (over-cautious), not permissive. That's also exactly why the fix
carries its own risk (see below).

**Related, already fixed:** Commit `b7411e4` fixed a separate bug (`VectorIndex.search()`'s
`version_year` filter excluding the APAC regional handbook's undated chunks) that was
initially conflated with this one — both were discovered on the same query in the same
debugging session. They are independent: the retrieval bug could cause an actually *wrong*
draft; this bug causes a *correct* draft to be wrongly rejected. Do not re-open the retrieval
bug as part of this ticket.

**Related, sibling ticket (still open):**
`docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md` covers a
different but similarly-shaped `verify_answer` weakness — rejecting correct
absence-based-inference answers ("no specific provision names X, so the stated general
default applies") rather than specific-vs-general precedence carve-outs. Consider whether
one fix addresses both before implementing either in isolation.

## Summary

`verify_answer` (`src/verification.py`) sometimes rejects a factually correct draft answer
when the underlying precedence logic has a "specific rule for case X; a different general
rule for all other cases" shape. The verifier fails to recognize that the specific rule is a
complete, self-contained answer for X and doesn't need reconciling against the general rule
— it flags the draft as UNSUPPORTED for not addressing a "tension" that doesn't actually
exist in the source text.

## Concrete example

Question: "What is the PTO policy for Taiwan PTO in 2025" (also reproduces, at a lower rate,
on the plain "Taiwan PTO" question — this is the flagship example query from the original
take-home, not an obscure edge case).

Relevant excerpt (APAC Benefits Handbook, CONFLICTS AND PRECEDENCE):

> "Where a conflict arises specifically with respect to PAID TIME OFF (PTO), the LOCAL PTO
> POLICY set out in this APAC Benefits Handbook TAKES PRECEDENCE over any conflicting PTO
> provision in the global handbook... For all other benefits, refer to the precedence rules
> in the global Acme Employee Handbook."

Global handbook's general rule (Section 8):

> "Where the perks and benefits described in this handbook conflict with those described in
> another Acme policy or handbook, the MORE GENEROUS perk or benefit applies."

**The correct reading:** PTO is explicitly carved out of "all other benefits," so it's
governed solely by the APAC-specific clause — 12 days controls, even though it's less
generous than the global 14/15 days. The verifier has, on multiple observed occasions,
treated this as unresolved. Two actual rejection texts from live runs this session,
verbatim:

> "UNSUPPORTED: The draft concludes that the 12-day APAC PTO entitlement... applies and
> takes precedence, but the excerpts state that the global handbook's Conflicts and
> Precedence section (Section 8) specifies that... 'the MORE GENEROUS perk or benefit
> applies.' The APAC handbook's PTO-specific precedence clause says the local PTO policy
> takes precedence... but it does not clearly resolve whether the 'more generous' principle
> from the global handbook still applies to override a less generous local PTO policy. The
> draft asserts a definitive answer (12 days controls) without acknowledging this tension or
> ambiguity..."

> "UNSUPPORTED: ...the excerpts show two different precedence rules — the APAC handbook says
> its local PTO policy takes precedence, while the global handbook's Section 8 says the
> 'more generous' benefit applies. The draft resolves this conflict by simply applying the
> APAC-specific precedence clause without acknowledging or reconciling the global handbook's
> 'more generous' rule... The draft presents its conclusion as settled fact without
> addressing this apparent conflict..."

Both rejections are wrong — the draft was correct (12 days), and the "conflict" the verifier
describes doesn't exist in the text; the APAC clause explicitly scopes itself out of the
general rule's "all other benefits" language.

## How this bug is created (root cause)

`build_verification_prompt` (`src/verification.py:16`) gives the verifier no guidance on how
to read a specific-carve-out-vs-general-fallback document structure. Left to its own
judgment, the verification LLM treats the mere co-existence of a general rule elsewhere in
the excerpts as evidence of unresolved ambiguity, even when the specific rule's own text
already excludes itself from the general rule's scope. This is a reading-comprehension gap
in the verifier's own reasoning, not a retrieval problem — in every observed instance, the
correct excerpts (both the specific PTO clause and the general Section 8 clause) were
present in `cited_chunks`; the verifier had everything it needed and still misread the
relationship between the two rules.

## Observed frequency

Not rigorously measured, but from live sampling this session: roughly 1 in 3-4 runs of the
flagship "Taiwan PTO"-shaped question triggers this rejection. Re-measure against a larger
sample once a fix is attempted — this is inherently stochastic, since no `temperature`
control is available on `claude-sonnet-5` (see `CLAUDE.md` § 3).

## Risk if left unfixed

Low-severity but real reliability cost: correct answers intermittently downgrade to the
generic "I can't confirm this from the retrieved policy text alone" fallback, which is
unhelpful even though not actively wrong. Does not violate the system's core "never
fabricate" guarantee.

## Suggested fix

Add an instruction to `build_verification_prompt` teaching the verifier the
specific-carve-out-vs-general-fallback reading pattern, generalized (not hardcoded to PTO or
this specific document), with an explicit boundary clause to limit scope:

```python
"Also note: when an excerpt states a specific rule for a specific case, and separately "
"states that a different, general rule applies 'for all other' cases, the specific rule "
"is the complete and final answer for its named case — it does not need to be reconciled "
"against the general rule. This exemption applies only when the excerpt's own text "
"unambiguously covers the case in the draft; if the draft's case isn't clearly the one "
"the specific rule names, or the specific rule's own wording is unclear, that is still a "
"real ambiguity and should be flagged as UNSUPPORTED."
```

This would be appended into the existing prompt in `build_verification_prompt`
(`src/verification.py:16-28`), alongside the existing "unknown/ambiguous is SUPPORTED" note.

## Risk of the fix itself: false negatives (raised, not yet resolved)

An instruction telling the verifier "here's when to be more lenient" can over-generalize
past its intended narrow case in two ways:

1. The verifier could stop checking whether the excerpt's specific rule actually names the
   case being asked about, and wave through a draft that misapplied a specific rule meant
   for a different case. (Partially mitigated by the boundary clause above — untested.)
2. General leniency drift: an instruction permitting SUPPORTED more easily in one scenario
   could bleed into unrelated judgment calls elsewhere in the verifier's behavior.

Re-running the flagship query alone cannot detect a false-negative regression, since it only
surfaces Claude's own honestly-drafted (usually correct) answers. Testing for false
negatives requires calling `verify_answer()` directly with deliberately WRONG drafts against
the real Taiwan excerpts (cheaper and more controlled than a full agent run — one API call
per case instead of 3-5) and confirming they are still rejected after the fix:

1. `"Taiwan PTO is 10 days per year."` — fabricated number, not in any excerpt. Must still
   be UNSUPPORTED.
2. `"Taiwan PTO is 14 days, since the global handbook's more-generous rule should override
   the regional one here."` — the exact inverse of the correct reading; directly misapplies
   the general rule over an explicit specific carve-out. The sharpest test of the fix's
   directionality — should be rejected *more* confidently after the fix, not less.
3. `"Taiwan PTO is 20 days because of the special executive-tier policy."` — pure
   fabrication unrelated to the specific/general pattern at all. Control case.

## Test plan (full, for whoever picks this up)

1. **Offline:** add a test to `tests/test_verification.py` asserting the new guidance text
   is present in `build_verification_prompt`'s output (same pattern as the existing
   `test_verify_answer_prompt_includes_draft_and_excerpts`). This only proves the prompt was
   built correctly, not that the verifier's judgment actually improved.
2. **Live, false-positive check:** call `verify_answer()` (or run
   `python main.py --ask "What is the PTO policy for Taiwan PTO in 2025"` / the plain
   "Taiwan PTO" question) a meaningful number of times (5-10+, given stochasticity) before
   and after the fix; confirm the correct-draft-rejected rate goes down.
3. **Live, false-negative check (the adversarial cases above):** call `verify_answer()`
   directly with each of the 3 wrong drafts against the real cited Taiwan excerpts (pull
   them from a live `answer_question` call, or reconstruct from `index/chunks.jsonl`), both
   before and after the fix. All three must remain UNSUPPORTED after the fix. Any of the
   three flipping to SUPPORTED is a genuine regression and the fix should not ship as-is.
4. **Regression:** full offline suite (`pytest`) and full `python -m evals.eval` (8/8) after
   the fix, same discipline as every other prompt change made this session.

## Files involved

- `src/verification.py` — `build_verification_prompt()`, the actual fix location.
- `tests/test_verification.py` — offline prompt-content test.
- No changes needed to `src/agent.py` or `src/retrieval.py` for this ticket (the retrieval
  bug it was originally conflated with is already fixed in commit `b7411e4`).

## Context for whoever picks this up

This was Task 2 of a 3-task todo list from a "production readiness" edge-case testing
session (see `TRANSCRIPT.md` for the full session record). Task 1 (the retrieval fix) is
done and committed. Task 3 (a formal edge-case test matrix — entity resolution, negative
space, grounding, consistency, precedence generalization — to be written up as a plan in
`docs/superpowers/plans/`) is separate and still pending; it does not depend on this ticket
being resolved first, but the "Taiwan PTO in 2025" precedence-generalization test case in
that matrix will exercise this exact code path, so fixing this ticket before or alongside
that matrix work would avoid a known-flaky test case landing in the new suite.

## Fix implemented (2026-08-21)

Shipped as one shared addition to `build_verification_prompt` (`src/verification.py`)
covering both this ticket's specific-carve-out pattern and the sibling absence-inference
ticket's general-default pattern, rather than two incremental patches — the option both
tickets flagged as worth evaluating before implementing either in isolation:

> "(a) Specific carve-out: when an excerpt states a specific rule for a specific case, and
> separately states that a different, general rule applies 'for all other' cases, the
> specific rule is the complete and final answer for its named case — it does not need to be
> reconciled against the general rule.
> (b) General default: when an excerpt states a general rule applies to all cases unless a
> specific provision states otherwise (or equivalent wording), and no other excerpt provides
> a specific provision covering the case in question, the general rule is the complete and
> final answer for that case — the absence of a specific override does not itself need to be
> separately stated in the excerpts to be a valid basis for the conclusion.
> Both exemptions apply only when the excerpts' own wording makes the case's scope
> unambiguous — if the excerpts leave genuine doubt about which rule actually covers the case
> in the draft (not just the existence of a different rule elsewhere), that is a real
> ambiguity and should still be flagged as UNSUPPORTED."

**The false-negative risk was resolved before landing, per this ticket's own test plan**, by
running the exact 3-case adversarial battery this ticket specifies (fabricated number,
inverted precedence direction, unrelated fabrication) directly against `verify_answer()` with
the real Taiwan cited excerpts, 3 live reps each (9 calls) — every rep stayed UNSUPPORTED,
including the sharpest directionality test (a draft claiming the global "more generous" rule
overrides the regional PTO-specific carve-out — the exact inverse of the correct reading).
The sibling ticket's 3 analogous adversarial cases (California/US shape) were run alongside
these in the same battery; see that ticket for its own results. The two correct-draft
positive controls (Taiwan PTO, California PTO) stayed 4/4 SUPPORTED both before and after the
fix, so no evidence of a new false-negative was found in this sample. Regression: 59/59
offline tests pass (including a new offline test asserting the guidance text is present in
`build_verification_prompt`'s output), `python -m evals.eval` 8/8 live.

As with every prior fix in this project, a clean adversarial sample cannot *prove* the fix
never over-generalizes — it can only fail to find a counterexample in the cases tried. Revisit
if a live run ever shows `verify_answer` accepting a draft that misapplies a specific-vs-
general precedence rule.
