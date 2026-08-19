# Coding Agent Transcript

This is the actual conversation that shaped this build — the take-home explicitly asked to
see "what conversation/questions/definitions" went into it, so this is a faithful record of
that session with Claude Code (using the `superpowers` plugin), not a reconstruction after
the fact. A curated summary of just the decisions is in `HISTORY.md`.

---

## 1. Reading the brief

**User:** "Use the superpowers plugin and lets complete the take home. Can you start by
reading the take home pdf. Please record any coding agent history as well"

Claude read `Take Home Test/Take Home Test 2026.pdf`. It specifies: build a Q&A system over
the three handbooks using RAG (not full-document reading per query), with 8 example
queries and expected answers, including two non-numeric cases (`unknown` for a
pre-2025 query, and a hedge for an ambiguous "Asia" jurisdiction). An example response is
given, showing the expected reasoning style: state the regional rule, the global rule, the
precedence rule, then synthesize.

Claude then inspected the three `.docx` files' actual paragraph text (via a raw XML dump) to
understand the real content before designing anything — notably, **California is never
mentioned anywhere in any document**, which is itself informative: the expected "15 (global,
latest version wins)" answer for a California employee only makes sense if the system
correctly determines no regional handbook covers California, so the global default applies.

## 2. Brainstorming (architectural path)

Claude invoked `superpowers:brainstorming`, classified this as an **architectural** task (new
project, no existing code), and worked through it via clarifying questions rather than
guessing:

**Q1 — Model access.** No `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` was set in the environment.
Claude asked how the system should get its embeddings + LLM reasoning, offering Anthropic API
+ local embeddings, OpenAI for both, or fully local. **User chose: Anthropic API
(recommended)** — Claude for generation, local `sentence-transformers` for embeddings.

**Q2 — Language/stack.** Python (recommended) vs. Node/TypeScript. **User chose: Python.**

**Q3 — Retrieval strategy.** Claude proposed a question about single-shot retrieval (larger
k, always-include precedence sections) vs. agentic multi-hop retrieval (a `search` tool
Claude can call multiple times). Before answering, **the user asked for clarification**:

> "In either strategy what happens if a user asks a question not answered in the docs? This
> system can't give back incorrect information. No hallucinations or fuzzy answers should
> ever be given."

Claude responded that this is a cross-cutting concern independent of the retrieval
strategy, and proposed five concrete grounding safeguards: a strict "answer only from
retrieved excerpts" system prompt, mandatory per-claim citations, explicit hedge/unknown as
first-class answer types (not error cases), a verification pass that re-checks the draft
answer against retrieved excerpts before returning it, and temperature 0.

**User then decided:** "proceed with agentic multi-hop, always show citations."

**Q4 — Interface.** CLI with both a canned-query mode and an `--ask` mode (recommended) vs.
canned-only vs. a web UI. **User chose: CLI with both modes.**

**Q5 — History capture.** Full transcript + curated summary (recommended) vs. curated summary
only. **User chose: full transcript + curated summary** — which is this file plus
`HISTORY.md`.

## 3. Design presented in chat, then a design gap the user caught

Claude presented the architecture (ingestion → chunking → embedding → agentic retrieval →
verification → CLI) in sections. After the first section, **the user asked a pointed
question**:

> "Looks like a good start, few questions. What happens if we need to parse more documents or
> a document becomes deprecated? Will we need to run retrieval each time this application
> starts?"

This changed the design: Claude added a declarative `documents.yaml` manifest (so adding or
deprecating a document is a config change, not a code change) and split ingestion from
querying into separate processes (`ingest.py` builds and persists the index once; `main.py`
just loads it), rather than re-embedding on every run.

## 4. A working-style instruction

Before implementation began, **the user said:**

> "When building this code emphasizes true red/green TDD, YAGNI (You Aren't Gonna Need It),
> and DRY"

Claude incorporated this directly into the design's testing section (one testable unit per
file, fixture-based tests, explicit "not building" list) and saved it as a standing
preference in memory for future sessions with this user.

## 5. Writing the spec — and finding real bugs before writing code

Claude wrote the design spec to `docs/superpowers/specs/2026-08-19-rag-qa-system-design.md`
and asked the user to review it. **The user pushed back with four specific, technical
questions** rather than approving outright:

> "Before building, worth checking whether the handbooks put benefit figures in tables,
> python-docx paragraph-only extraction would silently drop. Do all three documents actually
> share the same SECTION N / N.N header convention your chunking relies on? Will free-text
> search alone will reliably surface the correct chunk given the right jurisdiction and year?
> Would adding structured metadata filters alongside the embedding search would reduce the
> risk of getting the wrong chunk? For eval.py is it bad practice to call claude api? Is
> there a way to run this test without external api calls?"

Claude went back to the actual `.docx` XML to answer these with evidence, not assumptions,
and found two real problems:

1. **Tables**: all 9 "tables" in the global handbooks turned out to be single-cell banner
   boxes containing the section headers — not data tables with hidden figures, but
   `python-docx`'s `Document.paragraphs` API would have silently dropped them anyway, since
   it skips table-nested paragraphs entirely. Fix: read the raw XML directly instead of using
   `python-docx` at all.
2. **Heading convention**: the two global handbooks use `pStyle="Compact"` for real headers;
   APAC uses `pStyle="Heading2"` — genuinely different conventions, and neither document gives
   subsection headers their own paragraph. The originally planned "split on SECTION N: / N.N
   regex" was already wrong. Fix: one paragraph = one chunk, tagged by nearest heading,
   detected via a style whitelist instead of per-document regexes.

For the retrieval-quality question, Claude proposed (and the user's question directly led
to) two mitigations: embedding a metadata header alongside each chunk's own text
("contextual embeddings," since the 2025 and 2026 PTO paragraphs are nearly word-for-word
identical except the number), and giving the search tool structured `doc_type`/`version_year`
filters Claude can apply once it's resolved those facts from a question.

For the `eval.py`/API-calls question, Claude's answer: not bad practice, since the actual
thing under test is "does the system reason correctly," which a mock would defeat — but the
*unit* tests should stay fully offline. This led to `verify_answer` taking its LLM call as an
injected parameter (real client in production, a stub in tests) and a new offline
**retrieval-recall test suite** that checks the real corpus's retrieval quality using only
local embeddings, no API calls.

**User: "Lgtm, update and proceed."** Claude revised the spec with all of the above and
committed it.

## 6. Implementation plan

Claude wrote a 12-task implementation plan (`docs/superpowers/plans/2026-08-19-rag-qa-system.md`)
following true red/green TDD per task, then asked the user to choose an execution mode.
**User: "1"** (Subagent-Driven — a fresh implementer subagent plus a fresh reviewer subagent
per task, in-session).

## 7. Execution — subagent-driven development

Claude set up an isolated git worktree, ran a pre-flight conflict scan across all 12 tasks
(clean — no rulings needed), and executed each task as: dispatch implementer → implementer
reports → dispatch reviewer → reviewer verdicts spec compliance and code quality → any
finding gets fixed and re-reviewed → task marked complete in the SDD ledger.

Two real defects were caught during this loop, not invented for show — both are recorded
with full reasoning in `.superpowers/sdd/2026-08-19-rag-qa-system/progress.md`:

- **Task 8** (real ingestion against the actual handbooks): the reviewer sanity-checked an
  unexpectedly high chunk count and found that 5 real regional-law paragraphs in APAC's
  "LOCAL LAW PROVISIONS" section were being silently discarded — a consequence of the
  Task 4 heading heuristic treating any `Compact`-styled paragraph as a heading, which is
  also how APAC happens to style some of its body sentences. Claude ruled on a fix (a
  length guard: heading-styled AND ≤60 characters), dispatched it, and re-review confirmed
  it fixed exactly the 5 missing paragraphs with no new breakage.
- **Task 10** (the offline retrieval-recall test suite, built specifically to answer the
  user's "will search reliably surface the correct chunk" question from step 5): the
  implementer found a genuine near-miss — the APAC scope paragraph ranked 7th of 13
  candidates for a jurisdiction query, just outside the top-5 cutoff — root-caused it
  properly instead of loosening the test, and correctly escalated instead of guessing a fix
  on its own initiative. Claude ruled on raising `k` from 5 to 8, applied in both the test
  and the real agent's search tool (since the same risk existed in the live system).

All 12 tasks completed with clean or fixed-and-clean reviews. `HISTORY.md` and this file were
then written directly by the controller session (not a subagent), since only this session
has the actual conversation content.

## 8. What's next in this transcript

The final whole-branch review, and — pending an `ANTHROPIC_API_KEY` from the user, since none
was available in the build environment — the real end-to-end run of `eval.py` against the
actual Claude API, are recorded as later entries below if this file is updated after that
work completes.
