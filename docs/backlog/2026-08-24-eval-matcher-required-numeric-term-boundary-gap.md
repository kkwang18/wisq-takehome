# BACKLOG: `Expectation.required`'s word-boundary matcher reopens a numeric-prefix false positive for numeric-shaped terms

**Status:** Open, not fixed — deliberately deferred, low priority. Found during the final
whole-branch review of `docs/superpowers/plans/2026-08-24-eval-matcher-redesign.md`. No current
eval case triggers this; it's a latent gap, not an active bug.

**Discovered:** 2026-08-24, final review of the eval-matcher redesign branch, as a follow-up
observation on the Task 9 fix (see `docs/superpowers/plans/2026-08-24-eval-matcher-redesign.md`'s
SDD ledger for that fix's full root-cause account).

**Severity:** Low. Purely an eval-harness precision gap on a field (`required`) whose only
current real-world use (`ENTITY_HALLUCINATION_GUARD`) uses word terms (`"China"`, `"Japan"`,
`"Taiwan"`), never short numeric ones.

## Summary

Task 9 fixed a real bug: `Expectation.required`'s original implementation reused
`_numeric_boundary_matches()` (designed to protect numeric markers like `"50"` from matching
inside a larger number like `"$500"`), whose comma-exclusion also blocked an ordinary word
immediately followed by a comma in prose (e.g. `"China"` in `"...China, Japan, and Taiwan."`).
The fix introduced a new, purpose-built `_term_boundary_matches()` using plain `\b`
word-boundary regex instead, deliberately **not** modifying `_numeric_boundary_matches` itself
(to avoid regressing the ~44 live eval cases that function protects).

The final reviewer confirmed this fix is correct for every current use, but also verified a
narrow tradeoff it reopens: `_numeric_boundary_matches`'s comma-exclusion protects a specific
case `\b` word-boundaries do not — a short numeric marker matching as a false prefix of a
larger comma-grouped number, when nothing else blocks it. Confirmed directly:

```python
>>> _term_boundary_matches("1", "budget is 1,234 dollars")
True   # "1" incorrectly matches inside "1,234"
>>> _numeric_boundary_matches("1", "budget is 1,234 dollars")
False  # correctly blocked
```

`\b` treats a comma as a non-word character, so it counts as a boundary — but a comma acting as
a thousands-separator is still semantically "inside" the number, not a real boundary. Plain
word terms (`"China"`, `"Japan"`) don't have this issue since they're never followed by a
digit-implying comma pattern; only `required` terms that are themselves number-like are
affected.

## Investigation

No current `Expectation.required` value in either `evals/eval.py` or `evals/edge_cases.py` is
a short (1-2 digit) numeric string, so this gap has zero live impact today. It's flagged now
purely because it's a real, confirmed asymmetry between `required`'s new matcher and the
long-standing `_numeric_boundary_matches` guarantee every plain-string numeric marker still
gets — worth closing before someone adds a numeric `required` term near a comma-grouped larger
number and hits a silent false positive.

## Suggested fix (sketch, not implemented)

Dispatch inside `required`'s matching loop based on whether each individual term looks
numeric, rather than redesigning either boundary function:

```python
def _is_numeric_term(term: str) -> bool:
    return term.replace(",", "").replace("$", "").isdigit()

# inside the required check:
for term in expectation.required:
    matcher = _numeric_boundary_matches if _is_numeric_term(term) else _term_boundary_matches
    if not matcher(term, result.text):
        ...
```

This gets each term the boundary rule appropriate to its own shape — numeric terms keep full
comma protection, word terms keep comma-tolerant prose matching — without touching either
existing function or its test coverage. Estimated small, low-risk change; the main cost is
writing adversarial tests for both directions (a numeric `required` term near a comma-grouped
number; a word `required` term immediately followed by a comma) before shipping, per this
project's standing discipline for anything touching shared matching logic.

## Test plan (once picked up)

1. `Expectation(required=["1"])` against `"budget is 1,234 dollars"` must NOT match (the gap
   this ticket describes).
2. `Expectation(required=["China"])` against `"...China, Japan..."` must still match (the
   Task 9 fix's original case — must not regress).
3. Full offline suite green; no live-API verification needed (this is pure regex-boundary
   logic, no LLM sampling variance involved).

## Files involved

- `evals/matching.py` — `_check_expectation()`'s `required` block, and both `_term_boundary_matches`/
  `_numeric_boundary_matches`, the likely fix location.
- `tests/test_matching.py` — new adversarial tests per the test plan above.
