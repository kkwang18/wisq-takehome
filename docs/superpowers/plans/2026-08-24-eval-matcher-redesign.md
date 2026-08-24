# Eval Matcher Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `evals/matching.py`'s matcher with a structured `Expectation` type that
deterministically checks numeric equivalence, unknown-vs-hedge-vs-rejected as distinct
outcomes, document/version correctness, and required/forbidden claims — additive alongside
today's plain string/list markers, which keep working unchanged.

**Architecture:** A new `Expectation` dataclass in `evals/matching.py` with one optional field
per new capability, ANDed when multiple are set. `matches()` gains an `isinstance(expected,
Expectation)` dispatch branch alongside its existing `str`/`list`/`tuple` handling.
Document/version checks need real retrieval metadata, so `VerifiedAnswer` (`src/verification.py`)
gains a `cited_chunks` field, threaded through every one of its construction sites in
`src/verification.py` and `src/agent.py`. A new `explain()` function gives specific,
per-sub-check failure diagnostics for `Expectation`-based cases (plain markers keep today's
simpler message).

**Tech Stack:** Python 3.9, pytest, `dataclasses`, `re`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-eval-matcher-redesign-design.md`

## Global Constraints

- Fully deterministic: no LLM/API calls anywhere inside `evals/matching.py`.
- Additive: `matches("12", result)`, `matches("unknown", result)`, `matches("hedge", result)`,
  and `matches(["12", "unknown"], result)` must all keep behaving exactly as they do today —
  every existing eval case that doesn't opt into `Expectation` is unaffected.
- Document/version checks use `Chunk.doc: DocMeta` metadata from `VerifiedAnswer.cited_chunks`
  only — never parse the citation text.
- `version_year` is a plain equality check on real cited-chunk metadata, not a filter — a
  chunk with `version_year=None` (the evergreen APAC handbook) does not match a specific
  `version_year=N` expectation. Do not import `VectorIndex.search()`'s "`None` matches any
  year filter" retrieval-time special case here.
- `forbidden` checks are gated by `grounded=True` — when `grounded=False`, the `forbidden`
  check is skipped (treated as satisfied), not failed, since a rejected draft's dumped
  verifier reasoning can echo source-excerpt text while explaining why something is wrong.
  `numeric`/`unknown`/`hedge` checks require `grounded=True` to pass at all (same as today's
  plain-marker behavior).
- Run eval scripts as `python -m evals.eval` / `python -m evals.edge_cases`, never
  `python evals/eval.py` — required for `sys.path` to resolve `ingest`/`src.*` imports (see
  `CLAUDE.md`'s gotchas). Live verification (Task 9) needs `ANTHROPIC_API_KEY` exported; Tasks
  1–8 are fully offline.
- No `temperature` param on any Claude API call (not touched by this plan's files, but a
  standing project-wide rule — see `CLAUDE.md`).

---

### Task 1: `VerifiedAnswer.cited_chunks` — thread real retrieval metadata through every return path

**Files:**
- Modify: `src/verification.py` (the `VerifiedAnswer` dataclass and all four `verify_answer()`
  return statements)
- Modify: `src/agent.py:224-228,244-248` (the two early-return `VerifiedAnswer` constructions)
- Test: `tests/test_verification.py`, `tests/test_agent.py`

**Interfaces:**
- Consumes: nothing new — `verify_answer()` already receives `cited_chunks: list[Chunk]` as a
  parameter; this task only makes it flow into the return value too.
- Produces: `VerifiedAnswer.cited_chunks: list[Chunk]` (defaults to `[]`), available to every
  caller of `answer_question()`/`verify_answer()`. Task 5 depends on this.

- [ ] **Step 1: Write the failing tests**

In `tests/test_verification.py`, update the existing equality-based test and add a new one
(both go right after the existing `test_verify_answer_passes_through_supported_draft`, which
needs its expected object updated too since it does a full dataclass equality check):

```python
def test_verify_answer_passes_through_supported_draft():
    result = verify_answer(SUPPORTED_DRAFT, [CHUNK], llm_call=lambda prompt: "SUPPORTED")
    assert result == VerifiedAnswer(text=SUPPORTED_DRAFT, grounded=True, cited_chunks=[CHUNK])


def test_verify_answer_includes_cited_chunks_on_every_return_path():
    # Empty-cited_chunks hard-fail: cited_chunks is [] going in, so it stays [] on the way out.
    result = verify_answer("some draft", [], llm_call=lambda p: "SUPPORTED")
    assert result.cited_chunks == []

    # Citation-check hard-fail: cited_chunks was non-empty, so it must still be attached even
    # though the draft itself was rejected before any LLM call.
    draft = "15 days per year.\n\nStandard global entitlement.\n\n— (Fake Handbook, Section 1)"
    result = verify_answer(draft, [CHUNK], llm_call=lambda p: "SUPPORTED")
    assert result.cited_chunks == [CHUNK]

    # LLM-rejected path.
    result = verify_answer(UNSUPPORTED_DRAFT, [CHUNK], llm_call=lambda p: "UNSUPPORTED: nope")
    assert result.cited_chunks == [CHUNK]
```

In `tests/test_agent.py`, update the two existing `answer_question` tests:

```python
def test_answer_question_stops_after_max_tool_iterations():
    client = _ScriptedClient([_search_response("call")])

    result = answer_question("What is PTO?", _StubIndex(), client=client)

    assert result.grounded is False
    assert len(client.messages.calls) == MAX_TOOL_ITERATIONS
    assert len(result.cited_chunks) == MAX_TOOL_ITERATIONS


def test_answer_question_completes_normally_within_iteration_cap():
    client = _ScriptedClient(
        [
            _search_response("call_1"),
            _submit_answer_response("call_2", "15 days per year.", "Standard global entitlement.", "Test Handbook, 4.2 PTO"),
            _verify_response("SUPPORTED"),
        ]
    )

    result = answer_question("What is PTO?", _StubIndex(), client=client)

    assert result.grounded is True
    assert result.text == "15 days per year.\n\nStandard global entitlement.\n\n— (Test Handbook, 4.2 PTO)"
    assert len(client.messages.calls) == 3
    assert len(result.cited_chunks) == 1
    assert result.cited_chunks[0].doc.display_name == "Test Handbook"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_verification.py tests/test_agent.py -v`
Expected: FAIL — `VerifiedAnswer.__init__()` doesn't accept `cited_chunks` yet, and the
`assert result.cited_chunks == ...` lines raise `AttributeError`.

- [ ] **Step 3: Add `cited_chunks` to `VerifiedAnswer` and thread it through `verify_answer()`**

In `src/verification.py`, change the import and dataclass:

```python
from dataclasses import dataclass, field
from typing import Callable

from src.models import Chunk


@dataclass
class VerifiedAnswer:
    text: str
    grounded: bool
    rejected_draft: str | None = None
    cited_chunks: list[Chunk] = field(default_factory=list)
```

Update all four `verify_answer()` return statements to include `cited_chunks=cited_chunks`:

```python
def verify_answer(draft: str, cited_chunks: list[Chunk], llm_call: Callable[[str], str]) -> VerifiedAnswer:
    if not cited_chunks:
        return VerifiedAnswer(
            text="No policy excerpts were retrieved, so this answer cannot be grounded in the handbooks.",
            grounded=False,
            cited_chunks=cited_chunks,
        )

    citation_text = _extract_citation(draft)
    if not any(c.doc.display_name in citation_text for c in cited_chunks):
        return VerifiedAnswer(
            text="The answer's citation doesn't name any of the retrieved excerpts, so this "
            "cannot be confirmed as grounded.",
            grounded=False,
            rejected_draft=draft,
            cited_chunks=cited_chunks,
        )

    prompt = build_verification_prompt(draft, cited_chunks)
    verdict = llm_call(prompt).strip()

    if verdict.upper().startswith("SUPPORTED"):
        return VerifiedAnswer(text=draft, grounded=True, cited_chunks=cited_chunks)

    fallback = (
        "I can't confirm this from the retrieved policy text alone — "
        f"the verification check flagged: {verdict}"
    )
    return VerifiedAnswer(text=fallback, grounded=False, rejected_draft=draft, cited_chunks=cited_chunks)
```

- [ ] **Step 4: Thread `cited_chunks` through `answer_question()`'s early returns**

In `src/agent.py`, update both early-return `VerifiedAnswer` constructions (the
max-iterations cap and the max-tokens cutoff):

```python
        if iterations > MAX_TOOL_ITERATIONS:
            return VerifiedAnswer(
                text="Answer generation required too many tool calls to converge; not returning a partial answer.",
                grounded=False,
                cited_chunks=cited_chunks,
            )
```

```python
        if response.stop_reason == "max_tokens":
            return VerifiedAnswer(
                text="Answer generation was cut off before completion; not returning a partial answer.",
                grounded=False,
                cited_chunks=cited_chunks,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_verification.py tests/test_agent.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests (no other file references `VerifiedAnswer(...)` by full positional/
keyword equality in a way this new field would break — confirmed by this run).

- [ ] **Step 7: Commit**

```bash
git add src/verification.py src/agent.py tests/test_verification.py tests/test_agent.py
git commit -m "$(cat <<'EOF'
Add VerifiedAnswer.cited_chunks, threaded through every return path

Groundwork for the eval matcher's document/version correctness checks
(docs/superpowers/specs/2026-08-24-eval-matcher-redesign-design.md) —
eval cases need real retrieval metadata, not citation-text parsing.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 2: `matches()` takes the full `VerifiedAnswer`, not separate `text`/`grounded` args

**Files:**
- Modify: `evals/matching.py` (the `matches()` signature and body)
- Modify: `evals/eval.py:32`, `evals/edge_cases.py:109` (call sites)
- Test: `tests/test_matching.py` (every existing test call site)

**Interfaces:**
- Consumes: `VerifiedAnswer` from `src.verification` (Task 1's `cited_chunks` field is present
  but unused until Task 5).
- Produces: `matches(expected, result: VerifiedAnswer) -> bool` — the signature every later
  task and both eval scripts build on.

- [ ] **Step 1: Rewrite `tests/test_matching.py`'s call sites to build a `VerifiedAnswer`**

Replace the whole file with this content (every call site changes from
`matches(expected, text, grounded=...)` to `matches(expected, _result(text, grounded))`; a new
`_result()` helper and a `VerifiedAnswer` import are added; nothing else about the tests'
intent changes):

```python
from __future__ import annotations

from evals.matching import matches
from src.verification import VerifiedAnswer

# Real response captured live for "Since Taiwan employees get unlimited PTO, how many sick
# days do they get?" — correctly corrects the false PTO premise (12 days, not unlimited) and
# correctly declines to state a sick-days figure, since none is given in the corpus.
REAL_CORRECT_RESPONSE = (
    "No fixed number of sick days on file — Taiwan employees don't actually get unlimited "
    "PTO (that premise is incorrect), and sick leave for Taiwan is governed by applicable "
    "local law and Acme policy rather than a set day count in the handbooks I can search.\n\n"
    "Taiwan employees get 12 days of PTO per year under the APAC Benefits Handbook, which "
    "takes precedence over the global PTO figure specifically for PTO. Sick leave isn't "
    "covered by that regional precedence rule, and the global handbook just defers to local "
    "law for the actual number of sick days, so I don't have a specific figure to give you "
    "— (APAC Benefits Handbook, Regional Benefits / Conflicts and Precedence; Acme Employee "
    "Handbook 2026, Section 4.4)"
)

# A plausible WRONG response: correctly corrects PTO to 12, but hallucinates that sick days
# also equal 12 instead of declining to answer. A single "12" marker cannot tell these two
# responses apart — that's exactly what a compound assertion is for.
HALLUCINATED_RESPONSE = (
    "12 days of sick leave per year. Taiwan employees get 12 days of PTO (not unlimited, "
    "correcting your premise), and sick leave follows the same 12-day allotment."
)


def _result(text: str, grounded: bool = True, cited_chunks=None) -> VerifiedAnswer:
    return VerifiedAnswer(text=text, grounded=grounded, cited_chunks=cited_chunks or [])


def test_single_string_expected_still_works():
    assert matches("12", _result("the figure is 12 days"))
    assert not matches("12", _result("the figure is 15 days"))


def test_unknown_marker_class_still_works():
    assert matches("unknown", _result("I don't know the answer"))
    assert not matches("unknown", _result("the figure is 12 days"))


def test_no_fixed_number_phrasing_is_recognized_as_unknown():
    assert matches("unknown", _result("There is no fixed number of sick days on file."))


def test_no_specific_number_phrasing_is_recognized_as_unknown():
    assert matches("unknown", _result("No specific number of weeks/days is on file for maternity leave in Japan."))


def test_compound_list_requires_every_condition():
    assert matches(["12", "unknown"], _result("12 days, but I don't know the rest"))
    assert not matches(["12", "unknown"], _result("12 days, all figures confirmed"))
    assert not matches(["12", "unknown"], _result("I don't know"))


def test_real_correct_response_requires_both_pto_correction_and_sick_days_decline():
    assert matches(["12", "unknown"], _result(REAL_CORRECT_RESPONSE))


def test_hallucinated_sick_days_figure_is_correctly_rejected():
    assert not matches(["12", "unknown"], _result(HALLUCINATED_RESPONSE))


def test_numeric_marker_does_not_match_inside_a_larger_dollar_figure():
    assert not matches("50", _result("The gym reimbursement is $500 per month."))
    assert not matches("$50", _result("The gym reimbursement is $500 per month."))


def test_numeric_marker_does_not_match_inside_a_larger_day_count():
    assert not matches("12", _result("Employees get 120 days of leave."))


def test_numeric_marker_does_not_match_inside_a_year():
    assert not matches("14", _result("As of 2014, the policy was different."))


def test_comma_separated_marker_does_not_match_inside_a_larger_figure():
    assert not matches("1,000", _result("The annual budget is $21,000 per year."))


def test_numeric_marker_still_matches_its_own_whole_number():
    assert matches("50", _result("The gym reimbursement is $50 per month."))
    assert matches("$50", _result("The gym reimbursement is $50 per month."))
    assert matches("12", _result("Employees get 12 days of leave."))
    assert matches("14", _result("As of 2014, the policy was 14 days."))
    assert matches("1,000", _result("The annual budget is $1,000 per year."))


def test_numeric_marker_matches_at_string_boundaries():
    assert matches("12", _result("12 days per year."))
    assert matches("12", _result("The allowance is 12"))


def test_numeric_marker_does_not_match_an_ungrounded_rejection_even_if_the_digits_appear():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: ...the global $50/month rate winning over the regional "
        "$30/month rate... SUPPORTED"
    )
    assert not matches("$50", _result(rejection_text, grounded=False))


def test_hedge_marker_does_not_match_an_ungrounded_rejection():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: it's ambiguous which country applies here..."
    )
    assert not matches("hedge", _result(rejection_text, grounded=False))


def test_numeric_and_hedge_markers_still_match_when_grounded():
    assert matches("$50", _result("The gym reimbursement is $50 per month."))
    assert matches("hedge", _result("Which specific country are you in?"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `matches()` still takes `(expected, result_text, grounded)` positionally, so
calling it with a single `_result(...)` object raises `TypeError`.

- [ ] **Step 3: Change `matches()`'s signature in `evals/matching.py`**

```python
from __future__ import annotations

import re

from src.verification import VerifiedAnswer

# Union of both files' marker lists as they stood before this extraction — eval.py had
# "no matching handbook version"/"no handbook version exists"; edge_cases.py had "no fixed
# number". Neither file loses a marker it relied on; since these are OR'd, a superset can
# only make "unknown" detection more permissive, never break a currently-passing case.
UNKNOWN_MARKERS = [
    "unknown",
    "don't have enough information",
    "do not have enough information",
    "cannot determine",
    "can't determine",
    "no reliable basis",
    "not enough information",
    "insufficient information",
    "unable to confirm",
    "can't confirm",
    "cannot confirm",
    "don't know",
    "do not know",
    "cannot answer this question with confidence",
    "can't answer this question with confidence",
    "no factual basis",
    "don't have a factual basis",
    "do not have a factual basis",
    "would require guessing",
    "avoid guessing",
    "should avoid guessing",
    "should avoid stating",
    "nothing on file",
    "no policy on record",
    "not on record",
    "no matching handbook version",
    "no handbook version exists",
    "no fixed number",
    "no specific number",
]

HEDGE_MARKERS = ["ambig", "clarif", "which country", "specific country", "unclear", "depends on"]


def _numeric_boundary_matches(marker: str, text: str) -> bool:
    """Substring match requiring non-digit, non-comma characters on both sides, so a
    numeric/currency marker like "50" or "1,000" can't match inside a larger number it
    isn't actually part of (e.g. "50" inside "$500", "1,000" inside "$21,000",
    "14" inside "2014") — confirmed live as a real false-positive risk, not theoretical."""
    pattern = r"(?<![0-9,])" + re.escape(marker) + r"(?![0-9,])"
    return re.search(pattern, text) is not None


def matches(expected, result: VerifiedAnswer) -> bool:
    # A list/tuple of conditions means ALL must hold — for a compound question that mixes a
    # false premise with a genuinely-unanswerable sub-question, a single marker can't tell a
    # correct answer from one that got the premise right by luck while hallucinating the
    # other half (see tests/test_matching.py for the live case that exposed this).
    if isinstance(expected, (list, tuple)):
        return all(matches(e, result) for e in expected)
    lowered = result.text.lower()
    if expected == "unknown":
        return any(marker in lowered for marker in UNKNOWN_MARKERS) or not result.grounded
    if expected == "hedge":
        # Unlike "unknown", a hedge/numeric expectation implies the system actually confirmed
        # the figure or ambiguity — an ungrounded rejection must never satisfy it just because
        # the rejection text happens to contain a matching word/digit by accident (a rejected
        # draft's dumped verifier reasoning can echo almost anything from the source excerpts).
        return result.grounded and any(word in lowered for word in HEDGE_MARKERS)
    return result.grounded and _numeric_boundary_matches(expected, result.text)
```

- [ ] **Step 4: Update the two eval script call sites**

In `evals/eval.py`, change:

```python
        if not matches(expected, result.text, result.grounded):
```

to:

```python
        if not matches(expected, result):
```

In `evals/edge_cases.py`, make the identical change on its `matches(expected, result.text, result.grounded)` line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests.

- [ ] **Step 7: Commit**

```bash
git add evals/matching.py evals/eval.py evals/edge_cases.py tests/test_matching.py
git commit -m "$(cat <<'EOF'
Change matches() to take the full VerifiedAnswer, not text+grounded

Pure signature refactor, no behavior change — groundwork for
Expectation-based checks that need more than text/grounded (cited_chunks,
in particular). Plain string/list markers behave identically.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 3: `Expectation` dataclass + numeric equivalence

**Files:**
- Modify: `evals/matching.py` (add `Expectation`, `_word_to_number`, `_normalize_numbers`,
  `_matches_numeric_expectation`, `_matches_expectation`, and the new dispatch branch)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `matches(expected, result: VerifiedAnswer) -> bool` (Task 2).
- Produces: `Expectation` dataclass (all eight fields — later tasks fill in the unimplemented
  ones' checks, but the shape is fixed here so no later task changes the dataclass itself);
  `_matches_expectation(expectation: Expectation, result: VerifiedAnswer) -> bool`, which
  Tasks 4–6 extend by adding more `if` blocks (never renamed or restructured).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching.py` (the `Expectation, _word_to_number, matches` import at the
top of the file is updated in a separate step below — don't add another import line here):

```python
def test_word_to_number_handles_small_and_compound_phrases():
    assert _word_to_number("fifty") == "50"
    assert _word_to_number("one thousand") == "1000"
    assert _word_to_number("twelve") == "12"
    assert _word_to_number("not a number") is None


def test_expectation_numeric_matches_plain_digit():
    assert matches(Expectation(numeric="50"), _result("The gym reimbursement is $50 per month."))


def test_expectation_numeric_matches_currency_formatting_variant():
    assert matches(Expectation(numeric="$1,000"), _result("The annual budget is $1000 per year."))


def test_expectation_numeric_matches_spelled_out_number():
    assert matches(Expectation(numeric="12"), _result("Employees get twelve days of PTO per year."))


def test_expectation_numeric_does_not_match_wrong_figure():
    assert not matches(Expectation(numeric="50"), _result("The gym reimbursement is $30 per month."))


def test_expectation_numeric_does_not_match_inside_a_larger_number():
    assert not matches(Expectation(numeric="50"), _result("The gym reimbursement is $500 per month."))


def test_expectation_numeric_requires_grounded():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: ...the global $50/month rate..."
    )
    assert not matches(Expectation(numeric="50"), _result(rejection_text, grounded=False))
```

Change the top import line from `from evals.matching import matches` to
`from evals.matching import Expectation, _word_to_number, matches` (testing the "private"
`_word_to_number` helper directly matches this file's existing style of testing internal
helpers alongside public behavior — see `_numeric_boundary_matches`'s lack of a direct test
only because it has no branching logic of its own; `_word_to_number` does, so it gets one).
Remove the separate `from evals.matching import Expectation, _word_to_number` line shown in
the test block above — it's redundant with this single updated import.

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `Expectation` and `_word_to_number` don't exist yet (`ImportError`).

- [ ] **Step 3: Implement `Expectation`, number normalization, and the numeric check**

Add to `evals/matching.py` (after the `HEDGE_MARKERS` list, before `_numeric_boundary_matches`):

```python
from dataclasses import dataclass, field


@dataclass
class Expectation:
    numeric: str | None = None
    unknown: bool = False
    hedge: bool = False
    rejected: bool = False
    required: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    doc_type: str | None = None
    version_year: int | None = None


_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000}

_WORD_NUMBER_PATTERN = re.compile(
    r"\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|thousand)[\s-]*)+\b",
    re.IGNORECASE,
)
_NUMBER_TOKEN_PATTERN = re.compile(r"[0-9][0-9,]*")


def _word_to_number(phrase: str) -> str | None:
    """Convert a small English number phrase (e.g. "fifty", "one thousand") to a digit
    string, or None if `phrase` isn't a recognized number word/phrase. Deliberately scoped to
    the small integers this corpus's real answers use (day counts, dollar amounts up to a few
    thousand) — not a general English-number parser."""
    words = phrase.lower().replace("-", " ").split()
    if not words:
        return None
    total = 0
    current = 0
    for word in words:
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word in _SCALES:
            current = (current or 1) * _SCALES[word]
            if _SCALES[word] == 1000:
                total += current
                current = 0
        else:
            return None
    return str(total + current)


def _normalize_numbers(text: str) -> set[str]:
    """Extract every number-like token from `text`, normalized: `$`/commas stripped from
    digit runs, and small English number words/phrases converted to their digit-string
    equivalent via `_word_to_number`."""
    found = set()
    for match in _NUMBER_TOKEN_PATTERN.finditer(text.replace("$", "")):
        digits = match.group().replace(",", "")
        if digits:
            found.add(digits)
    for match in _WORD_NUMBER_PATTERN.finditer(text):
        number = _word_to_number(match.group())
        if number is not None:
            found.add(number)
    return found


def _matches_numeric_expectation(numeric: str, result: VerifiedAnswer) -> bool:
    if not result.grounded:
        return False
    expected_normalized = _normalize_numbers(numeric)
    if not expected_normalized:
        return False
    return bool(expected_normalized & _normalize_numbers(result.text))


def _matches_expectation(expectation: Expectation, result: VerifiedAnswer) -> bool:
    if expectation.numeric is not None:
        if not _matches_numeric_expectation(expectation.numeric, result):
            return False
    return True
```

Then add the dispatch branch as the first check in `matches()`:

```python
def matches(expected, result: VerifiedAnswer) -> bool:
    if isinstance(expected, Expectation):
        return _matches_expectation(expected, result)
    if isinstance(expected, (list, tuple)):
        return all(matches(e, result) for e in expected)
    ...
```

(Leave the rest of `matches()`'s body — the `str`/`list` handling — exactly as Task 2 left it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add evals/matching.py tests/test_matching.py
git commit -m "$(cat <<'EOF'
Add Expectation and numeric equivalence to the eval matcher

First piece of the structured-expectation redesign
(docs/superpowers/specs/2026-08-24-eval-matcher-redesign-design.md):
numeric markers now tolerate currency/comma formatting and small
spelled-out numbers, deterministically, via a scoped word-number table —
not a general English-number parser.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 4: `unknown` / `hedge` / `rejected` as distinct outcomes

**Files:**
- Modify: `evals/matching.py` (`_matches_expectation`)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `Expectation`, `_matches_expectation` (Task 3).
- Produces: nothing new for later tasks — this and Task 3 together make every non-doc/version,
  non-required/forbidden field of `Expectation` functional.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching.py`:

```python
def test_expectation_unknown_requires_grounded_and_explicit_wording():
    assert matches(Expectation(unknown=True), _result("There is no fixed number of sick days on file."))
    assert not matches(Expectation(unknown=True), _result("12 days per year."))


def test_expectation_unknown_does_not_count_an_ungrounded_rejection():
    # The key gap this splits from today's plain "unknown" marker (which is satisfied by
    # `not grounded` alone): a verifier rejection must not silently pass as if the system had
    # correctly determined the answer is unknown.
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: the draft's figure isn't stated in the excerpts."
    )
    assert not matches(Expectation(unknown=True), _result(rejection_text, grounded=False))


def test_expectation_hedge_requires_grounded_and_hedge_wording():
    assert matches(Expectation(hedge=True), _result("Which specific country are you in?"))
    assert not matches(Expectation(hedge=True), _result("15 days per year."))


def test_expectation_rejected_requires_grounded_false():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: the draft wrongly claims $30 applies."
    )
    assert matches(Expectation(rejected=True), _result(rejection_text, grounded=False))
    assert not matches(Expectation(rejected=True), _result("15 days per year."))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `Expectation(unknown=True)`/`hedge=True`/`rejected=True` are accepted by the
dataclass but `_matches_expectation` doesn't check them yet, so `matches()` returns `True`
unconditionally for these expectations (the negative-case assertions fail).

- [ ] **Step 3: Extend `_matches_expectation`**

```python
def _matches_expectation(expectation: Expectation, result: VerifiedAnswer) -> bool:
    if expectation.numeric is not None:
        if not _matches_numeric_expectation(expectation.numeric, result):
            return False
    if expectation.unknown:
        if not (result.grounded and any(marker in result.text.lower() for marker in UNKNOWN_MARKERS)):
            return False
    if expectation.hedge:
        if not (result.grounded and any(word in result.text.lower() for word in HEDGE_MARKERS)):
            return False
    if expectation.rejected:
        if result.grounded:
            return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add evals/matching.py tests/test_matching.py
git commit -m "$(cat <<'EOF'
Split unknown/hedge/rejected into distinct Expectation outcomes

Expectation(unknown=True) now requires grounded=True and explicit
wording — unlike the plain "unknown" marker, a verifier rejection can no
longer silently satisfy it. Expectation(rejected=True) is the new,
explicit way to assert a rejection is the correct expected outcome.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 5: Document/version correctness against real `cited_chunks`

**Files:**
- Modify: `evals/matching.py` (`_matches_expectation`)
- Modify: `tests/test_matching.py` (`_result()` helper gains `cited_chunks` support — already
  written into Task 2's version of the helper, so this task only adds fixtures and tests)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `VerifiedAnswer.cited_chunks` (Task 1), `Expectation`/`_matches_expectation`
  (Task 3).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching.py`:

```python
from src.models import Chunk, DocMeta

_GLOBAL_DOC = DocMeta(file="g.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Acme Employee Handbook 2026")
_APAC_DOC = DocMeta(file="a.docx", doc_type="regional_handbook", jurisdictions=["China", "Japan", "Taiwan"], version_year=None, display_name="APAC Benefits Handbook")
_GLOBAL_CHUNK = Chunk(text="Standard PTO is 15 days.", section_title="4.2 PTO", doc=_GLOBAL_DOC)
_APAC_CHUNK = Chunk(text="Regional PTO is 12 days.", section_title="Regional Benefits", doc=_APAC_DOC)


def test_expectation_doc_type_matches_any_cited_chunk():
    result = _result("12 days per year.", cited_chunks=[_GLOBAL_CHUNK, _APAC_CHUNK])
    assert matches(Expectation(doc_type="regional_handbook"), result)


def test_expectation_doc_type_fails_when_no_cited_chunk_matches():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    assert not matches(Expectation(doc_type="regional_handbook"), result)


def test_expectation_version_year_matches_any_cited_chunk():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    assert matches(Expectation(version_year=2026), result)


def test_expectation_version_year_none_does_not_match_a_specific_year():
    # The evergreen APAC handbook's version_year=None must not satisfy a specific-year
    # expectation — a plain equality check on real chunk metadata, not the
    # VectorIndex.search() "None matches any year filter" retrieval-time special case.
    result = _result("12 days per year.", cited_chunks=[_APAC_CHUNK])
    assert not matches(Expectation(version_year=2026), result)


def test_expectation_doc_type_and_version_year_combine_with_numeric():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    assert matches(Expectation(numeric="15", doc_type="global_handbook", version_year=2026), result)
    assert not matches(Expectation(numeric="15", doc_type="global_handbook", version_year=2025), result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `doc_type`/`version_year` are accepted by `Expectation` but unchecked, so the
negative-case assertions fail.

- [ ] **Step 3: Extend `_matches_expectation`**

```python
def _matches_expectation(expectation: Expectation, result: VerifiedAnswer) -> bool:
    if expectation.numeric is not None:
        if not _matches_numeric_expectation(expectation.numeric, result):
            return False
    if expectation.unknown:
        if not (result.grounded and any(marker in result.text.lower() for marker in UNKNOWN_MARKERS)):
            return False
    if expectation.hedge:
        if not (result.grounded and any(word in result.text.lower() for word in HEDGE_MARKERS)):
            return False
    if expectation.rejected:
        if result.grounded:
            return False
    if expectation.doc_type is not None:
        if not any(c.doc.doc_type == expectation.doc_type for c in result.cited_chunks):
            return False
    if expectation.version_year is not None:
        if not any(c.doc.version_year == expectation.version_year for c in result.cited_chunks):
            return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add evals/matching.py tests/test_matching.py
git commit -m "$(cat <<'EOF'
Add doc_type/version_year checks against real cited_chunks metadata

Checks any cited chunk's DocMeta, not the citation text — no
citation-string parsing involved. version_year is a plain equality
check, not a filter: the evergreen APAC handbook's version_year=None
never matches a specific-year expectation.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 6: Required and forbidden claims

**Files:**
- Modify: `evals/matching.py` (`_matches_expectation`)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `Expectation`/`_matches_expectation` (Task 3), `_numeric_boundary_matches` (already
  existing, from before this plan).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching.py`:

```python
def test_expectation_required_and_forbidden_together():
    text = "12 days per year. Taiwan is covered by the APAC regional handbook."
    assert matches(Expectation(required=["12", "Taiwan"], forbidden=["Singapore"]), _result(text))


def test_expectation_required_fails_when_a_term_is_missing():
    text = "12 days per year."
    assert not matches(Expectation(required=["12", "Taiwan"]), _result(text))


def test_expectation_required_uses_numeric_boundary_matching():
    assert not matches(Expectation(required=["50"]), _result("The gym reimbursement is $500 per month."))


def test_expectation_forbidden_fails_when_term_present():
    text = "The APAC handbook covers China, Japan, Taiwan, and Singapore."
    assert not matches(Expectation(forbidden=["Singapore"]), _result(text))


def test_expectation_forbidden_is_skipped_on_an_ungrounded_rejection():
    # Same false-positive-risk rationale as the existing numeric/hedge grounded-gating: a
    # rejected draft's dumped verifier reasoning can echo almost any text from the source
    # excerpts while explaining why something is wrong — that's not the system claiming it.
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: the draft wrongly named Singapore as covered."
    )
    assert matches(Expectation(forbidden=["Singapore"]), _result(rejection_text, grounded=False))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `required`/`forbidden` are accepted by `Expectation` but unchecked.

- [ ] **Step 3: Extend `_matches_expectation`**

```python
def _matches_expectation(expectation: Expectation, result: VerifiedAnswer) -> bool:
    if expectation.numeric is not None:
        if not _matches_numeric_expectation(expectation.numeric, result):
            return False
    if expectation.unknown:
        if not (result.grounded and any(marker in result.text.lower() for marker in UNKNOWN_MARKERS)):
            return False
    if expectation.hedge:
        if not (result.grounded and any(word in result.text.lower() for word in HEDGE_MARKERS)):
            return False
    if expectation.rejected:
        if result.grounded:
            return False
    if expectation.doc_type is not None:
        if not any(c.doc.doc_type == expectation.doc_type for c in result.cited_chunks):
            return False
    if expectation.version_year is not None:
        if not any(c.doc.version_year == expectation.version_year for c in result.cited_chunks):
            return False
    if expectation.required:
        if not all(_numeric_boundary_matches(term, result.text) for term in expectation.required):
            return False
    if expectation.forbidden and result.grounded:
        if any(term in result.text for term in expectation.forbidden):
            return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add evals/matching.py tests/test_matching.py
git commit -m "$(cat <<'EOF'
Add required/forbidden claim checks to Expectation

forbidden is gated by grounded=True: an ungrounded rejection's dumped
verifier reasoning can echo source-excerpt text while explaining why a
draft is wrong, which isn't the same as the system claiming it — so the
check is skipped (not failed) when grounded=False.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 7: `explain()` diagnostics, wired into both eval scripts' failure output

**Files:**
- Modify: `evals/matching.py` (add `explain()`)
- Modify: `evals/eval.py`, `evals/edge_cases.py` (failure collection and printing)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: everything from Tasks 3–6 (`Expectation`, `_matches_numeric_expectation`,
  `_numeric_boundary_matches`, `UNKNOWN_MARKERS`, `HEDGE_MARKERS`, `_normalize_numbers`).
- Produces: `explain(expected, result: VerifiedAnswer) -> str`, used by both eval scripts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching.py`:

```python
from evals.matching import explain


def test_explain_reports_plain_marker_unchanged():
    assert explain("12", _result("15 days")) == "expected marker: '12'"


def test_explain_reports_numeric_mismatch():
    msg = explain(Expectation(numeric="50"), _result("The gym reimbursement is $30 per month."))
    assert "numeric" in msg
    assert "50" in msg


def test_explain_reports_forbidden_term_found():
    msg = explain(Expectation(forbidden=["Singapore"]), _result("Covers China, Japan, Taiwan, and Singapore."))
    assert "forbidden" in msg
    assert "Singapore" in msg


def test_explain_reports_doc_type_mismatch():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    msg = explain(Expectation(doc_type="regional_handbook"), result)
    assert "doc_type" in msg
    assert "regional_handbook" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `explain` doesn't exist yet (`ImportError`).

- [ ] **Step 3: Implement `explain()` in `evals/matching.py`**

```python
def explain(expected, result: VerifiedAnswer) -> str:
    """Human-readable reason `expected` didn't match `result`, for eval-failure printing.
    Only meaningful to call when matches(expected, result) is already False."""
    if not isinstance(expected, Expectation):
        return f"expected marker: {expected!r}"

    reasons = []
    if expected.numeric is not None and not _matches_numeric_expectation(expected.numeric, result):
        found = _normalize_numbers(result.text)
        reasons.append(f"numeric: expected {expected.numeric!r}, found {found or 'no numbers'}")
    if expected.unknown and not (result.grounded and any(m in result.text.lower() for m in UNKNOWN_MARKERS)):
        reasons.append("unknown: expected explicit unknown wording with grounded=True")
    if expected.hedge and not (result.grounded and any(w in result.text.lower() for w in HEDGE_MARKERS)):
        reasons.append("hedge: expected explicit hedge wording with grounded=True")
    if expected.rejected and result.grounded:
        reasons.append("rejected: expected grounded=False")
    if expected.doc_type is not None and not any(c.doc.doc_type == expected.doc_type for c in result.cited_chunks):
        cited = {c.doc.doc_type for c in result.cited_chunks}
        reasons.append(f"doc_type: expected {expected.doc_type!r}, cited {cited or 'nothing'}")
    if expected.version_year is not None and not any(c.doc.version_year == expected.version_year for c in result.cited_chunks):
        cited = {c.doc.version_year for c in result.cited_chunks}
        reasons.append(f"version_year: expected {expected.version_year!r}, cited {cited or 'nothing'}")
    if expected.required:
        missing = [t for t in expected.required if not _numeric_boundary_matches(t, result.text)]
        if missing:
            reasons.append(f"required: missing {missing}")
    if expected.forbidden and result.grounded:
        present = [t for t in expected.forbidden if t in result.text]
        if present:
            reasons.append(f"forbidden: found {present}")
    return "; ".join(reasons) if reasons else "expectation did not match (no specific sub-check failure detected)"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_matching.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Wire `explain()` into `evals/eval.py`**

Change the import and the failure-collection/printing:

```python
from evals.matching import explain, matches
```

```python
    for question, expected in EXPECTED:
        result = answer_question(question, index)
        print(f"Q: {question}\n{result.text}\n{'-' * 80}")
        if not matches(expected, result):
            failures.append((question, expected, result))

    if failures:
        print(f"\n{len(failures)} of {len(EXPECTED)} queries did not match expectations:")
        for q, exp, result in failures:
            print(f"  Q: {q}\n  {explain(exp, result)}\n  got: {result.text}\n")
        sys.exit(1)
```

- [ ] **Step 6: Wire `explain()` into `evals/edge_cases.py`**

Same change: `from evals.matching import matches` → `from evals.matching import explain,
matches`; `failures.append((category, question, expected, result.text))` →
`failures.append((category, question, expected, result))`; and the failure-printing loop:

```python
    if failures:
        print(f"\n{len(failures)} of {total} edge cases did not match expectations:")
        for cat, q, exp, result in failures:
            print(f"  [{cat}] Q: {q}\n  {explain(exp, result)}\n  got: {result.text}\n")
        sys.exit(1)
```

- [ ] **Step 7: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests.

- [ ] **Step 8: Commit**

```bash
git add evals/matching.py evals/eval.py evals/edge_cases.py tests/test_matching.py
git commit -m "$(cat <<'EOF'
Add explain() for per-sub-check Expectation failure diagnostics

Both eval scripts now print which specific check failed (numeric,
doc_type, forbidden, etc.) instead of just the opaque expected-marker
repr — a compound Expectation failure was previously undiagnosable from
the eval script's own output alone.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 8: Migrate `PRECEDENCE` to `Expectation`, add an entity-hallucination-guard category

**Files:**
- Modify: `evals/edge_cases.py` (`PRECEDENCE` list, new `ENTITY_HALLUCINATION_GUARD` list,
  `CATEGORIES` dict, import line)

**Interfaces:**
- Consumes: `Expectation` (Task 3).
- Produces: nothing — this is a leaf task, data-only, verified live in Task 9.

- [ ] **Step 1: Update the import**

Change `from evals.matching import explain, matches` to
`from evals.matching import Expectation, explain, matches`.

- [ ] **Step 2: Rewrite `PRECEDENCE`**

Replace the existing `PRECEDENCE` list with:

```python
# Precedence generalization: full cross-product across every APAC country and every
# benefit-type/year combination this corpus supports — proving the logic isn't
# Taiwan-specific is this category's entire point, so it does NOT collapse to one
# representative. Also re-exercises the version_year retrieval fix (commit b7411e4) across
# China/Japan, not just Taiwan. Each case now also asserts *which* document/version actually
# governed the answer (Expectation.doc_type/.version_year against real cited_chunks), not just
# the resulting figure — catching a case that gets the right number for the wrong reason.
PRECEDENCE = [
    ("What is the PTO for an employee based in China in 2025?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in China in 2026?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in China?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in Japan in 2025?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in Japan in 2026?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in Japan?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in Taiwan in 2025?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in Taiwan in 2026?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the PTO for an employee based in Taiwan?", Expectation(numeric="12", doc_type="regional_handbook")),
    ("What is the gym benefit for an employee based in China?", Expectation(numeric="50", doc_type="global_handbook", version_year=2026)),
    ("What is the gym benefit for an employee based in Japan?", Expectation(numeric="50", doc_type="global_handbook", version_year=2026)),
    ("What is the gym benefit for an employee based in Taiwan?", Expectation(numeric="50", doc_type="global_handbook", version_year=2026)),
    ("What is the annual conference and training budget for an employee based in China?", Expectation(numeric="1,000", doc_type="global_handbook", version_year=2026)),
    ("What is the annual conference and training budget for an employee based in Japan?", Expectation(numeric="1,000", doc_type="global_handbook", version_year=2026)),
    ("What is the annual conference and training budget for an employee based in Taiwan?", Expectation(numeric="1,000", doc_type="global_handbook", version_year=2026)),
]
```

- [ ] **Step 3: Add `ENTITY_HALLUCINATION_GUARD`**

Add this new list right after `PRECEDENCE`:

```python
# Entity hallucination guard: correct answers about APAC-jurisdiction questions must never
# invent named jurisdictions the corpus doesn't cover. docs/backlog/2026-08-20-draft-time-
# named-entity-hallucination.md: a draft once fabricated "Hong Kong/Singapore" as APAC-covered
# countries, neither of which appears anywhere in the corpus — verify_answer caught it that
# time, but the fix (a SYSTEM_PROMPT restriction) has only 7 live reproductions behind it.
# These cases give that fix ongoing, structural regression coverage.
ENTITY_HALLUCINATION_GUARD = [
    ("What is the PTO allowance for an employee living in Asia?", Expectation(hedge=True, forbidden=["Hong Kong", "Singapore"])),
    ("What countries does the APAC regional handbook cover?", Expectation(required=["China", "Japan", "Taiwan"], forbidden=["Hong Kong", "Singapore"])),
]
```

- [ ] **Step 4: Register the new category**

Update `CATEGORIES`:

```python
CATEGORIES = {
    "entity_resolution": ENTITY_RESOLUTION,
    "negative_space": NEGATIVE_SPACE,
    "grounding": GROUNDING,
    "consistency": CONSISTENCY,
    "precedence": PRECEDENCE,
    "entity_hallucination_guard": ENTITY_HALLUCINATION_GUARD,
}
```

- [ ] **Step 5: Sanity-check the file imports cleanly**

Run: `source .venv/bin/activate && python -c "import evals.edge_cases"`
Expected: no output, exit code 0 (confirms no syntax errors and every `Expectation(...)` call
is well-formed — this file's actual behavior can only be verified live, in Task 9).

- [ ] **Step 6: Run the full offline suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests (this task doesn't touch any file `tests/` covers, but confirms
nothing else broke).

- [ ] **Step 7: Commit**

```bash
git add evals/edge_cases.py
git commit -m "$(cat <<'EOF'
Migrate PRECEDENCE to Expectation, add entity-hallucination-guard cases

PRECEDENCE cases now assert which document/version actually governed
the answer, not just the resulting figure. New category gives the
named-entity-hallucination SYSTEM_PROMPT fix
(docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md)
ongoing structural regression coverage instead of relying on manual
live re-testing.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

---

### Task 9: Live verification

**Files:** none (verification only; fixes here go back into whichever task's files if a real
bug turns up)

**Interfaces:**
- Consumes: the fully assembled system from Tasks 1–8.
- Produces: a pass/fail report. This task's job is to confirm the redesign didn't regress
  anything real, and to root-cause (not just re-run) any genuine failure — never a plain
  string/list case, since Task 2's refactor is behavior-preserving by construction and Tasks
  3–6 are purely additive.

- [ ] **Step 1: Run `evals.eval`**

Run: `source .venv/bin/activate && ANTHROPIC_API_KEY=<key> python -m evals.eval`
Expected: `All 8 queries matched expectations.` (`EXPECTED` in `evals/eval.py` is untouched
plain-string data — this run's real purpose is confirming `VerifiedAnswer.cited_chunks` and
the new `matches()`/`explain()` signatures work correctly against live API responses, not
just the offline fakes in `tests/test_agent.py`.)

If it fails: read the `explain()` output (still just `expected marker: ...` for these
untouched plain-string cases) and the full answer text. A failure here most likely means a
live LLM sampling-variance issue unrelated to this plan (this project's history has several —
see `docs/backlog/`) rather than a bug in this change; cross-check against `git diff` before
concluding either way, the same discipline used for every other `verify_answer`-adjacent
change in this project (see `docs/TRANSCRIPT.md`).

- [ ] **Step 2: Run `evals.edge_cases`**

Run: `source .venv/bin/activate && ANTHROPIC_API_KEY=<key> python -m evals.edge_cases`
Expected: all 38 cases pass (36 original + 2 new `ENTITY_HALLUCINATION_GUARD` cases), or any
failures are ones already diagnosed as known, documented flakiness in `docs/backlog/`
(cross-check `explain()`'s output and the category against those tickets before assuming a
failure is new).

For any failure in `precedence` or `entity_hallucination_guard` specifically (the two
categories this plan added new check types to): use `explain()`'s output to determine whether
it's a real system bug (fix at its source, not in the matcher) or a case that needs
adjusting because the live answer's citation shape doesn't match what was assumed when writing
Task 8's `Expectation` values (e.g. a case genuinely does need both the 2025 *and* 2026 global
handbook cited for some compound reason not anticipated) — if the latter, adjust that specific
case's `Expectation` in `evals/edge_cases.py`, re-run, and note the adjustment's reasoning in
a code comment next to the case, matching this file's existing style (see the "Republic of
China" case's comment for precedent).

- [ ] **Step 3: Final full regression**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: PASS, all tests (should already be true from every prior task's Step — this is the
final confirmation after any live-driven adjustments in Steps 1–2).

- [ ] **Step 4: Commit any live-driven adjustments**

Only if Steps 1–2 required changing an `Expectation` value in `evals/edge_cases.py`:

```bash
git add evals/edge_cases.py
git commit -m "$(cat <<'EOF'
Adjust <case description> Expectation after live verification

<one sentence: what the live run showed and why the adjustment is correct>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EkLiocR6ZJ2LirgKcvwmAp
EOF
)"
```

If no adjustments were needed, no commit for this task — Tasks 1–8's commits already cover
everything, and this task's Steps 1–3 are pure verification with nothing new to record in git.

---

## Plan self-review notes

- **Spec coverage:** numeric equivalence → Task 3; unknown/hedge/rejected split → Task 4;
  document/version correctness → Tasks 1 + 5; required/forbidden → Task 6; diagnostics
  (spec's "Diagnostics on failure" section) → Task 7; migration scope → Task 8; testing →
  Task 9. Every spec section maps to at least one task.
- **Placeholder scan:** no TBD/TODO; every code step shows complete, real code; no task
  references a function/type not defined in an earlier task (`_matches_expectation` is
  introduced once in Task 3 and only ever extended, never redefined from scratch).
- **Type consistency:** `Expectation`'s eight fields are all declared once, in Task 3, and
  never renamed; `matches(expected, result: VerifiedAnswer) -> bool` and
  `explain(expected, result: VerifiedAnswer) -> str` keep identical signatures from the task
  that introduces each through the rest of the plan.
