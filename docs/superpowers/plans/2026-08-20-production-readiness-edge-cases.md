# Production-Readiness Edge Case Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-tier edge-case test suite covering five production-readiness
categories — entity resolution, negative space, grounding, consistency, and precedence
generalization — validated against the real Acme handbook corpus, not synthetic fixtures.

**Architecture:** Tier 1 is a new offline pytest file
(`tests/test_retrieval_entity_resolution.py`) exercising `VectorIndex.search()` directly
against the persisted real corpus with lexically-varied queries (typos, casing,
abbreviations, naming traps) — zero API calls, real embeddings, same pattern as the existing
`test_retrieval_recall.py`. Tier 2 is a new live-API acceptance script (`edge_cases.py`,
sibling to `eval.py`, same `_matches()`-heuristic pattern) covering all 5 categories
end-to-end through `answer_question()`. Kept separate from `eval.py` so the take-home's
8-query acceptance gate stays fast and cheap; this suite is explicitly run-on-demand given
its live API cost (~36 questions × 3-5 Claude calls each).

**Tech Stack:** Python, pytest, `sentence-transformers` (offline), `anthropic` SDK (live),
existing `src/retrieval.py` / `src/agent.py` — no new dependencies.

**Spec:** No separate written spec doc — the spec is the conversation itself. See
`TRANSCRIPT.md` § 13 for the full scoping discussion and case-selection rule below.

## Global Constraints

- **Case-selection rule** (agreed with the user): full cross-product only for precedence
  generalization (3 APAC countries × {PTO, gym, conference budget}, plus PTO × 3 year
  conditions), since proving the logic isn't Taiwan-specific is that category's entire
  point. Every other category gets one representative case per distinct failure
  *mechanism*, not per jurisdiction — testing the same lexical-variation mechanism (typo,
  casing, abbreviation) against multiple jurisdictions adds no signal, since it exercises
  the same code path each time.
- **Grounded in the real corpus, not synthetic fixtures.** Every expected answer below is
  derived from the actual document text (dumped and read from `index/chunks.jsonl` earlier
  in this session), not invented. Key facts this plan relies on:
  - APAC regional handbook: PTO = 12 days, gym = $30/month, blanket across China/Japan/Taiwan
    (no per-country figures), evergreen (no yearly editions).
  - APAC excludes contractors and scopes coverage by "based in and working from," not
    nationality (`SCOPE` section).
  - APAC's PTO precedence clause carves PTO out of the global "more generous" rule
    (`CONFLICTS AND PRECEDENCE` section) — regional 12 days controls even though it's less
    generous than global.
  - Global handbook: PTO = 14 days (2025) / 15 days (2026), gym = $50/month, conference/
    training budget = $1,000/year (Section 5.2, mentioned only in the global handbook — no
    APAC-specific provision exists for it at all).
  - Sick leave, parental/bereavement/jury-duty leave, and notice periods are all deferred to
    "applicable local law" in the global handbook with **no specific number given anywhere**
    in any of the three documents.
- **No mocks for live cases.** Tier 2 hits the real Claude API, same as `eval.py` — this is
  deliberate (see `eval.py`'s design rationale in `CLAUDE.md` § 2).
- **`ANTHROPIC_API_KEY` must be exported before running Tier 2** — same requirement as
  `eval.py`/`main.py`.
- **This is not classic red/green TDD for Tier 2.** `edge_cases.py` is a live acceptance
  script like `eval.py`, not unit-testable code with a deterministic pass/fail cycle before
  implementation exists — there's no "implementation" to write, only cases to run against
  the already-built system. Tier 1 *is* classic TDD (offline, deterministic, real
  embeddings, against code that already exists and either does or doesn't behave correctly).
- **The version_year retrieval bug (commit `b7411e4`) and the verify_answer precedence bug
  (`docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md`) are both already
  known.** The precedence-generalization cases in Task 2 will re-exercise both code paths
  across China/Japan (not just Taiwan) — expect the backlog bug to surface intermittently
  there too until it's fixed. Do not treat that as a new finding; cross-reference the
  existing ticket instead of re-diagnosing it.

---

## File Structure

- `tests/test_retrieval_entity_resolution.py` (new) — Tier 1, offline retrieval-robustness
  tests against the real persisted `index/`.
- `edge_cases.py` (new, project root, sibling to `eval.py`) — Tier 2, live full-agent
  acceptance script covering all 5 categories.

---

### Task 1: Offline entity-resolution retrieval tests

**Files:**
- Create: `tests/test_retrieval_entity_resolution.py`
- Test: this file IS the test (Tier 1 has no separate implementation to write — it tests
  existing retrieval behavior against the real corpus)

**Interfaces:**
- Consumes: `VectorIndex.load(dir_path)` and `SEARCH_K` from `src/retrieval.py` (both
  existing, unchanged)
- Produces: nothing consumed by later tasks — Tier 1 and Tier 2 are independent

- [ ] **Step 1: Write the test file**

```python
from __future__ import annotations

import pytest

from src.retrieval import SEARCH_K, VectorIndex


@pytest.fixture(scope="module")
def index():
    return VectorIndex.load("index")


def _section_titles(results):
    return [r.chunk.section_title for r in results]


def test_lowercase_jurisdiction_still_surfaces_regional_pto(index):
    results = index.search("what is the pto for an employee based in taiwan", k=SEARCH_K)
    assert any("REGIONAL BENEFITS" in t or "CONFLICTS AND PRECEDENCE" in t for t in _section_titles(results))


def test_typo_jurisdiction_still_surfaces_regional_pto(index):
    results = index.search("What is the PTO for an employee based in Tiawan?", k=SEARCH_K)
    assert any("REGIONAL BENEFITS" in t or "CONFLICTS AND PRECEDENCE" in t for t in _section_titles(results))


def test_country_abbreviation_still_surfaces_regional_scope(index):
    results = index.search("What is the gym benefit for an employee in the PRC?", k=SEARCH_K)
    assert any("SCOPE" in t or "REGIONAL BENEFITS" in t for t in _section_titles(results))


def test_alternate_country_name_still_surfaces_regional_scope(index):
    results = index.search("What is the PTO for an employee based in the Republic of China?", k=SEARCH_K)
    assert any("SCOPE" in t or "REGIONAL BENEFITS" in t for t in _section_titles(results))


def test_contractor_exclusion_clause_is_retrievable(index):
    results = index.search("Does the APAC handbook cover contractors?", k=SEARCH_K)
    assert any("SCOPE" in t for t in _section_titles(results))
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_retrieval_entity_resolution.py -v`

Expected: all pass against the real, persisted `index/`. If any fail, that's a genuine
retrieval-quality gap (not a fixture bug, since this hits the real corpus) — root-cause it
via `superpowers:systematic-debugging` before proceeding. Do not loosen an assertion to make
it pass; a failure here means `SEARCH_K`, the embedding model, or `embed_text()`'s
contextual header genuinely needs adjustment (same class of fix as the original `SEARCH_K`
5→8 change documented in `CLAUDE.md` § 3).

- [ ] **Step 3: If any test fails, root-cause and fix before proceeding**

- [ ] **Step 4: Commit**

```bash
git add tests/test_retrieval_entity_resolution.py
git commit -m "Add offline entity-resolution retrieval robustness tests"
```

---

### Task 2: Live full-agent edge-case acceptance script

**Files:**
- Create: `edge_cases.py`

**Interfaces:**
- Consumes: `answer_question(question, index, client=None) -> VerifiedAnswer` from
  `src/agent.py` (existing, unchanged), `build_index(manifest_path)` from `ingest.py`
  (existing, unchanged)
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write `edge_cases.py`**

```python
from __future__ import annotations

import os
import sys

from ingest import build_index
from src.agent import answer_question

# Entity resolution: one representative case per distinct lexical/semantic mechanism, not
# per jurisdiction — typo/casing/abbreviation exercise the same retrieval code path
# regardless of which jurisdiction they're pointed at, so testing multiple adds no signal.
ENTITY_RESOLUTION = [
    ("what is the pto for an employee based in taiwan", "12"),
    ("What is the PTO for an employee based in Tiawan?", "12"),
    ("What is the gym benefit for an employee in the PRC?", "50"),
    ("What is the PTO for an employee based in the Republic of China?", "12"),
    ("What is the PTO for a Chinese national who works remotely from California?", "15"),
    ("What is the PTO for a contractor based in Taiwan?", "15"),
    ("What is the PTO for an employee who splits time between Japan and the United States?", "hedge"),
]

# Negative space: false premises and never-mentioned benefits.
NEGATIVE_SPACE = [
    ("Since Taiwan employees get unlimited PTO, how many sick days do they get?", "12"),
    ("Why is the California-specific gym reimbursement only $75/month?", "50"),
    ("What is Acme's signing bonus policy?", "unknown"),
    ("How many days of parental leave does a Japan-based employee get?", "unknown"),
]

# Grounding: plausible-sounding questions with zero supporting text anywhere in the corpus.
GROUNDING = [
    ("What is Acme's 401(k) matching policy?", "unknown"),
    ("How many sick days does a Taiwan-based employee get?", "unknown"),
    ("What is the maternity leave duration for a Japan employee?", "unknown"),
]

# Consistency: paraphrases of two already-known-good canonical questions must converge on
# the identical verdict.
CONSISTENCY = [
    ("How many vacation days does someone based in Taiwan get?", "12"),
    ("I'm in Taiwan — what's my PTO?", "12"),
    ("Taiwan PTO allowance?", "12"),
    ("PTO days for Taiwan-based staff?", "12"),
    ("Gym reimbursement for a California employee?", "50"),
    ("I work out of California, what's the fitness benefit?", "50"),
    ("What's the wellness or gym perk for someone in CA?", "50"),
]

# Precedence generalization: full cross-product across every APAC country and every
# benefit-type/year combination this corpus supports — proving the logic isn't
# Taiwan-specific is this category's entire point, so it does NOT collapse to one
# representative. Also re-exercises the version_year retrieval fix (commit b7411e4) across
# China/Japan, not just Taiwan.
PRECEDENCE = [
    ("What is the PTO for an employee based in China in 2025?", "12"),
    ("What is the PTO for an employee based in China in 2026?", "12"),
    ("What is the PTO for an employee based in China?", "12"),
    ("What is the PTO for an employee based in Japan in 2025?", "12"),
    ("What is the PTO for an employee based in Japan in 2026?", "12"),
    ("What is the PTO for an employee based in Japan?", "12"),
    ("What is the PTO for an employee based in Taiwan in 2025?", "12"),
    ("What is the PTO for an employee based in Taiwan in 2026?", "12"),
    ("What is the PTO for an employee based in Taiwan?", "12"),
    ("What is the gym benefit for an employee based in China?", "50"),
    ("What is the gym benefit for an employee based in Japan?", "50"),
    ("What is the gym benefit for an employee based in Taiwan?", "50"),
    ("What is the annual conference and training budget for an employee based in China?", "1,000"),
    ("What is the annual conference and training budget for an employee based in Japan?", "1,000"),
    ("What is the annual conference and training budget for an employee based in Taiwan?", "1,000"),
]

CATEGORIES = {
    "entity_resolution": ENTITY_RESOLUTION,
    "negative_space": NEGATIVE_SPACE,
    "grounding": GROUNDING,
    "consistency": CONSISTENCY,
    "precedence": PRECEDENCE,
}


def _matches(expected: str, result_text: str, grounded: bool) -> bool:
    lowered = result_text.lower()
    if expected == "unknown":
        unknown_markers = [
            "unknown", "don't have enough information", "do not have enough information",
            "cannot determine", "can't determine", "no reliable basis", "not enough information",
            "insufficient information", "unable to confirm", "can't confirm", "cannot confirm",
            "don't know", "do not know", "cannot answer this question with confidence",
            "can't answer this question with confidence", "no factual basis",
            "don't have a factual basis", "do not have a factual basis", "would require guessing",
            "avoid guessing", "should avoid guessing", "should avoid stating",
            "nothing on file", "no policy on record", "not on record",
        ]
        return any(marker in lowered for marker in unknown_markers) or not grounded
    if expected == "hedge":
        return any(
            word in lowered
            for word in ["ambig", "clarif", "which country", "specific country", "unclear", "depends on"]
        )
    return expected in result_text


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Export it before running: export ANTHROPIC_API_KEY=sk-...")

    index = build_index("documents.yaml")
    failures = []
    total = 0

    for category, cases in CATEGORIES.items():
        print(f"\n{'=' * 80}\n{category.upper()}\n{'=' * 80}")
        for question, expected in cases:
            total += 1
            result = answer_question(question, index)
            print(f"Q: {question}\n{result.text}\n{'-' * 80}")
            if not _matches(expected, result.text, result.grounded):
                failures.append((category, question, expected, result.text))

    if failures:
        print(f"\n{len(failures)} of {total} edge cases did not match expectations:")
        for cat, q, exp, got in failures:
            print(f"  [{cat}] Q: {q}\n  expected marker: {exp!r}\n  got: {got}\n")
        sys.exit(1)

    print(f"\nAll {total} edge cases matched expectations.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it live**

Run: `export ANTHROPIC_API_KEY=sk-... && python edge_cases.py`

Expected: some failures on the first run are likely and informative, not necessarily a bug
in the script — this is genuinely new coverage (particularly negative-space and grounding,
which no prior test exercises). Root-cause each failure via
`superpowers:systematic-debugging` before deciding whether it's a real `SYSTEM_PROMPT`/
`verify_answer` gap or a marker-matching gap in `_matches()` (same distinction made
throughout this session's live-run fixes — see `CLAUDE.md` § 4 on `eval.py`'s matcher
brittleness, which applies identically here). Cross-reference the known bugs listed in
Global Constraints before treating a precedence-category failure as new.

- [ ] **Step 3: Fix any real gaps found, re-run until stable**

Follow the same discipline as every other live-tested change this session: full offline
suite + a live re-run after each fix, one variable at a time, evidence before claiming a fix
works.

- [ ] **Step 4: Commit**

```bash
git add edge_cases.py
git commit -m "Add production-readiness edge-case acceptance suite"
```

---

## Self-Review

**Spec coverage:** entity resolution ✓ (Task 1 offline + Task 2 `ENTITY_RESOLUTION`),
negative space ✓ (`NEGATIVE_SPACE`), grounding ✓ (`GROUNDING`), consistency ✓
(`CONSISTENCY`), precedence generalization ✓ (`PRECEDENCE`, full cross-product per the
scoping rule).

**Placeholder scan:** none — every case has a concrete question and expected marker; both
tasks have complete code, not descriptions of code.

**Type consistency:** `edge_cases.py` reuses `answer_question`'s exact existing signature
and `VerifiedAnswer`'s `.text`/`.grounded` fields, matching `eval.py`'s established usage —
no new types introduced.
