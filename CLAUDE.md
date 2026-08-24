# CLAUDE.md

Session-continuity file only — orientation, inviolable rules, and gotchas so a fresh Claude
session doesn't repeat settled mistakes or re-derive settled decisions. Not the design doc and
not the history:

- **Architecture, components, tradeoffs, rejected alternatives, scale roadmap** → `docs/DESIGN.md`
- **Full decision-by-decision narrative** → `docs/TRANSCRIPT.md` (raw) / `docs/HISTORY.md`
  (navigable index into it)
- **Deferred, fully-investigated work** → `docs/backlog/` (root cause + fix sketch + test plan
  already written per ticket, not one-line TODOs)
- **Setup / run / test commands** → `README.md`

## What this is

A RAG Q&A CLI over three Acme HR handbook `.docx` files (a take-home deliverable — see
`Take Home Test/Take Home Test 2026.pdf` for the original brief). Retrieve, don't stuff: every
claim must come from a chunk actually returned by a search call, never a document pasted whole
into the prompt. Never fabricate: unresolved questions get `unknown` or a hedge, not a guess.

## Domain rules the system must preserve

Any change to `src/agent.py`, `src/verification.py`, or the prompts inside them must keep
these true — they're the actual correctness contract, not stylistic defaults:

- Local (APAC) handbook wins over global, but **only for PTO** — every other benefit falls
  back to the global handbook's own precedence rule.
- Global handbook's own default: **more generous benefit wins** where policies conflict.
- **Latest version wins** when no year is stated (2025 vs. 2026 global handbook).
- **`unknown`, not a guess**, when no matching data exists (e.g. a 2021 query — no handbook
  that old).
- **Hedge, not a coin flip**, when the named jurisdiction is broader than what a regional
  handbook actually covers (e.g. "Asia" vs. China/Japan/Taiwan) — even if the final figure
  would be the same either way, the ambiguity itself must be surfaced.
- **No hallucination, ever** — including named entities, not just figures. Every claim must
  trace to a retrieved excerpt with a citation.

## Operating rules for this repo

- **TDD, red before green.** Offline `tests/` first (zero API cost) — then live-verify any
  prompt or logic change with `evals.eval` and/or `main.py --ask` before calling it done.
  Offline tests can't catch LLM sampling variance; this project has repeatedly found real bugs
  (verdict ordering, verifier false-rejections, formatting inconsistency) that only a live
  rerun surfaces. Use multiple reps, not one — single live runs have been misleading before.
- **When an LLM's output needs to be reliably parseable, constrain it with a tool schema —
  don't ask for a shape in a prompt and hope.** This has fixed two real, live-confirmed bugs
  already: `submit_answer`/`format_answer()` (verdict/reason/citation formatting) and
  `report_verification`/`VERIFY_TOOL` (verifier classification) in `src/agent.py`. Reach for
  this pattern first the next time something similar comes up.
- **Don't propose a vector DB, LLM-assisted chunking, or other scale-motivated infra change
  without reading `docs/backlog/` first.** Both are already fully designed and prototype-
  verified against the real corpus to bring no current benefit — deliberately deferred, not
  overlooked. See `docs/DESIGN.md`'s "What happens when it scales?" for trigger conditions.
- Keep `CLAUDE.md` / `TRANSCRIPT.md` / `HISTORY.md` updated incrementally as work happens, not
  batched at the end.
- Only commit, push, or open a PR when explicitly asked.

## Known gotchas

- `claude-sonnet-5` rejects any `temperature` param — 400 error. Never pass one.
- Thinking is on by default and shares `max_tokens` with output text — a low `max_tokens` on
  a thinking-enabled call can silently return empty text. The main answer loop leaves thinking
  on (`max_tokens=8000`); `verify_llm_call` explicitly disables it (`max_tokens=1000`).
- Run eval scripts as `python -m evals.eval` / `python -m evals.edge_cases`, not
  `python evals/eval.py` — needed for `sys.path` to resolve `ingest`/`src.*` imports the way
  `pytest.ini`'s `pythonpath = .` already does for `tests/`.
- The user's `! export ANTHROPIC_API_KEY=...` only reaches their own terminal, not this
  session's separate Bash tool shell — pass the key inline per command instead of trying to
  export it in Bash, and never persist it to a file.
- `VectorIndex.search()`'s `version_year=None` on a *chunk* means "matches any year filter,"
  not "matches only when no filter is given." Needed for the evergreen APAC handbook (no
  yearly editions) to survive a year-filtered search — get this backwards and a year-scoped
  query silently loses regional precedence.
- `chunk_document()` raises `ValueError` if `documents.yaml`'s `split_sentences_in_sections`
  names a section that isn't an actual heading in the document — don't "fix" this by catching
  the error; it means the manifest entry is wrong.
- Add or deprecate a source document in `documents.yaml`, never in code.
- Current tuned constants (see `docs/DESIGN.md` for why each value):
  `MODEL = "claude-sonnet-5"`, `SEARCH_K = 10`, `MAX_TOOL_ITERATIONS = 8`.

## Current status

(as of 2026-08-24)

111 offline tests pass (`pytest`). `evals.eval` (8 take-home queries) passes 8/8 live — last
verified 2026-08-24. `evals.edge_cases` is now a 38-case suite (36 original + 2 added for
named-entity-hallucination regression coverage); last full run scored 32/38, with all 6
failures individually diagnosed rather than just counted: 1 fresh-but-known
`verify_answer` carve-out-overgeneralization recurrence (see backlog ticket below — now two
same-day reproductions), 1 already-documented stale test expectation, 3 already-documented
`evals/matching.py` marker-phrasing gaps in categories unrelated to any change since, and 1
real matcher bug (found live, root-caused, fixed, and re-verified live 2/2 — see
`docs/superpowers/plans/2026-08-24-eval-matcher-redesign.md`'s SDD ledger for the full account).

`evals/matching.py` was substantially extended this session: a structured `Expectation` type
now supports numeric equivalence, `unknown`/`hedge`/`rejected` as three distinct, correctly-
`grounded`-gated outcomes, document/version correctness against real retrieval metadata
(`VerifiedAnswer.cited_chunks`, new this session), and required/forbidden claims — additive
alongside the original plain string/list markers, which are unchanged. Deterministic
throughout; no LLM calls added to the eval harness. `src/verification.py`'s citation check was
also tightened this session to scan only the parsed-out citation field, not the whole draft.

Open backlog (`docs/backlog/`), deliberately deferred with trigger conditions documented in
each: `2026-08-20-vector-db-migration-for-scale.md`, `2026-08-20-llm-assisted-semantic-chunking.md`,
`2026-08-20-draft-time-named-entity-hallucination.md` (fix shipped; ticket stays open only
because the live sample confirming it is too small to close confidently),
`2026-08-22-verify-answer-carve-out-overgeneralization-false-rejection.md` (`verify_answer`
can over-generalize one benefit's specific carve-out into false suspicion of a sibling benefit
the same excerpt explicitly routes to the general rule; root cause confirmed analytically, and
now reproduced live twice in one day — still held without a fix, deliberately, pending a
controlled before/after baseline), `2026-08-24-eval-matcher-cited-chunks-weak-doc-version-check.md`
(the new `Expectation.doc_type`/`version_year` checks are a weaker precondition than they look
— `cited_chunks` holds everything retrieved in a conversation, not just what was cited),
`2026-08-24-eval-matcher-required-numeric-term-boundary-gap.md` (a narrow, currently-unused
edge case in `required`'s boundary matching). Remaining gaps in `docs/DESIGN.md`'s "Known
failure modes."
