# Eval matcher redesign: structured expectations

**Status:** Approved design, not yet implemented. See `docs/TRANSCRIPT.md` for the
brainstorming session that produced this spec.

## Purpose

`evals/matching.py`'s `matches()` is the pass/fail judge for every live-API eval case in
`evals/eval.py` (8 take-home queries) and `evals/edge_cases.py` (36-case production-readiness
suite). Today it only understands plain keyword/substring markers (`"12"`, `"unknown"`,
`"hedge"`, or a list of these ANDed together). This has already caused or hidden real bugs
twice — a numeric marker matching inside a larger number (`"50"` inside `"$500"`), and a
`grounded`-blind-spot where numeric/hedge markers could "pass" against a rejected, ungrounded
answer if the expected marker happened to appear inside the dumped rejection reasoning by
coincidence. Both are fixed, but the underlying weakness — a keyword/substring heuristic
standing in for real semantic checks — remains, and is explicitly flagged as a known gap in
`docs/DESIGN.md`'s "Known limitations" and "Path to scale" (`#2 Eval harness rigor`).

This spec extends the matcher to deterministically check five things it can't check today:
numeric equivalence beyond raw substring, explicit-unknown vs. explicit-hedge vs. a genuinely
*rejected* (ungrounded) answer as three distinct outcomes, document/version correctness against
what was actually retrieved, and required-vs-forbidden claims as symmetric, general-purpose
per-case assertions.

## Constraints

- **Fully deterministic.** No LLM calls inside the eval harness itself. This is a deliberate
  choice, not a deferral: an LLM-judge fallback (floated in `docs/DESIGN.md`'s roadmap as one
  option) would import the same cost/latency/nondeterminism problem into the test suite that
  this project has repeatedly had to root-cause out of `verify_answer` — the harness that's
  supposed to catch that class of problem shouldn't also suffer from it.
- **Additive, not a rewrite.** The existing plain-string/list marker format
  (`"12"`, `"unknown"`, `"hedge"`, `["12", "unknown"]`) must keep working unchanged. Only eval
  cases that need one of the five new capabilities get migrated to the new structured form;
  the rest of the ~44 existing cases are untouched.
- **No text-parsing of the citation field for document/version correctness.** This project
  already moved away from parsing free-text LLM output for structural guarantees
  (`submit_answer`/`format_answer`, `report_verification`/enum) — the document/version check
  must use real retrieval metadata (`Chunk.doc: DocMeta`), not the citation string.

## Data model: `Expectation`

New dataclass in `evals/matching.py`:

```python
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
```

Every field is optional; an eval case supplies only the fields relevant to what it's checking.
All supplied checks are ANDed (matching today's compound-list semantics).

`matches(expected, result, ...)` dispatches on `type(expected)`: `str` and `list`/`tuple`
behave exactly as today; `Expectation` is a new branch. To support the new checks, `matches()`
needs access to more than `result_text` + `grounded` — see "Signature change" below.

## Splitting "unknown" from "rejected"

Today, `expected == "unknown"` is satisfied by explicit unknown-ish wording **or**
`not grounded` (`evals/matching.py:62`, the `or not grounded` clause). This conflates two
outcomes that must be told apart:

- **The system correctly determined the answer is unknown** — a *good* outcome, verdict
  reached, `grounded=True`, phrased as unknown/no-data.
- **`verify_answer` rejected a draft** — could be the safety net working correctly (draft was
  actually wrong), or could be a false-rejection bug (see the several `docs/backlog/
  verify-answer-*-false-rejection.md` tickets). Either way, it's a materially different event
  from "the system confirmed there's no data," and a case that happens to expect `"unknown"`
  should not silently "pass" when what actually happened is an unrelated verifier rejection.

`Expectation(unknown=True)` requires explicit unknown wording **and** `grounded=True`.
`Expectation(rejected=True)` requires `grounded=False` specifically — asserting that a
rejection is the *correct*, expected outcome for that case (e.g. a case deliberately
constructed to test that `verify_answer` catches a specific bad draft). Existing plain-string
`"unknown"` keeps its current, more permissive behavior unchanged (backward compatible) — the
stricter `Expectation(unknown=True)` is opt-in for cases that migrate.

## Numeric equivalence

New `_normalize_numbers(text: str) -> set[str]`, replacing the numeric branch of `matches()`'s
raw-substring-with-boundary-guard approach for `Expectation.numeric` (the plain-string numeric
path keeps today's `_numeric_boundary_matches()` behavior unchanged for backward compatibility).

Normalization handles, in order:
1. Strip `$` and thousands-separator commas/spaces: `"$1,000"`, `"1000"`, `"1 000"` → `"1000"`.
2. Map a small hardcoded word→digit table to digit strings: `one`..`twenty`, `thirty`..
   `ninety` (by tens), `hundred`, `thousand`, combined via ordinary English number-word
   composition (e.g. `"fifty"` → `"50"`, `"one thousand"` → `"1000"`). This is deliberately
   **not** a general English-number parser — scoped to the small integers this corpus's real
   answers actually use (day counts, dollar amounts up to a few thousand), consistent with
   this project's standing YAGNI norm (see `docs/backlog/` for other deliberately-scoped-down
   decisions). Numbers outside this small vocabulary are left unnormalized (matched as digits
   only) rather than guessed at.
3. Extract all number-like tokens from `result_text` this way (both raw digit runs and
   recognized word-numbers), preserving the existing digit/comma boundary guard so `"50"`
   still cannot match inside `"$500"`.

`Expectation(numeric="50")` passes if `"50"` (normalized) is among the normalized tokens
extracted from the answer text, and `grounded=True` (same grounded-gating rationale as today's
plain-string numeric/hedge checks — see "Forbidden claims" below for why).

## Document/version correctness

**Signature change:** `VerifiedAnswer` (`src/verification.py`) gains a new field:

```python
@dataclass
class VerifiedAnswer:
    text: str
    grounded: bool
    rejected_draft: str | None = None
    cited_chunks: list[Chunk] = field(default_factory=list)
```

`verify_answer()` already receives `cited_chunks` as a parameter on every call — this change
only requires including it on each of `verify_answer()`'s existing return paths (the two
deterministic-rejection paths, the LLM-verified-supported path, and the LLM-rejected path).
`agent.py`'s early-return paths (max-iterations, cut-off generation) construct `VerifiedAnswer`
directly without going through `verify_answer()` — those get `cited_chunks=cited_chunks`
(whatever was accumulated before the early return) or an empty list, matching each path's
existing semantics.

`matches()` needs the full `VerifiedAnswer` (or at least `.cited_chunks`) passed in, not just
`result_text`/`grounded` — see "Signature change" below for the call-site update.

`Expectation(doc_type="regional_handbook")` and/or `Expectation(version_year=2026)` pass if
**any** chunk in `cited_chunks` has a matching `DocMeta.doc_type`/`.version_year` — mirroring
today's "at least one match, not all" semantics for compound-question citations
(`test_verify_answer_accepts_citation_naming_one_of_several_retrieved_documents` in
`tests/test_verification.py` is the analogous precedent in `verify_answer` itself).

This is a plain equality check on real chunk metadata, not a filter — a chunk with
`version_year=None` (the evergreen APAC handbook) simply does not match a specific
`version_year=2026` expectation. Do **not** import `VectorIndex.search()`'s "`None` matches
any year filter" special-casing here (`CLAUDE.md`'s gotchas) — that rule exists for retrieval
filtering, not for asserting what was actually cited, and applying it here would let an
`Expectation(version_year=2026)` case silently pass against an APAC-only citation that never
actually confirmed 2026 applies.

## Required and forbidden claims

`Expectation.required: list[str]` is a direct generalization of today's list/tuple-of-strings
convention (each element ANDed, using the same numeric-boundary-aware substring check as
today) — available as an explicit field so it can be combined with the other new checks on the
same `Expectation` instance, not just as a bare list.

`Expectation.forbidden: list[str]`: the case fails if **any** listed string appears in
`result_text`. Gated by `grounded=True`, same as the numeric/hedge checks — a rejected draft's
dumped verifier reasoning can echo almost any text from the source excerpts while explaining
*why* something is wrong, which is not the same as the system claiming it (this exact
class of false-positive already bit numeric/hedge markers once; see
`tests/test_matching.py`'s existing grounded-gating tests for the precedent). This is a
judgment call, not a forced conclusion — noted here explicitly in case it needs revisiting once
real forbidden-claim cases are written.

## Signature change

`matches()`'s current signature is `matches(expected, result_text: str, grounded: bool) -> bool`.
New signature: `matches(expected, result: VerifiedAnswer) -> bool`, since `Expectation` checks
need `cited_chunks` in addition to `text`/`grounded`. Both call sites (`evals/eval.py`,
`evals/edge_cases.py`) already have the full `VerifiedAnswer` from `answer_question()` — they
currently unpack `.text`/`.grounded` to pass separately; this becomes `matches(expected, result)`,
slightly simpler at the call site.

## Diagnostics on failure

Both eval scripts currently print `expected marker: {exp!r}` on a failure. For a compound
`Expectation`, this is far less useful (doesn't say *which* field failed). Add a small
`explain(expected, result) -> str` in `evals/matching.py`, called only on failure, that reports
which specific sub-check(s) failed (e.g. `"numeric: expected '50', found {'30'}"`,
`"forbidden: found 'Singapore'"`, `"doc_type: expected regional_handbook, cited: global_handbook"`).
Plain string/list expectations keep today's simpler failure message unchanged.

## Migration scope

Only cases that need a new capability are rewritten to `Expectation(...)`. Planned migrations:

- `evals/edge_cases.py`'s `PRECEDENCE` category (14 cases): add `doc_type`/`version_year`
  expectations, since this category exists specifically to test precedence generalization
  across jurisdictions/years — the category best served by document/version checking.
- A small number of new `forbidden`-based cases exercising the entity-hallucination corpus gap
  from `docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md` (e.g. asserting
  `"Hong Kong"`/`"Singapore"` never appear in an APAC-jurisdiction answer).
- Any existing case whose current plain-string expectation is looser than what it's actually
  trying to verify (to be identified during implementation, not exhaustively pre-listed here).

All other existing cases keep their current plain-string/list form.

## Testing

1. New `tests/test_matching.py` cases per new capability, following the existing style
   (grounded in real captured response shapes where a precedent exists, e.g. the
   `REAL_CORRECT_RESPONSE`/`HALLUCINATED_RESPONSE` pattern already in that file).
2. Full offline suite green after implementation.
3. Live-verify with `python -m evals.eval` and `python -m evals.edge_cases` — every case that
   passes today under the old matcher must still pass under the new one (the new checks are
   strictly additive capability, not a behavior change to any case that doesn't opt into them).

## Out of scope

- LLM-judge fallback for genuinely fuzzy/semantic cases — explicitly deferred per the
  "fully deterministic" constraint above, not forgotten.
- Unit variants (e.g. "2 weeks" == "14 days") for numeric equivalence — no observed case in
  this corpus needs it; the corpus always states figures in one consistent unit per benefit.
- A corpus-wide always-on forbidden-entity blocklist (as opposed to per-case `forbidden`
  lists) — per-case is more flexible and was the explicit choice; a global blocklist can be
  layered on later if a real recurring need shows up.
