# BACKLOG: `verify_answer` misclassifies a correct verdict when the verifier reasons aloud

**Status:** Fixed (2026-08-22). See "Fix implemented" at the bottom.

**Discovered:** 2026-08-22, during live verification of the `submit_answer` tool-call
formatting fix (see `CLAUDE.md` decisions and `docs/TRANSCRIPT.md` § 23). Surfaced
incidentally while re-running `evals.eval`'s 8-query suite as a regression check for an
unrelated change — not something that change caused; `verify_answer.py` and
`build_verification_prompt` were not touched in that session.

**Severity:** Medium — same profile as the two related tickets: degrades reliability (a
correctly-grounded draft gets discarded and replaced with a confusing message), does not
cause fabrication. Arguably worse *presentation* than a clean rejection, though: the user
doesn't see a tidy "can't confirm this" — they see that message followed by a long, garbled
dump of the verifier's own internal reasoning, ending in a conclusion that contradicts the
framing around it.

**Related tickets:** `docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md`
and `docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md` — both
closed 2026-08-21 via a shared addition to `build_verification_prompt` teaching the verifier
to credit two inference patterns (specific carve-out; general default) as supported. This new
bug is a **different mechanism** — not the verifier reaching the wrong conclusion, but
`verify_answer`'s code misreading a *correct* conclusion because of how the response is
worded. See "Possible connection to the recent fix" below for why they may not be fully
independent.

## Summary

`verify_answer` (`src/verification.py:49`) classifies the verifier's response with:

```python
if verdict.startswith("SUPPORTED"):
    return VerifiedAnswer(text=draft, grounded=True)
```

`build_verification_prompt` instructs the verifier to "Respond with exactly 'SUPPORTED'" or
"'UNSUPPORTED: <reason>'" — but nothing enforces that literally. If the verifier reasons
through the question out loud instead of answering tersely, and its *final* conclusion is
"SUPPORTED" but the response doesn't *begin* with that word, `verify_answer` takes the
rejection branch anyway — discarding a correctly-grounded draft and replacing it with a
confusing fallback message built from the verifier's own rambling, self-contradicting text.

## Concrete example

Live query: `"What is the gym related benefits for a Taiwanese employee?"`, run via
`python -m evals.eval` (2026-08-22). The verifier's raw response (`verdict` in
`verify_answer`) was:

> "UNSUPPORTED: The excerpts establish a specific carve-out rule: PTO conflicts are governed
> by the APAC handbook, while 'For all other benefits, refer to the precedence rules in the
> global Acme Employee Handbook.' The global handbook's precedence rule states the 'more
> generous' benefit applies where there is a conflict. The draft asserts this results in the
> global $50/month rate winning over the regional $30/month rate for employees in China,
> Japan, and Taiwan — but this contradicts the 'more generous' rule itself, which would favor
> the $50/month benefit only because it's higher, which is actually consistent... however,
> the issue is that the draft presents this as the single, unqualified answer ('$50 per month
> gym reimbursement') without acknowledging that this conclusion applies specifically to APAC
> employees only via the general precedence rule, and needs the 'more generous' comparison to
> be correctly applied. Applying the general rule, $50 is indeed more generous than $30, so
> the conclusion follows correctly from the excerpts. This reasoning is actually supported as
> a valid application of the general default (b): the general precedence rule applies since
> no specific override exists for gym benefits, and under that rule, $50 (being more
> generous) wins. This is a valid supported inference.
>
> SUPPORTED"

Because this string starts with `"UNSUPPORTED:"`, `verify_answer` returned `grounded=False`
and the fallback text `"I can't confirm this from the retrieved policy text alone — the
verification check flagged: {verdict}"` — i.e. the entire rambling paragraph above, shown to
the user, despite the verifier's own final word being "SUPPORTED." The eval only "passed"
that query because `evals/matching.py`'s `"$50"` marker happened to appear inside the dumped
text — the matcher never checked that the *displayed* answer was well-formed or that
`grounded` was `True`.

**Confirmed rare, not systemic:** 3 immediate reruns of the exact same query afterward (via
`main.py --ask`) all came back clean — terse verifier response, correctly `grounded=True`,
properly formatted `verdict\n\nreason\n\n— (citation)` output. No recurrence in those 3 reps.
(No further live stress-testing was done to pin down an occurrence rate beyond this — not
worth the API spend for a fix that's an improvement regardless of the exact rate; see
"Decision," below.)

## Connection to the recent `verify_answer` fix

The gym-benefits question is exactly the "general default" pattern (pattern (b)) that the two
related tickets' shared fix taught `build_verification_prompt` to explicitly credit by name.
It's plausible that asking the verifier to explicitly reason about which of two named
patterns (a)/(b) applies increases the odds it reasons out loud on borderline cases, which is
exactly the condition that trips this bug — i.e. that fixing the two related tickets may have
made *this* bug marginally more likely, even though it fixed the (larger) problem it targeted.

**This does not need separate confirmation.** The fix below (tool-schema-constrained
classification) makes the verifier's phrasing and verbosity structurally irrelevant to
whether `verify_answer` classifies it correctly — `verdict` comes from an enum field, not
prefix-parsed prose, so it doesn't matter *why* the verifier might reason out loud, or how
often, or whether the precedence fix contributed to it. Once this fix lands, that's the
resolution: the mechanism that could make out-loud reasoning dangerous is gone, independent of
whatever caused the reasoning in the first place.

## Decision (2026-08-22)

User: skip the occurrence-rate stress test (test plan item 2 below) — the fix is worth making
regardless of how often this specific failure mode fires, and live API spend to measure a
rate isn't justified when the fix is happening either way. Proceed straight to root-cause
reproduction (an offline regression test capturing the exact bug) and implementation.

## Related, independent finding: same root-cause class as `evals/matching.py`'s known gap

`evals.eval` reported this query as passing despite `verify_answer` returning `grounded=False`
and a garbled rejection message — because `evals/matching.py`'s numeric marker check
(`_numeric_boundary_matches`) is a plain substring search over `result_text` and never
consults the `grounded` flag at all (`evals/matching.py:52-64`), so `"$50"` happening to
appear inside the dumped verifier text was enough to "pass." This is a second, independent
instance of the exact blind spot already documented in `CLAUDE.md` § 4 ("`evals/matching.py`'s
`matches()` is a substring/keyword heuristic on free-form model output... inherently
gameable") — different code path (the eval matcher, not `verify_answer` itself), same root
cause class: a heuristic that checks for a substring's *presence* rather than confirming the
text means what the check assumes it means. Worth keeping in mind together with that existing
gap if `evals/matching.py` is ever revisited — not fixed here, since it's out of scope for
this ticket's fix (which is about `verify_answer`'s classification logic, not the eval
harness), but flagged so the connection isn't lost.

## Suggested fix (sketch, not yet designed in detail)

**Primary option, recommended:** apply the same pattern just shipped for the draft answer
(`SUBMIT_ANSWER_TOOL` / `format_answer()` in `src/agent.py`, see `CLAUDE.md` decisions) to the
verifier call too — stop asking the verifier to format a classification into free text and
have it call a tool instead, with a `verdict` field constrained to an enum
(`["SUPPORTED", "UNSUPPORTED"]`) and a separate `reason` string field (used only when
`UNSUPPORTED`). This makes the classification itself a code guarantee instead of a
string-prefix guess, the same reliability upgrade already applied to answer formatting.
`verify_answer`'s own interface (`llm_call: Callable[[str], str]`, `.startswith("SUPPORTED")`)
could stay unchanged if the *implementation* of `llm_call` in `answer_question` (currently
`src/agent.py:178`) is the one that switches to tool-calling internally and constructs a
guaranteed-prefix string from the tool's fields before returning it — a minimal-diff fix that
doesn't touch `verification.py`'s tested logic at all. Would need `tool_choice` forcing the
tool, same as the answer-formatting fix.

**Cheaper alternative, not recommended without more data:** keep free text but parse more
robustly — e.g. check the *last* non-empty line/token for an unambiguous "SUPPORTED" not
preceded by "UN", instead of requiring it as the *first* word. Riskier: this project has
already hit real bugs from "clever" substring/heuristic text parsing before (`evals/matching.py`'s
numeric-boundary false-positive bug), so a regex-based fix here should get the same adversarial
scrutiny that fix got, not be assumed correct on first pass.

Do not ship either option without adversarial testing analogous to the two related tickets'
3-case batteries (a fabricated-number draft, an inverted-direction draft, an unrelated
fabrication) — the goal is fixing the parsing brittleness without accidentally making
`verify_answer` *more* lenient toward genuinely unsupported drafts.

## Test plan

1. **Root-cause reproduction first.** Feed `verify_answer()` a scripted `llm_call` fake that
   returns exactly the captured response above, and confirm it reproduces `grounded=False` —
   the offline regression test for the *bug*, TDD red step, added before the fix.
2. **Tool-based fix:** offline test that the new verifier call always returns a string
   starting with `"SUPPORTED"` or `"UNSUPPORTED"` regardless of how verbose the tool's
   `reason` field is (construct the returned string from the tool's enum-constrained
   `verdict` field in code, not from raw model text — mirrors `format_answer()`'s tests) —
   this is what makes the "reasons out loud" failure mode structurally impossible, not just
   less likely.
3. **Regression:** full offline suite and `python -m evals.eval` (8/8) after the fix, same
   discipline as every other prompt/verification change in this project. (Live stress-testing
   to measure the pre-fix occurrence rate was deliberately skipped — see "Decision," above.)

## Files involved

- `src/verification.py` — `verify_answer()`'s `.startswith("SUPPORTED")` check
  (`src/verification.py:59`) — left unchanged; the fix moved the guarantee upstream to the
  caller instead.
- `src/agent.py` — the verifier call, previously an untestable inline closure
  (`llm_call`, old `src/agent.py:178`), extracted to a standalone `verify_llm_call(client,
  prompt)` and switched to tool-calling.

## Context for whoever picks this up

Found opportunistically while live-verifying an unrelated fix (`submit_answer` tool-call
formatting, same session — see `docs/TRANSCRIPT.md` § 23).

## Fix implemented (2026-08-22)

Shipped the primary option: `verify_answer.py` was left untouched (still trusts its caller to
hand it a string starting with `"SUPPORTED"` or `"UNSUPPORTED"`), and `src/agent.py`'s
verifier call was rebuilt to guarantee that contract structurally instead of hoping the
verifier's free text happens to comply.

- Added `VERIFY_TOOL` (`report_verification`): a `verdict` field constrained to
  `enum: ["SUPPORTED", "UNSUPPORTED"]`, plus a separate `reason` string field used only when
  `UNSUPPORTED`.
- Extracted the previously-inline `llm_call` closure into a standalone, independently
  testable `verify_llm_call(client, prompt)`, which calls the verifier with
  `tool_choice={"type": "tool", "name": "report_verification"}` (forcing the tool every
  time — no free-text fallback is possible) and constructs the returned string in code from
  `block.input["verdict"]`/`block.input["reason"]`, not from raw model prose.
  `answer_question` now passes `lambda prompt: verify_llm_call(client, prompt)` to
  `verify_answer`, unchanged from `verify_answer`'s perspective.
- The "possible connection to the recent precedence fix" thread is resolved as designed, not
  separately investigated: `verdict` is read from an enum field regardless of how long or
  self-correcting the `reason` field's prose is, so it no longer matters whether that earlier
  fix increased verifier verbosity on borderline cases — verbosity can't corrupt
  classification anymore, full stop.

TDD: added `test_verify_tool_schema_constrains_verdict_to_supported_or_unsupported`,
`test_verify_llm_call_returns_supported_verdict`,
`test_verify_llm_call_returns_unsupported_verdict_with_reason`, and the direct regression test
for the reported bug shape, `test_verify_llm_call_ignores_reasoning_verbosity_in_verdict_classification`
(a long, self-correcting-looking `reason` string with `verdict: "SUPPORTED"` — asserts the
output is exactly `"SUPPORTED"`, proving verbosity can't leak into the classification), plus
`test_verify_llm_call_forces_the_verification_tool` (asserts `tool_choice` is forced to
`report_verification`). Updated the existing scripted-response test
(`test_answer_question_completes_normally_within_iteration_cap`) to script a
`report_verification` tool call for the verification step instead of a raw `"SUPPORTED"` text
block. 69/69 offline tests pass.

Live-verified per the "Decision" above (no occurrence-rate stress test — the fix is worth
shipping regardless of the pre-fix rate): 5 reps of the exact reported query (Taiwan gym
benefits) all came back cleanly formatted and correctly `grounded=True`, no misclassification
in any of them. Re-ran `evals.eval`'s 8-query suite: 8/8, including the Taiwan-gym query that
previously required the eval matcher's substring blind spot to accidentally pass.

**What this does and doesn't resolve:** the specific parsing brittleness (classification
depending on which word a free-text response happens to start with) is now structurally
impossible, not just less likely — this is a stronger guarantee than a probabilistic
improvement, which is why no stress test was needed to justify shipping it. It does not
address the separate, cross-referenced `evals/matching.py` substring-matching blind spot
(same root-cause class, different code path) — that remains open, tracked in `CLAUDE.md` § 4,
not fixed here.
