# BACKLOG: `verify_answer` over-rejects correct answers based on absence-inference reasoning

**Status:** Not started — new evidence gathered, no fix attempted yet.

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
3. Regression: full offline suite and `eval.py` (8/8) after any fix, same discipline as
   every other prompt change made in this project.

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
