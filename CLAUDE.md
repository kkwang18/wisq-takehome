# CLAUDE.md

## 1. Project summary

A RAG Q&A CLI over three Acme HR handbook `.docx` files (a take-home deliverable). Core
constraint: **retrieve, don't stuff** — answers must come from chunked/embedded/searched
excerpts, never full documents pasted into the prompt — and **never fabricate**: every claim
must cite a retrieved excerpt, and the system must explicitly answer `unknown` or hedge
rather than guess when the excerpts don't resolve the question. The hard cases are
version conflicts (2025 vs 2026 global handbook), regional precedence (APAC overrides global
for PTO only, not other benefits), and jurisdiction ambiguity ("Asia" vs the three countries
an APAC handbook actually covers).

## 2. Architecture

```
documents.yaml → ingest.py → index/{chunks.jsonl,embeddings.npy}
                                        ↓
question → main.py / evals.eval → src/agent.py (Claude + search tool loop) → src/verification.py → answer
```

- `documents.yaml` — declares each source doc's metadata (`doc_type`, `jurisdictions`,
  `version_year`, `active`). Add/deprecate a document here, not in code.
- `src/docx_reader.py` — reads `word/document.xml` directly (stdlib `zipfile` +
  `ElementTree`), no `python-docx`.
- `src/chunking.py` — one non-empty paragraph = one chunk, tagged with nearest preceding
  heading. `HEADING_STYLES = {"Compact", "Heading2"}` + a `MAX_HEADING_LENGTH = 60` guard.
  `DocMeta.split_sentences_in_sections` (set via `documents.yaml`) opts specific sections of
  a specific document into sentence-level splitting instead — a deliberate, manifest-driven,
  per-section exception, not a corpus-wide default. See decisions below for why it's scoped
  this narrowly.
- `src/retrieval.py` — `embed_text()` (contextual header + chunk text),
  `VectorIndex` (build/save/load/search, local `sentence-transformers`, plain numpy, no
  vector DB), `SEARCH_K = 10` (shared constant, also imported by `src/agent.py` — raised from
  8, see decisions below).
  `preload_model()` starts the `SentenceTransformer` load on a background thread;
  `_get_model()` joins it before first use — see decisions below.
- `src/agent.py` — `answer_question()`: Claude + a `search_handbooks` tool, multi-hop
  (calls the tool as many times as needed), `MODEL = "claude-sonnet-5"`. No `temperature`
  param anywhere (rejected by this model). Main loop leaves adaptive thinking on
  (`max_tokens=8000`); the verification call disables thinking (`max_tokens=1000`). Calls
  `index.preload_model()` first thing, so the local embedding model loads on a background
  thread concurrently with the first Claude round-trip instead of blocking after it.
- `src/verification.py` — `verify_answer()`: hard-fails (`grounded=False`, no LLM call) if
  `cited_chunks` is empty; otherwise asks the LLM to check the draft against only the cited
  excerpts. `VerifiedAnswer.rejected_draft` preserves a downgraded draft (currently unread
  by any caller).
- `ingest.py` — `build_index(manifest_path)`, and a CLI that persists to `index/`.
- `main.py` — CLI: no args runs the 8 take-home example queries, `--ask "..."` runs one.
- `evals/` — live-API acceptance scripts, grouped separately from the `main.py`/`ingest.py`
  product CLI since they're QA tooling, not app usage — run as `python -m evals.eval` /
  `python -m evals.edge_cases` (not `python evals/eval.py`, so `sys.path` resolves
  `ingest`/`src.*` imports the same way `pytest.ini`'s `pythonpath = .` already does for
  tests). Neither is named `test_*.py` nor lives in `tests/`, so `pytest` never runs them.
  - `evals/matching.py` — shared `matches(expected, result_text, grounded)` used by both
    eval scripts (extracted from what were two independently-drifting copies — see decisions
    below). Numeric/currency markers (`"12"`, `"$50"`, `"1,000"`) require non-digit,
    non-comma characters on both sides, so a marker can't match inside a larger number it
    isn't actually part of (`"50"` no longer matches inside `"$500"`). `"unknown"`/`"hedge"`
    markers do substring/keyword matching against the shared `UNKNOWN_MARKERS`/
    `HEDGE_MARKERS` lists; a list/tuple `expected` requires every element to match (AND
    semantics, for compound questions — see gaps below).
  - `evals/eval.py` — the 8 take-home example queries against a fresh `build_index`, not the
    persisted `index/`.
  - `evals/edge_cases.py` — sibling to `evals/eval.py`, same pattern, but a much larger
    production-readiness suite: 36 cases across entity resolution, negative space,
    grounding, consistency, and precedence generalization. Kept separate from `eval.py` so
    the take-home's 8-query gate stays fast/cheap — run this one on demand, not on every
    commit (real API cost: ~36 questions × 3-5 Claude calls each).
- `tests/` — offline only (real local embeddings, zero API calls, zero mocks).
  `test_retrieval_recall.py` checks real-corpus retrieval quality against the take-home's
  actual queries — this is the regression guard for chunking/embedding/`k` changes.
  `test_retrieval_entity_resolution.py` does the same against lexically-varied queries
  (typos, casing, abbreviations, alternate country names) — the offline half of the
  `edge_cases.py` production-readiness suite. `test_matching.py` tests `evals/matching.py`'s
  `matches()` function directly — the one place in the test suite that gets automated,
  zero-cost regression coverage of the *test harness's own correctness*, not just the system
  under test; add a case here whenever `matches()` changes, the same way any other logic
  change gets a test.
- `docs/backlog/` — deferred, fully-investigated tasks a future session can pick up cold:
  root cause, suggested fix, risk, and test plan already written up, not just a one-line
  TODO. Check here before starting new work in case it's already been diagnosed.

## 3. Key decisions and why

- **Raw XML instead of `python-docx`.** The handbooks' section headers live inside
  single-cell "banner" tables; `python-docx`'s `Document.paragraphs` silently skips
  table-nested content and would drop every header.
- **One-paragraph-per-chunk instead of header-regex splitting.** The two global handbooks
  use `pStyle="Compact"` for real headers; the APAC handbook uses `pStyle="Heading2"` — no
  shared convention. Worse, APAC's "LOCAL LAW PROVISIONS" section has 5 real body paragraphs
  that *also* use `Compact`, which a naive style-only rule misclassified as headings and
  silently dropped. Fixed with the length guard, not per-document special-casing.
- **Contextual embedding headers + structured `doc_type`/`version_year` search filters.**
  The 2025 and 2026 PTO paragraphs are nearly word-for-word identical except the day count —
  nothing in the raw text says which version it is, so embedding similarity alone can't
  reliably disambiguate. `embed_text()` prepends doc metadata before embedding; the search
  tool also exposes explicit filters so Claude can narrow structurally once it's resolved a
  year/jurisdiction, not just hope similarity gets it right.
- **`SEARCH_K` raised twice from an original 5, now 10** (see the chunking-investigation
  decision below for the second raise, 8→10). The first raise (5→8) came from the
  real-corpus recall test: the APAC scope paragraph (naming the 3 covered countries) ranked
  7th of 13 for a jurisdiction query — an adjacent generic continuation paragraph outranked
  it. This is a live-system risk, not just a test-tuning issue, so `k` is one shared constant
  used by both `src/agent.py` and the recall tests.
- **No `temperature` param on any Claude call; verification call disables thinking.**
  `claude-sonnet-5` rejects non-default sampling params (400). It also runs adaptive
  thinking by default when `thinking` is omitted, and thinking tokens count against the same
  `max_tokens` ceiling as text — a low `max_tokens` on the verification call was silently
  returning empty text and downgrading every answer. Both only surfaced on the first live
  API run, late in the build (no key was available earlier).
- **Ambiguity hedging is decoupled from whether the final number would differ.** Originally
  the hedge rule only fired if different candidate jurisdictions gave different figures — but
  "gym benefits in Asia" converges to $50 regardless of country, and the model sometimes
  answered definitively instead of asking which country, which isn't the take-home's
  expected behavior. The rule now hedges on the ambiguity itself.
- **Answers were tightened to 2-4 sentences, citing only the 1-2 determinative excerpts**,
  after live runs showed multi-paragraph answers padded with disclaimers about things not
  asked (statutory minimums, other jurisdictions) and offers to "search further" after the
  answer was already determined. Retrieval, precedence reasoning, and `verify_answer` logic
  were intentionally left untouched — this was a phrasing/scope change only.
- **`preload_model()` runs on a background thread, not a system-prompt instruction to
  batch tool calls.** Both were tried as latency fixes for the ~5-10s per-answer time.
  Measured directly: `import sentence_transformers` costs ~3.35s and the first
  `SentenceTransformer` instantiation costs ~2.81s — a ~6.2s one-time cost per process that,
  before this fix, blocked on the *first* `search_handbooks` tool call rather than
  overlapping with the Claude round-trip that precedes it. A system-prompt nudge to have
  Claude batch multiple `search_handbooks` calls into one turn was also tried, but a live
  ablation (0/4 failures with the nudge reverted vs. 2/4 with it in place, same query run
  repeatedly) showed it destabilized `verify_answer` on absence-based inference questions
  (e.g. "no regional handbook covers California, so the global default applies" — a
  legitimate inference the verifier only sometimes accepted) — almost certainly because the
  nudge made the model treat one batched round of searches as a stopping signal. Reverted;
  not worth trading correctness for an unconfirmed latency win. The remaining per-question
  latency is dominated by sequential Claude API round-trips (the multi-hop tool loop plus a
  separate verification call), which is an intentional grounding trade-off, not a bug — see
  the no-hallucination requirement above.
- **Prompt caching investigated and shelved, not implemented.** `SYSTEM_PROMPT` alone is 934
  tokens — under Sonnet 5's 1024-token cache minimum; only `SYSTEM_PROMPT` + `SEARCH_TOOL`
  together (1501 tokens) clears it. A live timing breakdown showed 97% of per-question time
  is Claude round-trip time dominated by thinking/generation, not input reprocessing, so
  caching this prefix would save a small amount of cost, not the latency that motivated
  investigating it — and `verify_answer`'s call sends no `system`/`tools` at all, so it can't
  benefit regardless. Revisit if call volume or system-prompt size grows materially.
- **Final answers follow a rigid three-part structure** — verdict first (the number, or the
  closest thing to one), one short plain-language reason (the rule/version that determined
  it), then a trailing citation tag — written like a text message from HR, not a memo. The
  verdict-first ordering needed two rounds of live-tested strengthening (an explicit
  WRONG/RIGHT example, then generalized from "no regional handbook" specifically to any
  absence reasoning, including "no matching year") before it held reliably; some residual
  variance across live runs looks like model sampling noise rather than a rule gap, since the
  same query was clean in one run and violated in another with identical instructions.
- **`VectorIndex.search()`'s `version_year` filter treats `version_year=None` as "matches
  any year filter,"** not "matches only when no filter is given." The APAC regional handbook
  has no yearly editions (it's evergreen), so a question naming both a region and a year
  (e.g. "Taiwan PTO in 2025") could otherwise silently exclude the regional precedence
  clause from a year-filtered search call — reproduced live, and at least once caused a
  genuinely wrong draft answer, not just a slow one. Global-handbook year disambiguation
  (2025 vs 2026, which have real distinct years) is unaffected.
- **Sentence-level chunking is a manifest-driven, per-section opt-in
  (`split_sentences_in_sections`), not a corpus-wide default — because a corpus-wide version
  was tried and reverted.** A live nondeterminism report traced back to a real retrieval gap:
  the APAC handbook's `SCOPE` section merges its coverage statement with its exclusion/
  referral clause into one chunk, diluting the exclusion clause's embedding enough to rank
  #19-21 of 71 chunks for out-of-APAC PTO questions ("US citizen," "California employee").
  Splitting every paragraph in the corpus into sentence-level chunks was tried first — it
  nearly doubled total chunk count (71→136) and, worse, *regressed* an already-passing
  retrieval-quality test (`test_apac_scope_is_retrievable_to_rule_out_california`) while not
  even clearly fixing the target queries (their rank got worse for 2 of 3, not better) — more
  fragments were competing for a fixed `SEARCH_K`. Reverted. Two prototypes (one on the real
  `SCOPE` text, one synthetic) then confirmed an LLM chunker's differentiating value (sub-
  sentence splitting, cross-paragraph merging) is real but wasn't needed for this specific
  fix — the LLM's actual boundary decisions on `SCOPE` were identical to plain sentence-
  splitting. The fix that shipped: scope sentence-splitting to just `SCOPE` via
  `documents.yaml`'s `split_sentences_in_sections` (73 chunks, not 136), which fixed the
  target queries without the corpus-wide regression. `SEARCH_K` still needed raising 8→10
  afterward — splitting `SCOPE` grew the regional-handbook chunk count 13→15, which pushed a
  *different* chunk (the country-list sentence) to a new near-tie at rank #9 — the same
  pattern as the original 5→8 fix, now recurring at the new boundary. LLM-assisted
  (semantic) chunking is documented as a deferred backlog item for when the corpus actually
  grows past what syntactic rules can safely assume — see
  `docs/backlog/2026-08-20-llm-assisted-semantic-chunking.md`. Full investigation, including
  both prototypes' exact results: `docs/TRANSCRIPT.md` § 15.
- **`SYSTEM_PROMPT` explicitly forbids naming any entity not verbatim in a retrieved
  excerpt, not just figures.** A live user report showed a draft claiming the APAC handbook's
  jurisdictions were "Hong Kong/Singapore/etc." — confirmed via direct corpus check that
  neither name appears anywhere in `index/chunks.jsonl` (the real scope is China, Japan,
  Taiwan). `verify_answer` correctly rejected the draft, so this never reached the user, but
  it was a genuine draft-time fabrication (inventing entities never retrieved at all), not a
  retrieval mix-up or a `verify_answer` misreading — a different bug class from the two
  `verify_answer` tickets below. Likely cause: pretrained knowledge of "typical APAC hubs"
  leaking through despite the existing outside-knowledge instruction, which was scoped to
  figures/norms and didn't name entities explicitly. Fix is purely restrictive (no
  false-negative risk, unlike the `verify_answer` tickets), so it was added directly rather
  than deferred; 7 live reproductions (3 before, 4 after) all came back correctly grounded,
  but that sample is too small to prove the fix against a rare (~1-in-4-ish) event. Full
  writeup: `docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md`.
- **`VectorIndex` stays plain `numpy`, not a real vector DB — verified live, not assumed.**
  Following the chunking fix, a full Chroma+hybrid-search prototype was built against the
  real 73-chunk corpus (dense embeddings identical to today's, plus a hand-rolled BM25 pass
  fused via Reciprocal Rank Fusion) and run against a 10-query battery deliberately including
  adversarial cases (a paraphrase-only query with zero shared keywords with its source text;
  the one remaining untested "general rule + exception" merged-chunk candidate from the
  `SCOPE` investigation). Result: `numpy` == Chroma-dense == Chroma-hybrid on all 10 — no
  case where the current system misses and hybrid catches it, at this corpus's current size.
  Full design (schema, indexing, filtering — including the same `version_year=None`-as-
  sentinel fix the chunking work required — and document lifecycle) written up as a backlog
  ticket, ready to implement without re-investigation once the corpus actually grows large
  enough to need it: `docs/backlog/2026-08-20-vector-db-migration-for-scale.md`.

- **`evals/eval.py` and `evals/edge_cases.py`'s independently-drifting `_matches()` copies
  were extracted into a shared `evals/matching.py`.** The two copies had already diverged
  (only `edge_cases.py` supported compound list/tuple assertions; only `eval.py` had two
  marker strings `edge_cases.py` lacked) — merged as the union of both marker lists (strictly
  additive, since markers are OR'd for "unknown" detection, so a superset can only catch more
  real phrasings, never break a case that passed before) rather than picking one side. Done
  as part of the same pass that fixed the numeric-boundary false-positive bug above, since
  both changes touched the same two files.

- **`answer_question`'s tool-use loop is capped at `MAX_TOOL_ITERATIONS = 8`.** A
  non-converging model would otherwise call `search_handbooks` indefinitely with no circuit
  breaker on API cost. Set above the highest round count observed live for a legitimately
  thorough multi-hop question (5), so it only trips on genuine non-convergence.
- **`chunk_document()` raises `ValueError` if `split_sentences_in_sections` names a section
  that was never seen as a heading.** A typo or a renamed/removed section previously
  silently no-opped back to paragraph-level chunking instead of erroring — the worst
  possible failure mode for a manifest setting that exists specifically to fix a real
  retrieval gap (the SCOPE dilution issue — see decisions above). Now fails loudly at
  ingest time instead.

## 4. Open questions / known gaps

- **A policy split across consecutive paragraphs under one heading can lose its second
  half.** Chunking is strictly one-paragraph-per-chunk; if a section splits meaning across
  two adjacent paragraphs (like APAC's SCOPE section did — the near-miss `SEARCH_K` fix
  addressed *that specific* case by widening `k`, not by merging chunks), a future section
  with the same shape could still rank its continuation paragraph out of the search window.
  Not currently tested for beyond the SCOPE case in `test_retrieval_recall.py`.
- **`evals/matching.py`'s `matches()` is a substring/keyword heuristic on free-form model
  output**, not a semantic check. It was tuned reactively against several live runs' actual
  phrasing (see `docs/HISTORY.md`/`docs/TRANSCRIPT.md`) and is inherently gameable for
  word-based markers — a hedge-then-guess answer could plausibly trip an "unknown" marker.
  Most recently, a correctly-hedged answer phrased as "which **specific** country" slipped
  past the `"which country"` marker entirely (fixed by adding `"specific country"`). Treat it
  as a smoke test, not a strict regression gate for word markers — expect to keep adding
  markers as real phrasing varies across live runs. Numeric/currency markers no longer have
  this problem in the same way a live-review pass found and fixed a real false-positive bug:
  bare substring matching meant `"50"` matched inside `"$500"`, `"12"` inside `"120"`, `"14"`
  inside `"2014"`, and `"1,000"` inside `"$21,000"` — all silently wrong. Fixed with a
  digit/comma boundary check (see `evals/matching.py`); regression tests in
  `tests/test_matching.py`.
- **`VerifiedAnswer.rejected_draft` has no reader yet** — written on downgrade, never
  surfaced by `main.py`/`eval.py`. Fine as-is, but if you add a `--debug` flag or similar,
  this is where a rejected draft already lives.
- **`verify_answer` intermittently rejects legitimate correct answers.** Two related but
  distinct patterns observed, each with its own backlog ticket (cross-linked to each other —
  consider whether one fix addresses both before implementing either): (a) absence-based
  inferences ("no regional handbook names California, so the global default applies")
  sometimes rejected as unsupported — corroborated by two more live reproductions found
  while building the `edge_cases.py` suite (the "Chinese national in California" and
  "Japan/US split" cases), written up in
  `docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md`; and (b)
  specific-vs-general precedence carve-outs ("for PTO specifically, X takes precedence; for
  all other benefits, refer to Y") misread as an unresolved conflict between X and Y, even
  though X explicitly excludes itself from Y's scope — reproduced live on the flagship
  Taiwan-PTO example question itself, written up in
  `docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md`. Every occurrence so
  far has correctly *not* produced a wrong answer (the downgrade path just falls back to
  "can't confirm"), so it costs eval-run reliability, not correctness. Both tickets have a
  fully written-up fix proposal, root cause, and false-negative-aware test plan — deferred
  because a false-negative risk (does the fix make the verifier too lenient elsewhere?) was
  raised and not yet resolved before implementation. Read the relevant ticket before
  attempting either pattern. Note: pattern (a)'s retrieval-side contributor for the specific
  "no regional handbook covers X" (California/US) shape has since improved — the `SCOPE`
  chunking fix (see decisions above) raised the resolving excerpt's rank, and 5/5 live
  re-tests post-fix were correct with no rejections. `verify_answer`'s own reasoning weakness
  is unchanged and could still surface via other absence-inference shapes; don't treat this
  ticket as resolved.
- **Writing a good `matches()` test case: check whether the question asks more than one
  independent thing.** A single substring/keyword marker only verifies one claim. A question
  bundling two unrelated claims (e.g. "since \[false premise\], what is \[a genuinely
  different, unrelated fact\]?") needs a compound `[marker, marker]` assertion, or the test
  can pass for the wrong reason — confirmed live: a single `"12"` marker on the Taiwan
  sick-days question passed only because the *unrelated* PTO-premise correction happened to
  restate "12," while the actual sick-days answer was never checked at all, so a
  hallucinated "sick days: 12" would have passed identically. A question correcting one false
  figure with no separate sub-question (e.g. the California gym `$75` case) doesn't have this
  risk — there's only one fact to verify — so don't reflexively compound every negative-space
  case, only ones that actually ask two independent things.
- **The Asia-gym hedge still explains what the figure would be under each branch** ("if
  you're in one of those three countries... $50/month would win; if you're elsewhere... only
  the global $50/month applies") — the exact hedge-undercutting pattern the verbosity
  tightening (§3) tried to close but didn't fully. Observed live, flagged, not yet fixed.
- **LLM-assisted (semantic) chunking is deferred, not implemented.** Two prototypes
  confirmed it has real differentiating value over mechanical sentence-splitting (sub-
  sentence exception splitting, cross-paragraph merging) but that capability isn't needed
  anywhere in this specific 3-document corpus today — every real gap found was fixable more
  cheaply. Relevant once the corpus grows past what syntactic chunking rules can safely
  assume. Full writeup, including a required decision-log design for auditability at scale:
  `docs/backlog/2026-08-20-llm-assisted-semantic-chunking.md`.
- **Migrating `VectorIndex` to a real vector DB (Chroma) is deferred, not implemented** —
  same shape as the chunking ticket above: designed in full and verified via a live
  prototype to bring no benefit at this corpus's current size (no measurable performance
  win over `numpy`; a 10-query hybrid-search battery found zero accuracy wins either).
  Ready-to-implement design (schema, indexing, filtering, document add/modify/delete
  lifecycle) plus the Python-3.9-compatibility findings that rule out FAISS/LanceDB/Qdrant
  without also upgrading Python: `docs/backlog/2026-08-20-vector-db-migration-for-scale.md`.

## 5. Current status

Implemented and merged to `main`: full pipeline, all 12 original plan tasks, a
whole-branch review (2 Critical + 5 Important findings fixed), and 3 live-run-only fixes
(2 eval.py matcher gaps, 1 hedging-behavior gap) from the initial build. A follow-up session
then (a) tightened answer verbosity/citation scope in `SYSTEM_PROMPT`, (b) investigated and
partly fixed the ~5-10s per-answer latency (`preload_model()`; reverted a batch-tool-calls
attempt after a live ablation showed it hurt correctness), (c) investigated and shelved
prompt caching (real but small win, not worth it yet), and (d) rewrote final answers into a
rigid three-part verdict/reason/citation structure, iterated against several live runs to
close two verdict-ordering leaks. A third session, building a production-readiness edge-case
test matrix, found and fixed a real `version_year` retrieval bug (commit `b7411e4`), and its
subagent-driven-development execution built and shipped the matrix itself: 5 offline
entity-resolution tests (`tests/test_retrieval_entity_resolution.py`) and a 36-case live
acceptance suite (`edge_cases.py`) covering entity resolution, negative space, grounding,
consistency, and precedence generalization. That execution also surfaced and corroborated
two distinct `verify_answer` weaknesses, each fully written up but deliberately not yet
implemented (see `docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md` and
`docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md`). 41 offline
tests pass. `eval.py` passes 8/8 against the real Claude API (last verified live right after
the `version_year` fix — re-run it if handbook content, retrieval logic, or `SYSTEM_PROMPT`
changes). `edge_cases.py` last ran 34/36 live, with the 2 non-passing cases both matching
the known absence-inference backlog ticket, not new bugs. A fourth session, prompted by a
user-reported live nondeterminism bug, traced it to a real `SCOPE`-chunk retrieval gap,
tried and reverted a corpus-wide sentence-splitting fix (regressed a passing test), then
shipped a narrowly-scoped, manifest-driven version instead (`split_sentences_in_sections`)
plus a `SEARCH_K` 8→10 follow-up raise for the same reason `SEARCH_K` was raised the first
time. Two chunking prototypes (real-corpus and synthetic) concluded LLM-assisted chunking
has real value but isn't needed yet for this corpus — deferred as a third backlog ticket
(`docs/backlog/2026-08-20-llm-assisted-semantic-chunking.md`). That same investigation also
produced a full vector-DB migration design (schema, indexing, filtering, document lifecycle)
verified via a live Chroma+hybrid-search prototype to bring no benefit yet either — deferred
as a fourth backlog ticket (`docs/backlog/2026-08-20-vector-db-migration-for-scale.md`).
43 offline tests pass. `eval.py` passes 8/8 against the real Claude API (last verified live
right after the chunking fix — re-run it if handbook content, retrieval logic, or
`SYSTEM_PROMPT` changes). A fifth session, prompted by a user-reported live fabrication
(draft claiming APAC covers "Hong Kong/Singapore," not in the corpus), root-caused it as
draft-time named-entity hallucination distinct from the two open `verify_answer` tickets,
and shipped a restrictive `SYSTEM_PROMPT` fix (see decisions above) after confirming no
regression: 49 offline tests pass, `evals.eval` passes 8/8 live. Documented as a fifth
backlog ticket rather than closed silently, since 7 clean live reproductions can't prove the
fix against the rare event it targets:
`docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md`. Nothing currently in
progress — the five backlog tickets (two `verify_answer`, one LLM-assisted chunking, one
vector-DB migration, one hallucination finding) are the natural next pickups, four deferred
because they're real but not yet justified by this corpus's current size, and the fifth
already fixed but kept open pending stronger confidence in the fix.
