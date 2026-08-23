# BACKLOG: `verify_answer` over-rejects correct answers based on absence-inference reasoning

**Status:** Fixed (2026-08-21), then recurred twice on 2026-08-22 and given a second,
more precisely root-caused fix the same day (a third credited inference pattern, "closed-list
exclusion" — see "Second fix implemented" near the bottom). The 2026-08-21 fix addressed
patterns (a)/(b); the recurrences traced to a third, distinct pattern (c) neither covered. See
"Fix implemented" below for the original shared addition with the sibling precedence ticket,
and "Second fix implemented" for what closed the recurrences.

**Discovered:** 2026-08-20, during the initial latency-investigation session (first
reproduction, "California PTO"), and corroborated again the same day during a
production-readiness edge-case investigation (two more reproductions via `edge_cases.py`,
see below).

**Severity:** Medium — same profile as the sibling ticket below: degrades reliability
(correct answers intermittently downgrade to "can't confirm"), does not cause fabrication.

**Related, sibling ticket:** `docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md`
covers a *different* `verify_answer` weakness (misreading a specific-carve-out-vs-general-rule
precedence structure). Both share the same root shape — the verifier only reliably credits
excerpts that state an answer directly, and is unreliable when the correct answer instead
follows from the *absence* of a specific override plus a stated general/default rule. **When
picking either ticket up, consider whether a single, more general fix to
`build_verification_prompt` addresses both patterns at once, rather than two separate
incremental patches** — that's a real design option worth evaluating before implementing
either fix in isolation, not a decision already made here.

## Summary

`verify_answer` sometimes rejects a factually correct draft when the correct reasoning is:
"no excerpt specifically names/covers [jurisdiction/case X], and a general/default rule
states it applies unless a specific provision says otherwise — so the general rule governs."
The verifier sometimes treats the absence of an explicit mention of X as making the
conclusion "fabricated" or "unsupported," even when an excerpt is present that establishes
the general rule's own applicability precisely for the case of no specific override.

## Concrete examples

**Original reproduction** (documented in `CLAUDE.md` § 4, first found during the earlier
latency-investigation session): "What is the PTO allowance for a California employee?" — a
correct draft ("no regional handbook covers California, so the global default applies") was
intermittently rejected as unsupported.

**Two new reproductions**, found live via `docs/superpowers/plans/2026-08-20-production-readiness-edge-cases.md`'s
`edge_cases.py` (Task 2, commit `0891e66`):

1. "What is the PTO for a Chinese national who works remotely from California?" (expected
   `"15"`, the global default). Rejection text: *"The excerpts do not mention California,
   remote work location, or nationality as factors determining policy applicability; this
   reasoning is fabricated and not supported by the excerpts."*
2. "What is the PTO for an employee who splits time between Japan and the United States?"
   (expected `"hedge"`). Rejection text: *"no excerpt mentions the US or any US-specific PTO
   provision. The excerpts only cover global (unspecified default) and APAC (China, Japan,
   Taiwan) provisions—there is no basis for treating the US as 'the global default'
   location..."*

**A third reproduction**, found by the user running the live CLI directly (not via
`edge_cases.py`), same day: `python3 main.py --ask "What is the PTO policy a us citizen"` run
twice back-to-back produced different outcomes — a correctly-grounded "15 days" on one run,
and on the other:

> "UNSUPPORTED: The excerpts do not state that there is no regional handbook covering the
> US, nor any information about US-specific PTO policy or the absence of a regional handbook
> for the US. This claim is fabricated/inferred beyond what the excerpts support."

Same shape as the other two: the verifier demands the excerpts *state the absence* of a
regional handbook, when what actually resolves the question is the global handbook's
affirmative "applies worldwide... unless a specific provision states otherwise" clause,
which is present in the corpus and (per the other run's success) is sometimes credited and
sometimes not — pure run-to-run sampling variance on top of the same underlying prompt gap
(no `temperature` control exists on `claude-sonnet-5`; see `CLAUDE.md` § 3).

Both rejections above are wrong. The real corpus (`index/chunks.jsonl`) contains, from the
global handbook's SECTION 1:

> "It applies to all Acme personnel worldwide, including both full-time employees and
> engaged contractors, regardless of the country in which they perform their work, unless a
> specific provision states otherwise."

This excerpt is the "factor determining policy applicability" the verifier claims doesn't
exist — it directly establishes that the global default governs any location not covered by
a more specific provision, which is exactly California's and the US's status here (neither
is named by the APAC regional handbook). The verifier is either failing to retrieve/credit
this excerpt, or retrieving it but not recognizing that it resolves the "no specific
provision" case by design, not by coincidence.

## Retrieval-side update (2026-08-20, same day)

Chasing the third reproduction above (the live "US citizen" nondeterminism report) led to a
genuine, independent finding: the APAC handbook's `SCOPE` section's most directly relevant
sentence — *"Contractors and personnel outside these three jurisdictions should refer to the
global Acme Employee Handbook"* — was ranking **#19-21 of 71 total chunks** for exactly these
queries, nowhere near `SEARCH_K`. This means the root cause for the California/US shape
wasn't purely a `verify_answer` reasoning gap as originally assumed (by analogy with the
sibling precedence ticket, where that assumption held) — retrieval was also implicated, at
least for this specific paragraph.

Fixed via a manifest-driven, scoped sentence-split of just `SCOPE`
(`documents.yaml`'s `split_sentences_in_sections`) plus a `SEARCH_K` 8→10 follow-up raise —
full story in `CLAUDE.md`'s chunking decisions and `TRANSCRIPT.md` § 15. Post-fix, 5/5 live
re-tests of the "US citizen" and "California employee" shapes were correct with no
rejections (previously intermittent, roughly 1-in-3-to-1-in-2 depending on sampling).

**What this does and doesn't mean for this ticket:** it's meaningful evidence that at least
part of what looked like pure verifier flakiness was actually a retrieval gap feeding the
verifier weak evidence to begin with — worth remembering before assuming any future
absence-inference rejection is automatically this ticket's pattern. It does *not* mean
`verify_answer`'s own reasoning weakness is fixed or disproven — the mechanism described
below (the verifier under-crediting inference-from-absence claims) is a separate, real
property of the verification prompt, independent of whether retrieval happens to hand it
strong or weak supporting evidence. Any *other* absence-inference case (a different
jurisdiction, a different benefit, a future document) could still trigger it even with
perfect retrieval.

## How this bug is created (root cause, best current understanding)

Not yet root-caused as precisely as the sibling ticket's pattern — that would be the first
step for whoever picks this up. Current hypothesis, based on the two new reproductions: the
verifier's prompt (`build_verification_prompt`, `src/verification.py:16`) gives it no
guidance on how to credit a "general rule + absence of a specific override" reasoning
pattern as sufficient support, the same way the sibling ticket found no guidance for the
"specific carve-out excludes itself from a general fallback" pattern. Both are cases where
the correct answer is a valid *logical consequence* of the excerpts rather than a *direct
restatement* of them, and the verifier appears to weight direct restatement much more highly
than valid inference — even when the inference is straightforward and the excerpts
explicitly invite it (e.g., "...unless a specific provision states otherwise" is explicitly
inviting the "is there a specific provision? no? then this applies" inference).

## Suggested fix (sketch, not yet designed in detail)

By analogy with the sibling ticket's approach: add explicit guidance to
`build_verification_prompt` teaching the verifier to credit a "general/default rule +
absence of a more specific provision naming this case" chain as sufficient support, provided
the general rule's own text explicitly frames itself as a default (e.g., "applies... unless
a specific provision states otherwise," "for all other cases..."). As with the sibling
ticket, any such instruction needs a tightened boundary clause and adversarial
false-negative testing before shipping — an instruction granting the verifier more leniency
here could, in principle, make it too willing to accept a draft that claims "no specific
provision covers this" when a provision actually does exist but wasn't retrieved. Do not
implement without an adversarial test plan analogous to the sibling ticket's three-case
approach (a fabricated-number draft, a draft that inverts the correct absence-reasoning
direction, and a pure-fabrication control).

## Test plan (starting point)

1. Reproduce the two new cases above via direct `verify_answer()` calls (not the full
   agent loop) against the real cited excerpts, to confirm the mechanism precisely (does the
   worldwide-default excerpt actually reach `cited_chunks` in these cases, or is retrieval
   also a factor here? — this needs verifying before assuming it's purely a verifier-prompt
   issue, the same way the sibling ticket's Bug 1/Bug 2 conflation was untangled by direct
   reproduction with debug instrumentation).
2. Once root-caused, follow the sibling ticket's test-plan shape: offline prompt-content
   test, live false-positive re-sampling, and adversarial false-negative cases specific to
   this pattern.
3. Regression: full offline suite and `python -m evals.eval` (8/8) after any fix, same
   discipline as every other prompt change made in this project.

## Files involved

- `src/verification.py` — `build_verification_prompt()`, likely fix location (pending root
  cause confirmation per Test plan item 1).
- Possibly `src/agent.py` / `src/retrieval.py` if item 1's investigation finds retrieval
  (not verification) is actually at fault for either case — do not assume verification is
  the culprit until checked, the same way `CLAUDE.md` § 4's Bug 1/Bug 2 investigation found
  two independent causes stacking on what first looked like one bug.

## Context for whoever picks this up

Found while executing
`docs/superpowers/plans/2026-08-20-production-readiness-edge-cases.md` (Task 2). The
implementer that first hit these two failures live initially misattributed them to "corpus
boundary limitations" (i.e., that California/US data genuinely isn't answerable from this
corpus) rather than recognizing them as this bug — the controller caught and corrected this
misattribution before the task was marked complete (see that plan's SDD ledger,
`.superpowers/sdd/2026-08-20-production-readiness-edge-cases/progress.md`, for the full
correction). Do not repeat that mistake: the expected answers ("15", "hedge") for these two
cases in `edge_cases.py` are correct and grounded in the real corpus, not aspirational.

## Fix implemented (2026-08-21)

Root-caused per this ticket's own Test plan item 1 first: direct `verify_answer()` probes
against the real corpus excerpts (the global handbook's "applies to all Acme personnel
worldwide... unless a specific provision states otherwise" clause, plus the APAC SCOPE
clause pointing non-APAC personnel back to the global handbook) confirmed the correct
draft was being accepted in a small baseline sample (4/4), consistent with this pattern
being genuinely intermittent rather than a deterministic failure — matching the "roughly
1-in-3-to-1-in-2" rate this ticket already documented from live sampling, not a
contradiction of it.

Shipped as the same shared `build_verification_prompt` addition described in the sibling
precedence ticket (pattern (b) there is this ticket's general-default pattern). The 3-case
adversarial battery this ticket's "Suggested fix" section requires (a fabricated number, a
draft that inverts the correct absence-reasoning direction, and a pure-fabrication control)
was run against the real California/US excerpts, 3 live reps each:

- `california_fabricated_number` ("20 days... per the global handbook"): UNSUPPORTED all 3
  reps — the verifier correctly cited the real 15-day figure as contradicting it.
- `california_inverted_direction` ("California employees are not covered by any Acme PTO
  policy, since no handbook specifically names California"): UNSUPPORTED all 3 reps — this is
  the sharpest test of the fix's directionality, since it inverts the correct absence
  reasoning (no specific mention means the general default *does* apply, not that nothing
  applies) and the fix needed to reject it despite granting more leniency to the *correct*
  direction of the same inference pattern.
- `california_unrelated_fabrication` ("25 days... due to a state-mandated top-up"):
  UNSUPPORTED all 3 reps.

The correct California-PTO draft stayed 4/4 SUPPORTED after the fix (same as the pre-fix
baseline), so no evidence the fix changed the correct-case acceptance rate in this sample —
consistent with either a real improvement in a pattern too intermittent for a
same-day small sample to detect a rate change, or the fix simply not being exercised because
this batch's baseline was already clean; distinguishing those two would need a much larger
sample than was practical to run live in one session. Regression: 59/59 offline tests pass,
`python -m evals.eval` 8/8 live.

**What this does and doesn't resolve:** the false-negative risk this ticket and its sibling
both flagged before implementation is addressed — the adversarial battery found no case where
the fix over-generalized. It does not prove the false-*positive* rejection rate is now zero;
that would need a much larger live sample than was practical here. Watch for a recurrence the
same way the retrieval-side update below was originally caught: a live report of an
absence-inference draft (any jurisdiction, any benefit) being wrongly rejected after this fix
would mean the shared addition needs to be revisited, not that this fix failed outright.

## Recurrence observed (2026-08-22)

A full `python -m evals.edge_cases` run (part of a broader P2/gap-closing session, see
`docs/TRANSCRIPT.md`) reproduced the exact flagship case from this ticket's own "Concrete
examples" section — "What is the PTO for a Chinese national who works remotely from
California?" — rejected again:

> "UNSUPPORTED: The excerpts do not mention California, remote work, or any rule
> distinguishing work location from nationality for determining APAC handbook applicability.
> The claim that 'your work location (not your nationality) is what counts' and the scenario
> of 'working remotely from California' are not supported by any excerpt — this appears to be
> a fabricated scenario/fact not present in the provided material."

Per this ticket's own note above, this is exactly the kind of recurrence flagged as possible —
the adversarial battery proved no *over*-generalization, not that the false-positive rate
dropped to zero, and a single failure in one live run (this was 1 of 36 questions in that
`edge_cases.py` pass, unrelated to any code touched that session — `src/verification.py`'s
`build_verification_prompt()` was not modified) is consistent with the "roughly
1-in-3-to-1-in-2" intermittent rate this ticket already documented pre-fix, not proof the fix
regressed. Not re-investigated or re-fixed as part of that session (out of scope for what was
asked); flagged here per this ticket's own instruction rather than left silently unnoticed.
Whoever revisits this ticket should treat this as one more data point toward measuring the
real post-fix rate, not as a reason to assume the fix failed.

## Second fix implemented (2026-08-22): the actual root cause of the recurrence

The recurrence above, plus a second live report the same day ("California employee in 2026"
nondeterministically rejected — the flagship take-home query itself), were root-caused
properly this time via live instrumentation rather than assumed to be more of the same
"residual sampling noise." Reproducing the query 8 times with logging on every `search_handbooks`
call showed the APAC handbook's `SCOPE` excerpt (the one enumerating China/Japan/Taiwan and
saying "personnel outside these three jurisdictions should refer to the global Acme Employee
Handbook") was retrieved and cited in all 8 reps — ruling out retrieval variance as the cause.

The actual mechanism was visible directly in the user's own captured rejection text:

> "The only regional handbook provided is the APAC Benefits Handbook covering China, Japan,
> and Taiwan. The claim that 'there's no regional handbook on file covering California' is
> not supported by the excerpts..."

The verifier states the fact that proves the claim, then declines to draw the one-step
conclusion. This is a real, specific gap in `build_verification_prompt`, not irreducible
noise: patterns (a) and (b) above are anchored to specific wording ("for all other cases...",
"unless a specific provision states otherwise"), and the `SCOPE` excerpt's actual wording — an
enumerated closed list plus an explicit "everyone else, refer elsewhere" instruction — doesn't
pattern-match either trigger phrase, despite being logically at least as strong evidence as
pattern (b) requires.

Added a third credited pattern, (c) "Closed-list exclusion," with the same boundary-clause
discipline as (a)/(b) (only applies when the list is explicitly closed/exhaustive with an
explicit fallback instruction — see `src/verification.py`). Adversarially tested via a scratch
probe script (not committed) against the real cited excerpts (`SCOPE`, `CONFLICTS AND
PRECEDENCE`, the global handbook's `4.2 PTO` paragraph): the correct draft went 6/6 `SUPPORTED`
(previously intermittent — this is the same query that triggered this ticket originally and
its recurrence above); three adversarial controls at 3 reps each — an inverted-direction draft
wrongly claiming California *is* covered by the APAC closed list, a fabricated-number draft, and
an unrelated-fabrication draft — all stayed correctly `UNSUPPORTED`, 9/9, no sign the added
leniency over-generalized. End-to-end (`main.py --ask`) reconfirmed clean 4/4, and both
recurrences on this ticket (the "California 2026" report and the "Chinese national remote from
California" case) were independently reconfirmed clean 3/3 each after the fix. Regression:
80/80 offline tests pass, `python -m evals.eval` 8/8 live.

**Status: closed with higher confidence than the first fix.** This time the root cause was
directly evidenced (not inferred from a documented "roughly 1-in-3-to-1-in-2" rate), the fix
targets the exact wording gap that caused it, and the adversarial sample is comparable to the
original fix's (9 adversarial reps here vs. 18 across two patterns originally, but concentrated
on the one pattern actually changed). Standard caveat still applies: a finite live sample
cannot prove a zero rate, only that this battery found no regression.
