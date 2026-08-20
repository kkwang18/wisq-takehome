# Build History

Curated summary of the decisions, definitions, and course-corrections behind this system.
The full raw conversation is in `TRANSCRIPT.md`.

## The task

Build a Q&A system over three Acme HR documents (`Acme_Employee_Handbook_2025.docx`,
`Acme_Employee_Handbook_2026.docx`, `APAC_Benefits_Handbook.docx`) that must use retrieval
(chunk + embed + search) rather than stuffing full documents into every prompt, and must
answer 8 example queries correctly — including two queries with no clean numeric answer
(`unknown`, `hedge`).

## Definitions established during brainstorming

These are the business rules the system has to apply, extracted from the handbooks' own
"Conflicts and Precedence" sections, not invented for the test set:

- **Local wins, but only for PTO.** The APAC Benefits Handbook explicitly claims precedence
  over the global handbook specifically for PTO, and only PTO — for every other benefit it
  points back to the global handbook's own precedence rule.
- **More generous wins, for everything else.** The global handbook's default rule: where
  policies conflict, the option with the greater monetary value or entitlement applies.
- **Latest version wins when no year is specified.** Two global handbooks exist (2025, 2026)
  with different PTO numbers (14 vs 15 days); absent a stated year, the current/latest
  version applies.
- **Unknown, not a guess, when data doesn't exist.** A query about 2021 has no matching
  handbook — none of the provided documents cover a period before 2025 — so the system must
  say so rather than extrapolate.
- **Hedge, not a coin flip, when the entity is ambiguous.** "An employee living in Asia" is
  broader than "China, Japan, or Taiwan" (the APAC handbook's actual scope) — since a
  non-APAC Asian country would get a different (global-only) answer, the system must flag the
  ambiguity and ask, not pick one arbitrarily.
- **No hallucination, ever.** Every claim must be traceable to a retrieved excerpt with a
  citation; if retrieved excerpts don't support an answer, the system must say so rather than
  produce a fluent-sounding guess.

## Architecture decisions

- **Anthropic API for reasoning, local `sentence-transformers` for embeddings** — no
  embeddings API needed, no OpenAI dependency.
- **Agentic multi-hop retrieval**, not single-shot top-k: the questions require resolving a
  jurisdiction, resolving a document version, and then applying a precedence rule that
  itself lives in a different part of the document — a single fixed retrieval pass can't
  anticipate that combination for an arbitrary future question, so Claude gets a
  `search_handbooks` tool it can call multiple times before answering.
- **A separate grounding-verification pass** after the draft answer, checking every claim
  against only the chunks actually retrieved during that conversation — this is the concrete
  mechanism behind "no hallucination, ever," not just a prompt instruction.
- **Citations always shown to the end user**, inline in the answer text, not hidden.
- **Manifest-driven document set** (`documents.yaml`): adding or deprecating a document is a
  YAML edit plus a re-run of `ingest.py`, no code change.
- **Ingestion and querying are separate processes**: `ingest.py` builds and persists the
  index once; `main.py` and `eval.py` just load it, so no embedding-model cost at query time.

## Real-document surprises that changed the design mid-build

Two things were wrong in the original plan, both caught by inspecting the actual `.docx`
XML rather than trusting assumptions, and both fixed with evidence, not guesses:

1. **The handbooks' section headers live inside single-cell "banner" tables**, not top-level
   body paragraphs. `python-docx`'s `Document.paragraphs` API silently skips table-nested
   content, which would have dropped every section header. Fixed by reading
   `word/document.xml` directly via stdlib `zipfile` + `xml.etree.ElementTree`, dropping the
   `python-docx` dependency entirely.
2. **The two documents don't share one heading convention.** The global handbooks use
   `pStyle="Compact"` for real section headers; the APAC handbook uses `pStyle="Heading2"`.
   Worse — discovered only after real ingestion — APAC's "LOCAL LAW PROVISIONS" section has
   5 real body-content paragraphs that *also* carry `pStyle="Compact"`, which the original
   heading heuristic misclassified as headings and silently discarded. Fixed with a length
   guard (a paragraph counts as a heading only if it's both short-styled AND short, ≤60
   characters) rather than per-document special-casing.

## A retrieval-ranking near-miss found by the offline recall test

The offline retrieval-recall test suite (built specifically to answer the brainstorming
question "will free-text search alone reliably surface the correct chunk?") caught a real
near-miss: the APAC handbook's country-scope paragraph (naming China/Japan/Taiwan) ranked
7th of 13 candidates for a jurisdiction-scoping query, just outside the top-5 cutoff, because
an adjacent generic continuation paragraph out-ranked it lexically. Root-caused (not
guessed), then fixed by raising `k` from 5 to 8 — applied both in the test and in the real
agent's search tool, since the same risk existed in the live system, not just the test.

## A non-functional system that passed every test — until it actually ran

No `ANTHROPIC_API_KEY` was available anywhere during the build, so `src/agent.py`'s real API
request shape was never exercised — only checked for valid syntax and clean imports. The
final whole-branch review (dispatched on the most capable available model, after all 12
implementation tasks were individually complete and reviewed) found two Critical defects in
that request shape, verified against current Claude API documentation before being fixed:

1. `temperature=0` on every API call — Claude Sonnet 5 rejects any non-default sampling
   parameter with an HTTP 400. The system could not answer a single question.
2. `max_tokens=200` on the grounding-verification call — Sonnet 5 runs adaptive thinking by
   default, and thinking tokens count against the same `max_tokens` ceiling as the response
   text, so this call would very likely return empty text — downgrading every answer,
   including fully correct ones, to the ungrounded fallback.

Once the user provided a real API key and the system could finally run, a *third* class of
defect surfaced that no unit test, offline recall test, or static review could have caught:
the "gym benefits in Asia" query sometimes returned a definitive number instead of the hedge
the take-home's own expected answer calls for, because the system prompt's ambiguity rule
only triggered when different candidate jurisdictions would produce different final figures
— which this query doesn't (the number converges to $50 regardless of the specific country).
Fixed by broadening the hedge trigger to fire on the ambiguity itself, not just on whether it
would change the number.

All three defect classes found during this build — the two document-parsing/chunking bugs
found by real ingestion, the retrieval-ranking near-miss found by the real-corpus recall
suite, and these API-shape and hedging-behavior bugs found only by actually calling the real
model — share one thing in common: every one of them was invisible at the scope where it was
introduced, and became visible only when something real was executed against it. This is the
practical argument for "run real things against real data" as a development discipline, not
just a slogan: three separate defect classes, three separate layers of the system, one
consistent method for catching all of them.

## A follow-up session: tightening verbosity, then chasing latency

A later session picked up two separate requests, in order.

**Verbosity.** Live answers were substantively correct but padded — multi-paragraph,
citing every chunk touched during multi-hop search rather than the ones that actually
decided the answer, and narrating caveats (statutory minimums, other jurisdictions) the
question never raised. Fixed entirely in `SYSTEM_PROMPT` (target 2-4 sentences, cite only
the 1-2 determinative excerpts, only raise a caveat the retrieved text makes relevant, don't
undercut a hedge by revealing the answer under every branch). Retrieval, precedence logic,
and `verify_answer` were deliberately left untouched. Re-verified live: 8/8.

**Latency.** Asked to explain and improve the reported 5-10s per answer, Claude measured
rather than guessed: importing `sentence_transformers` costs ~3.35s and instantiating the
`SentenceTransformer` model costs ~2.81s — a ~6.2s one-time cost per process, which the code
was paying *after* the first Claude round-trip (the model only loaded lazily on the first
`search_handbooks` tool call) instead of overlapping with it. Two candidate fixes were
proposed: preload the model on a background thread (no behavior change, pure concurrency),
and nudge the system prompt to have Claude batch multiple `search_handbooks` calls into one
turn instead of one at a time (fewer sequential API round-trips).

The first live re-run after implementing both surfaced a real regression: the no-year
"California PTO" query — which had passed cleanly in every prior live run this session —
failed 1 of 4 further trials, downgraded by `verify_answer` as unsupported. The failing
draft was making a legitimate inference from *absence* ("no regional handbook names
California, so the global default applies"), which the verifier sometimes accepted and
sometimes didn't. Rather than assume it was pre-existing model flakiness, Claude ran a live
ablation: same query, same code, only the batching-hint sentence toggled. **0 of 4 failures
with the hint reverted vs. 2 of 4 with it in place** — strong evidence the hint itself was
the cause, most likely because it made Claude treat one batched round of searches as a
stopping signal, which shows up as a terser, less-scaffolded draft that the verifier is
pickier about. The hint was reverted; `preload_model()` was kept, since it doesn't touch
answer content at all.

A final confirmation run then failed differently — the "gym benefits in Asia" query hedged
correctly ("Could you tell me which specific country you're in...") but `eval.py`'s
`_matches()` only checked for the literal substring `"which country"`, not `"which specific
country"`, so a properly-hedged answer slipped past every marker. This is the same class of
matcher brittleness documented from the original build (see below); fixed by adding
`"specific country"` to the hedge marker list. A subsequent live run: 8/8.

**Takeaway carried forward:** the same "run real things against real data" discipline that
caught defects during the original build caught a real one here too — a plausible-sounding
latency fix (batch the tool calls) turned out to measurably destabilize a correctness
guarantee, and the only way that surfaced was running the actual eval against the actual
API repeatedly, not reasoning about the prompt change in the abstract.

**Prompt caching, investigated and shelved.** Asked whether prompt caching was worth adding,
Claude measured rather than estimated: a live timing breakdown of one multi-hop question
(via temporary instrumentation in `answer_question()`, reverted after) showed 97% of the
~9.5s call time is Claude API round-trip time dominated by thinking/generation, and the real
`count_tokens` endpoint showed the static `SYSTEM_PROMPT` alone (934 tokens) falls *under*
Sonnet 5's 1024-token cache minimum — only the system prompt plus the `search_handbooks`
tool definition together (1501 tokens) clears it. Verdict: caching would save a real but
small amount of cost, not the latency that motivated the original investigation, since the
cacheable prefix is small relative to total call time and `verify_answer`'s call sends no
system/tools at all. Shelved for now. (Full breakdown: `TRANSCRIPT.md` § 11.)

**A rigid three-part answer structure, iterated live.** Asked to enforce a fixed
"text-from-HR" shape — verdict, then one reason, then a trailing citation tag, no
exceptions — Claude rewrote `SYSTEM_PROMPT` and, having learned from the batching-hint
incident above that a prompt-phrasing change can look right and still misbehave live,
re-verified against `eval.py` after every revision instead of once. Three real gaps surfaced
and were fixed in turn: reasoning leaking before the verdict on "no regional handbook
covers X" answers (fixed with an explicit example), the same leak recurring for "no
matching year" answers (fixed by generalizing the rule to absence in general, not just the
regional-handbook case), and an `eval.py` matcher gap for the phrase "nothing on file" (same
recurring matcher-brittleness class as before). Final live run: 8/8, with verdict-first
holding in 7 of 8 responses — the one residual violation had been clean on the identical
query in a prior run, which reads as model sampling variance rather than a rule gap, and
Claude stopped there rather than chase a variance floor no `temperature` control can reduce
on this model. Also surfaced, incidentally: the Asia-gym hedge still explains both branches'
outcomes, the same undercutting pattern the verbosity-tightening task above tried to close —
flagged, not fixed, since it's outside this task's scope. (Full detail: `TRANSCRIPT.md` §
12.)

## Production-readiness edge cases: designing the test matrix found two real bugs first

Asked to design tests for five production-readiness categories (entity resolution, negative
space, grounding, consistency, precedence generalization) before implementing them, Claude
grounded the design in the actual document content (read every chunk in
`index/chunks.jsonl`) rather than assumption, and flagged one risk while doing so: the APAC
regional handbook's `version_year=None` (undated, since it has no yearly editions) could get
silently excluded by a year-filtered search on a question naming both a region and a year —
e.g. "Taiwan PTO in 2025."

The user tested that exact question themselves and hit a rejected answer. Reproducing it
live with debug instrumentation revealed **two independent, stacking bugs** on the flagship
example query, not one: (1) the predicted retrieval bug — a year filter applied to a
regional-scoped search excluding the APAC precedence clause, which at least once caused a
genuinely wrong draft (14 days instead of 12) — and (2) a separate `verify_answer` weakness,
visible in the user's own run: a *correct* draft (12 days) rejected because the verifier
misread an explicit "for PTO specifically, X takes precedence; for all other benefits, refer
to Y" carve-out as unresolved ambiguity between X and Y.

Bug 1 was fixed via TDD (`VectorIndex.search()` now treats `version_year=None` as "matches
any year," not "matches only no filter") — 36/36 offline, live reproduction went from mixed
correctness to 3/4 correct with the remaining failure confirmed as Bug 2, full `eval.py`
8/8. Committed separately as its own change.

Bug 2's fix was proposed, then the user asked a sharp question: **"Could this open up the
change for false negatives?"** — correctly identifying that re-testing the flagship query
only checks whether wrongly-rejected-correct-answers go down, not whether the same
leniency-granting instruction makes the verifier miss genuinely wrong answers elsewhere.
Rather than implement against an unresolved risk, the fix (with a tightened boundary clause)
and a concrete adversarial test plan — three deliberately wrong drafts designed to catch a
false-negative regression, including one that's the exact directional inverse of the fix's
own claim — were written up as a backlog ticket instead:
`docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md`. Full root cause,
verbatim rejection quotes, suggested fix, and test plan are there for a future session to
pick up without re-deriving the investigation.

## Process

Built with the superpowers plugin: brainstorming → design spec → implementation plan →
subagent-driven execution (fresh implementer + fresh reviewer per task, true red/green TDD,
YAGNI, DRY — explicit user instruction, applied throughout) → final whole-branch review →
live acceptance run against the real Claude API (all 8 example queries from the take-home
pass). Every non-trivial judgment call made during execution — the two chunking-heuristic
fixes, the retrieval-k fix, the final review's API-shape fixes, and the live-run hedging fix
above — is recorded with its reasoning in the SDD ledger at
`.superpowers/sdd/2026-08-19-rag-qa-system/progress.md`.
