# Coding Agent Transcript

This is the actual conversation that shaped this build — the take-home explicitly asked to
see "what conversation/questions/definitions" went into it, so this is a faithful record of
that session with Claude Code (using the `superpowers` plugin), not a reconstruction after
the fact. A curated summary of just the decisions is in `docs/HISTORY.md`.

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
`docs/HISTORY.md`.

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

All 12 tasks completed with clean or fixed-and-clean reviews. `docs/HISTORY.md` and this file were
then written directly by the controller session (not a subagent), since only this session
has the actual conversation content.

## 8. Final whole-branch review found the system had never actually run

With all 12 tasks complete, Claude dispatched a final whole-branch review on the most
capable available model. It found two Critical defects — both in `src/agent.py`'s real API
request shape, which had never been exercised live because no `ANTHROPIC_API_KEY` was
available anywhere during the build, only static syntax/import checks:

1. `temperature=0` on both API calls — Claude Sonnet 5 rejects any non-default sampling
   parameter with an HTTP 400. The entire runtime path was dead on arrival.
2. `max_tokens=200` on the verification call — Sonnet 5 runs adaptive thinking by default
   when `thinking` is omitted, and thinking tokens count against the same `max_tokens`
   ceiling as the text output, so the verification call would very likely return empty text,
   downgrading every answer — including correct ones — to the ungrounded fallback.

Claude verified both claims directly against current Claude API documentation before ruling
on the fix (rather than trusting the review at face value, given they'd block merge), then
dispatched one consolidated fix covering these two Critical findings plus five Important
ones the same review raised (a truncation-handling gap, the anti-hallucination guarantee
being probabilistic rather than a code-level fact when nothing was retrieved, a downgraded
answer's draft being silently discarded and the verifier not being told that "unknown"/hedge
reasoning about absence is legitimately supportable, a missing fail-fast on a missing API
key, and a duplicated `k` constant). A scoped re-review (opus) confirmed all seven findings
were genuinely fixed in the working tree, not just attempted.

## 9. The live run — and what it caught that no earlier step could

**User:** provided their `ANTHROPIC_API_KEY` directly in chat so Claude could finally run the
system for real. Claude exported it only into the Bash tool call for `eval.py`, never wrote
it to any file or logged it.

The first live run: 7 of 8 queries passed. The one "failure" (the 2021 California PTO query)
was actually a correct, well-reasoned decline-to-guess answer — it just didn't contain the
literal word "unknown," which was all `eval.py`'s matcher checked for. Claude broadened the
matcher's phrase list and re-ran.

The second live run surfaced something more interesting: the same query now passed, but the
"gym benefits in Asia" query — which had genuinely hedged on the first run — this time gave a
definitive "$50/month" answer with only a brief caveat. Both are numerically correct (the
$50 global rate applies whether or not the specific Asian country has APAC regional
coverage), but the take-home's own expected answer is explicitly "hedge (country is not
clear)," not a definitive number. The root cause: the system prompt's ambiguity rule only
told Claude to hedge when different candidate jurisdictions would produce *different final
numbers* — which this query doesn't, so the rule never engaged even though the jurisdiction
genuinely can't be determined from the question.

Claude fixed the actual system prompt (not the eval script) — broadening the hedge trigger to
fire whenever a broad region only partially overlaps a regional handbook's coverage, since
the ambiguity about which policy and precedence path applies is worth surfacing on its own,
independent of whether the final figure happens to converge. The third live run: all 8
queries passed, including a properly hedged Asia answer that explains both scenarios and
asks which specific country.

A follow-up review of this fix (specifically checking whether the broadened `eval.py`
matcher could mask a real future regression) found the six numeric-expected queries are
structurally immune — the matcher branches on the expected marker's literal value, so a
broadened "unknown" phrase list can never substitute for a numeric substring check on a
different query — but flagged one added marker, a bare `"should avoid"`, as too generic and
possibly able to mask a genuine hedge-then-guess regression on the one query it does apply
to. Tightened to `"should avoid guessing"` / `"should avoid stating"`.

This whole sequence — a genuinely non-functional system that passed every unit and offline
test, caught only once it was actually run for real — is the strongest argument in this
build for the "run real things against real data" discipline that also caught the two
mid-execution chunking/retrieval defects in step 7. All three defects were invisible at the
scope where they were introduced and became visible only when something real was actually
executed against them.

## 10. A follow-up session — tightening verbosity, then a latency investigation that found a real bug

A later session opened with: "Lets pick up from our last session. Answers are substantively
correct (8/8 verdicts match), but too verbose — multi-paragraph, padded with disclaimers
about things not asked (statutory minimums not in retrieved text, offers to 'search further'
when already determined)," followed by four numbered requirements: lead with the verdict in
2-4 sentences; cite only the 1-2 chunks that actually determined the answer; drop speculative
caveats the retrieved text doesn't make relevant; only hedge on genuine ambiguity, without
revealing the answer under every branch. It explicitly asked to leave retrieval, precedence
reasoning, and `verify_answer` untouched.

Claude rewrote `SYSTEM_PROMPT`'s closing section to encode exactly those four rules, ran the
offline suite (34 passed, unaffected since this only touches prompt text), and asked to run
`eval.py` live to confirm. No `ANTHROPIC_API_KEY` was set in the shell; the user chose to
skip live verification for that turn rather than export one immediately.

**User:** "This is looking better now, lets focus on performance. The answer generation is
taking 5-10 seconds. Can we first understand why, what the bottlenecks are and how we can
improve?" Claude invoked the `systematic-debugging` skill rather than guessing, and measured
the local embedding stack directly instead of theorizing: `import sentence_transformers`
costs ~3.35s, instantiating `SentenceTransformer` costs ~2.81s, and a warm `search()` call
after that is ~0.03s (71 chunks, negligible). That ~6.2s is a one-time per-process cost, but
it was landing *inside* `answer_question()`'s timing because the model only loaded lazily on
the first `search_handbooks` tool call — after, not overlapping with, the first Claude
round-trip. Claude flagged the other likely contributor it couldn't measure without a key —
sequential Claude API round-trips (the multi-hop tool loop plus a separate `verify_answer`
call) — and asked which invocation pattern the user was timing (repeated `--ask`, one batch
run, or unsure), since that determines which bottleneck dominates. **User:** "Not sure/both
matter." Claude then proposed two "safe" fixes (background-thread model preload; a
system-prompt nudge to batch multiple `search_handbooks` calls in one turn) and two riskier
ones it flagged but didn't recommend without explicit buy-in (dropping the separate
verification call; disabling adaptive thinking on the main loop) — both would trade against
grounding/quality decisions made explicitly earlier in the project.

**User** then ran `! export ANTHROPIC_API_KEY=...` directly in the terminal to supply a real
key, and said: "Lets start with the two safe wins, I have exported the key" — followed
immediately by "Can you record the whole coding agent history in this chat as well" (the
request behind this section and the corresponding `docs/HISTORY.md` entry).

Claude first closed out the pending verification from the verbosity-tightening task: a live
`eval.py` run against the tightened prompt passed 8/8. It then implemented the two wins via
TDD — a failing test for `VectorIndex.preload_model()` first (red), then the implementation:
a background thread loads the model, `_get_model()` joins it before use — plus the
system-prompt batching nudge. Offline suite: 35/35 (34 + the new preload test).

A live re-run of `eval.py` with both changes in place failed 1/8: the no-year "California
PTO" query — which had passed cleanly in every prior live run — was downgraded by
`verify_answer` as unsupported. Claude re-ran the same query 3 more times in isolation and
saw it fail 1 of 3, confirming this was a real, reproducible-at-meaningful-rate issue, not a
one-off. Rather than assume the cause, Claude reported the finding plainly and asked whether
to spend more of the user's API budget on an ablation to isolate which of today's changes (if
either) was responsible, versus parking it as a possibly-pre-existing gap. **User:** "Run the
ablation."

Claude temporarily reverted only the batching-hint sentence (keeping `preload_model()`, which
doesn't touch answer content) and re-ran the same query 4 times: **0 failures**, versus 2
failures across the 4 prior trials with the hint in place. The mechanism: the failing drafts
were making a legitimate inference from absence ("no regional handbook names California, so
the global default applies") that the verifier inconsistently accepted — and the batching
hint most likely made Claude treat one batched round of searches as a stopping signal,
producing a terser, less-scaffolded draft the verifier was pickier about. Claude reverted the
hint permanently, kept `preload_model()`, reconfirmed the offline suite (still 35/35, since
none of this is offline-testable), and ran a final live `eval.py` pass to confirm.

That run failed differently: the "gym benefits in Asia" query hedged correctly ("Could you
tell me which specific country you're in...") but `eval.py`'s `_matches()` only checked the
literal substring `"which country"`, missing `"which specific country"` — the same class of
matcher brittleness documented from the original build, now caught on a phrasing variant one
word longer than before. Claude added `"specific country"` to the hedge marker list. The next
live run: 8/8.

Net changes kept: the verbosity-tightened `SYSTEM_PROMPT`, `VectorIndex.preload_model()` (a
background-thread model load with a TDD-covered test), and one more `eval.py` matcher
broadening. The batching-hint latency idea was tried, measured, and discarded — a real
example of a plausible-sounding fix that a live ablation showed was actively harmful, caught
only because the same "run real things against real data" discipline from the original build
was applied again rather than trusting the offline suite (which couldn't see any of this)
or a single passing live run (which had already happened twice before the flakiness showed
up on the third and fourth samples).

Before wrapping up, the user asked to resolve a `NotOpenSSLWarning` from `urllib3` that
appeared on every run. Claude traced it to `urllib3` v2 (a transitive dependency via
`requests` ← `huggingface_hub`) warning whenever Python's `ssl` module is built against
LibreSSL instead of OpenSSL — the case for this venv's macOS system-framework Python. Fixed
by pinning `urllib3<2` in `requirements.txt`. The user then reported still seeing the
warning; the actual cause was that their `python3 main.py` invocation used the *system*
Python's separate `~/Library/Python/3.9/lib/python/site-packages` install, not `.venv` —
the fix had only been applied inside `.venv`. Claude applied the same pin
(`pip install --user "urllib3<2"`) to that environment too and confirmed both were clean.

## 11. Investigating prompt caching before implementing it

**User:** "Okay. We have a great start, lets look into improvement areas. I was thinking
about implementing prompt caching. Can you run these tests to confirm if it's beneficial in
this system?" — followed, mid-turn while Claude was reading the `claude-api` skill, by a
precise two-part spec: (1) add timing around `agent.py` separating time in
`VectorIndex.search()` from each Claude API call type (search-decision, draft, verify), run
one representative multi-hop question, and report the breakdown; (2) check the static system
prompt's real token count against Sonnet 5's cache minimum, since the API's own
`count_tokens` endpoint exists for exactly this and guessing wasn't the point.

Claude added temporary `time.perf_counter()` instrumentation to `answer_question()`, ran it
live against "What is the gym related benefits for a employee living in Asia?" (a genuine
multi-hop case — the model issued two `search_handbooks` calls in one turn), and got: 3.49s
search-decision call, 4.30s draft call, 1.50s verify call, 0.25s total for both local
`index.search()` calls combined. Separately, `client.messages.count_tokens` showed
`SYSTEM_PROMPT` alone at 934 tokens — under Sonnet 5's 1024-token cache minimum — and
`SYSTEM_PROMPT` + the `search_handbooks` tool definition together at 1501 tokens, which does
clear it (render order is `tools → system → messages`, so a breakpoint on the system block
caches both).

While reverting the timing instrumentation, Claude ran `git checkout -- src/agent.py` —
which discarded the *entire* file's uncommitted changes, not just the instrumentation,
wiping out the verbosity-tightened `SYSTEM_PROMPT` and the `preload_model()` call from
earlier in the session (nothing had been committed yet). The harness's post-tool-use file
watcher surfaced the file's actual on-disk content in the next turn, Claude caught the
discrepancy immediately, disclosed the mistake plainly rather than silently re-applying a
fix, and reconstructed both lost changes from the conversation's own edit history —
confirmed correct via `git diff` matching the pre-mistake state exactly, and the offline
suite passing 35/35 again.

Claude's synthesis: 97% of the ~9.5s multi-hop call time is Claude API round-trip time, and
that time is dominated by thinking/generation, not input reprocessing — so even a cache hit
on the 1501-token prefix wouldn't move the number that motivated the original latency
investigation. The `verify_answer` call (16% of the total) sends no `system`/`tools` at all
and embeds a per-question draft, so it's structurally uncacheable regardless. Net: a real
but small cost lever (fractions of a cent per call at this volume), not a latency fix. Asked
how to proceed, the user asked to see the full reasoning before deciding, then: **"Yes, lets
skip this for now."**

**User:** "btw can you ensure the transcript is being regularly updated after each prompt?"
— this section, and the standing practice going forward, are the answer.

## 12. A rigid, texting-style answer structure

**User:** "Okay lets consider the answers this system gives, right now some answers lead
with the number, others lead with the reasoning. Lets enforce a rigid structure for each
answer, written as if HR is texting the employee. 1. answer first, the number or verdict.
2. Short supporting sentence explaining why. (the precedence rule or version that determined
it) 3. Citation as a light trailing tag. This change should be scoped to the phrasing and
structure not the logic."

Claude rewrote `SYSTEM_PROMPT`'s final-answer section into an explicit three-part template
matching the spec, then verified live rather than trusting the wording alone — the earlier
sessions' pattern of prompt changes producing real, only-visible-live regressions held again
here. The offline suite caught one thing immediately: the new text said "citation" but the
existing `test_agent.py` assertion checked for the substring `"cite"`, which "citation"
doesn't contain — fixed by rewording to "Cite only the excerpt(s)...".

The first live `eval.py` run (8/7 answerable, 1 failure) showed the real problem: 3 of 8
answers opened with a reasoning sentence *before* the verdict — e.g. "No regional handbook
for California/US exists... [then] **14 days of PTO...**" — directly violating "verdict
first, no preamble." Separately, the 2021 "unknown" query correctly said "Nothing on file
for that year" but failed `eval.py`'s matcher, which didn't have that phrase — the same
recurring matcher-brittleness class as before; fixed by adding `"nothing on file"` and
similar markers.

Claude strengthened the verdict-first instruction (explicit "very first words" language,
redirecting the absence-reasoning into part 2) and re-ran live: down to 2 of 7 violations,
both still the "no regional handbook covers X" pattern. Rather than keep restating the
abstract rule, Claude added a concrete WRONG/RIGHT example matching that exact failure
shape. Next live run: 0 structural violations in the 5 answerable cases, but a new
observation — the same pre-existing `verify_answer` flakiness on absence-based inference
claims (previously found and characterized in § 10, on a different query) recurred twice,
this time on "California gym" and the Asia hedge query. Claude did not re-open that
investigation — it's a known, separate, pre-existing gap, not something today's phrasing
change caused, and today's change was explicitly scoped to phrasing/structure only.

One more residual pattern surfaced: the 2021 "unknown" case still opened with "No results
found for a 2021 version..." before its own verdict line — the same anti-pattern, just for
a missing-year absence rather than a missing-region one. Claude generalized the rule (from
"no regional handbook" specifically to "any absence — no regional handbook, no matching
year, nothing else applies") and added a second WRONG/RIGHT example for the missing-year
case. A fourth live run: **8/8 passed**, with verdict-first holding in 7 of 8 responses —
the one remaining violation (California, no year specified) had been clean in the *previous*
run on the same query with identical instructions, which reads as genuine sampling variance
rather than a rule gap; Claude stopped iterating on wording at that point rather than chase
further compliance the model's own stochasticity limits, especially given `temperature`
cannot be set on this model to reduce it (see `CLAUDE.md` § 3).

Reading the final run closely also surfaced, unprompted, a live instance of an *older* known
gap: the Asia-gym hedge answer still explained what the figure would be under both branches
("...the global handbook's $50/month benefit would actually win out... if you're elsewhere...
only the global $50/month benefit applies") — the exact hedge-undercutting pattern § 10's
verbosity-tightening task tried to close ("do not also reveal what the answer would be under
each possible resolution") but evidently didn't fully. Flagged to the user, not fixed — out
of scope for a task that was already about a different part of the answer.

## 13. Production-readiness edge cases — a walkthrough that found two real bugs

**User:** "Lets work through some more edge cases and ensure our system is production
ready," followed by five categories, each with a precise one-sentence definition: entity
resolution (typos/casing/synonyms/compound entities), negative space (declining or
correcting rather than fabricating on out-of-scope or false-premise questions), grounding
(saying unknown for plausible-sounding but unsupported questions — "the core anti-
hallucination requirement of the whole assignment"), consistency (rephrasing shouldn't
change the verdict), and precedence (generalizing across the full set of covered countries,
"not just the single example (Taiwan) it was likely tuned against"). Asked for a walkthrough
of how to test these *before* implementing.

Claude invoked `superpowers:writing-plans`, then — rather than design in the abstract —
dumped and read every chunk in `index/chunks.jsonl` to ground the case matrix in the real
document content instead of assumptions. This surfaced real material: the APAC handbook
explicitly excludes contractors and scopes coverage by "based in and working from," not
nationality, creating genuine traps (a Chinese national working from California should get
global benefits, not regional); the conference/training budget ($1,000/year, Section 5.2)
exists only in the global handbook, giving a precedence-generalization case beyond the
PTO/gym pair the original 8 queries already covered. Claude proposed a two-tier test
architecture (offline retrieval-level for lexical robustness; a new live `edge_cases.py` for
full-agent behavior, kept separate from `eval.py` on cost/speed grounds) and flagged one
un-tested risk found while designing the matrix: the APAC handbook's `version_year=None` —
undated because it has no yearly editions — could get silently excluded by a year-filtered
search if a question named both a region and a year (e.g. "Taiwan PTO in 2025").

**User:** "Is this case matrix generalized examples you thought of or is this all of the
different combinations you plan on handling?" Claude answered directly: illustrative, not
exhaustive — laid out the actual combinatorial size per category (100+ cases if fully
crossed) and proposed a scoping rule: full cross-product only for precedence generalization
(since proving it isn't Taiwan-specific is the entire point of that category), one
representative per distinct failure mechanism everywhere else (a typo test on Taiwan and a
typo test on Japan exercise the same code path, so testing both adds no signal).

**User:** "Perfect and how are you thinking we handle 'Taiwan PTO in 2025'" — asking about
the flagged risk specifically. Claude proposed the retrieval-layer fix (treat
`version_year=None` as "matches any year," not "matches only no filter") and the TDD plan to
verify it, still as a proposal, not yet implemented.

**Then the user ran it themselves:** `python3 main.py --ask "What is the PTO policy for
Taiwan PTO in 2025"` — and got a rejected answer, pasted verbatim, asking what should
happen. Rather than assume this confirmed the predicted bug, Claude added temporary debug
instrumentation (search calls + draft, reverted via targeted `Edit` afterward — not
`git checkout --`, learning from the earlier incident) and reproduced the same query 3 more
times live. The debug output revealed **two independent bugs, not one**: Run 3 showed the
predicted retrieval bug directly — Claude's first search included `version_year=2025`
alongside a Taiwan-scoped query, returned zero APAC content, and Claude drafted a genuinely
*wrong* answer (14 days) before a later, unfiltered search finally found the regional
clause too late to correct course; `verify_answer` correctly caught and rejected that wrong
draft. But the user's original run showed a *different* failure: the draft had correctly
said 12 days, and `verify_answer` wrongly rejected it, reasoning the APAC PTO carve-out
"does not clearly resolve" against the global handbook's general "more generous" rule — a
misreading, since the APAC clause explicitly excludes PTO from "all other benefits." Two
real, independent, stacking bugs on the exact flagship example query.

**User:** "Can you create a todo list. Confirm with me, provide evidence each task is
completed successfully and that it doesn't create any new bugs. Then commit the changes
before starting the next task. Fix bug 1, bug 2, then pick up where we left off with the
matrix." Claude proposed the 3-task order and confirmed scope for Task 1 before touching
code.

**Task 1 (retrieval fix):** TDD — tightened `test_search_filters_by_version_year`, added a
dedicated `test_search_version_year_filter_always_includes_undated_chunks` (red before the
fix), re-scoped `test_search_returns_empty_when_filters_match_nothing` to
`doc_type="global_handbook"` since the old fixture-only "no match" case no longer held once
undated chunks legitimately started matching every year. One-line fix in
`VectorIndex.search()`. Evidence: 36/36 offline, 3/4 live flagship reproductions correct
(the 1 failure confirmed as Bug 2, not this one), full `eval.py` 8/8. Committed as `b7411e4`.

**Task 2 (verifier fix), proposed then challenged:** Claude proposed adding a
specific-carve-out-overrides-general-rule instruction to `build_verification_prompt`.
**User:** "Could this open up the change for false negatives?" — a sharp, correct challenge:
re-running the flagship query only tests whether false positives (correct drafts wrongly
rejected) go down, and can't reveal whether the same permission-to-be-lenient instruction
makes the verifier *too* lenient elsewhere. Claude tightened the instruction with an explicit
boundary clause (the exemption only fires when the excerpt unambiguously covers the queried
case) and designed three adversarial test drafts — a fabricated number, a draft that
deliberately misapplies the general rule over the specific one (the exact inverse of the
fix's own claim, and the sharpest directionality test), and a pure-fabrication control — to
be run against `verify_answer()` directly, before implementing.

**User:** "For now can you write this as a bug ticket. But it in a new directory, label it
to indicate future tasks. Lets log the issue so a future agent can pick up from here." Claude
created `docs/backlog/` and wrote
`docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md` — root cause, verbatim
rejection quotes from live runs, the suggested fix, the false-negative risk raised but not
resolved, and the full test plan (offline prompt-content check, live false-positive
re-sampling, and the three adversarial false-negative cases) — so a future session can
resume without re-deriving any of this investigation.

## 14. Executing the edge-case plan via subagent-driven development

**User:** "Can you create a todo list. Confirm with me, provide evidence each task is
completed successfully and that it doesn't create any new bugs. Then commit the changes
before starting the next task. Fix bug 1, bug 2, then pick up where we left off with the
matrix (write it up as a formal plan... and we pick an execution mode)." Claude proposed a
3-task order (fix the `version_year` bug, fix the `verify_answer` precedence bug, then the
edge-case matrix), got sign-off on Task 1's scope, and — for Bug 1 — went straight to TDD:
tightened `test_search_filters_by_version_year`, added
`test_search_version_year_filter_always_includes_undated_chunks` (red before the fix), fixed
`VectorIndex.search()` so `version_year=None` matches any year filter instead of only an
absent one. Evidence: 36/36 offline, 3/4 live flagship reproductions correct (the 1 failure
confirmed as the separate Bug 2, not this one), full `eval.py` 8/8. Committed as `b7411e4`.

For Bug 2, Claude proposed a tightened verifier instruction with a boundary clause and three
adversarial test drafts. **User:** "For now can you write this as a bug ticket... in a new
directory, label it to indicate future tasks" — same treatment as Bug 1's sibling ticket:
`docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md`.

**User:** "Lets go on to task 3." Claude wrote the formal plan
(`docs/superpowers/plans/2026-08-20-production-readiness-edge-cases.md`, two tasks: offline
entity-resolution retrieval tests, then the live 36-case `edge_cases.py` suite) and offered
execution modes. **User:** "Subagent-driven." Claude set up an isolated worktree
(`.worktrees/edge-case-plan`, careful to branch from local HEAD rather than
`EnterWorktree`'s default `origin/main`, since local `main` was several commits ahead and
unpushed), ran the pre-flight conflict scan, and dispatched Task 1 (haiku, fully-specified
transcription task) — clean report, clean review, approved.

Task 2's implementer (haiku) built `edge_cases.py`, ran it live (34/36), and reported
`DONE_WITH_CONCERNS` — but its own characterization of 2 of the 3 failures ("corpus
boundary limitations... California and US PTO not in handbooks") was wrong, and Claude
caught this itself before trusting the report: the real corpus's global-handbook Section 1
explicitly states coverage applies "worldwide... regardless of the country... unless a
specific provision states otherwise," which resolves both cases via the global default. This
was verified directly against `index/chunks.jsonl`, not assumed. Claude ruled the expected
markers correct-as-written, confirmed the actual committed code was untouched by the wrong
narrative, and resumed the implementer for one fix round to correct the commit message and
report rather than the code. Scoped re-review: all addressed, no new breakage.

The final whole-branch review (dispatched on the most capable available model) came back
clean — "Ready to merge: Yes" — with three Minor items triaged: a stale `CLAUDE.md` (fixed
directly by Claude as controller-level bookkeeping, not a subagent fix-loop, since it was
documentation not code), a DRY marker-list duplication between `eval.py` and `edge_cases.py`
(deferred, documented), and two test cases with less discriminating power than intended
(noted for a future revision). Claude also wrote a *second* backlog ticket
(`docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md`) distinguishing
this newly-corroborated absence-inference pattern from the sibling precedence-carve-out
ticket, cross-linked, with an explicit note to consider one fix for both.

Tests green (41/41), worktree merged to `main` via fast-forward, branch and worktree cleaned
up, per `superpowers:finishing-a-development-branch`'s standard 3-option menu — **user chose
"1. Merge back to main locally."**

## 15. A live nondeterminism report leads into a chunking-strategy design discussion

**User** ran the merged system directly and hit exactly the kind of thing this plan was
built to catch: `python3 main.py --ask "What is the PTO policy a us citizen"` twice
back-to-back produced a correct "15 days" answer once and an `UNSUPPORTED` rejection the
other time — "Why is there nondeterministic behavior?" Claude explained two layered causes:
`claude-sonnet-5`'s lack of a `temperature=0` option (general sampling variance, documented
in `CLAUDE.md` § 3) and, more specifically, that the rejection text was a near-exact match to
the already-ticketed absence-based-inference bug — a third live reproduction. Added to the
ticket as corroborating evidence, committed.

**User:** "I thought this system was reading from vectors which should be deterministic?"
Claude drew the distinction precisely: `VectorIndex.search()` (embedding + cosine similarity)
*is* fully deterministic — no LLM, no sampling, same query string always returns the same
ranked chunks. The nondeterminism enters through the LLM layers wrapped around it: Claude
generates the search query text itself, drafts the answer, and a separate LLM call verifies
it — three sampled calls, none of them the vector search itself.

**User:** "Could the way we are chunking help alleviate this issue?" Rather than answer from
theory, Claude ran the actual retrieval pipeline against the three queries in question and
found a concrete, previously-unknown fact: the APAC `SCOPE` paragraph's most directly relevant
sentence — "personnel outside these three jurisdictions should refer to the global Acme
Employee Handbook" — ranks **#19–21 of 71** total chunks for exactly the queries that need
it, nowhere near `SEARCH_K=8`. This revised Claude's own earlier root-cause understanding:
the absence-inference ticket had assumed (by analogy with the sibling precedence ticket,
where it was true) that the resolving excerpt was always present in `cited_chunks` — for this
pattern, that assumption doesn't hold. The gap is a retrieval/chunking problem for at least
part of the failure, not purely a verifier-reasoning one.

**User:** "How do these solutions scale as we add more documents or more complicated
exception boundaries?" Claude re-scanned the corpus for the general-shape pattern (a
paragraph combining a broad claim with a "does not apply"/"unless"/"except" exception) and
found three more structurally similar, untested candidates (`SECTION 1` P1, `SECTION 8` P3,
APAC `CONFLICTS` P2), then evaluated six-then-seven chunking strategies (status quo,
sentence-level, targeted manual splitting, section-level, additive hybrid, embedding-only,
and automated keyword-detection) along two axes: does discovery/effort scale with document
count, and does accuracy hold as exceptions get more complex. Manual approaches (targeted
splitting, additive hybrid) scored well per-instance but worst on discovery cost, which grows
unboundedly with corpus size; automated keyword-detection scored well on effort but poorly on
precision as document phrasing diversifies.

**User:** "For this task I am not allowed to look at the documents, so there cant be a manual
review. the system we build should consider scale always." Claude disqualified the two
manual-review-dependent strategies outright, drew a distinction between legitimate
*structural* inspection (needed to build any chunking pipeline at all — the same way the
original build read docx XML to discover `pStyle="Compact"`/`"Heading2"`) versus prohibited
*content-specific* hand-tuning (choosing a specific paragraph's split point by reading and
understanding its meaning), and flagged honestly that the existing `HEADING_STYLES` heuristic
was itself derived the prohibited way — a real, pre-existing tension in the shipped system,
not something to fix now but worth surfacing. Introduced sliding-window chunking as a new,
fully-mechanical candidate and recommended sentence-level or sliding-window over the
keyword-detection approach given the constraint.

**User:** "I take it back I can do some manual review, would that make c and e more
appealing?" Claude declined to simply say yes — reasoned that permission removes the
*prohibition* but not the *cost*, and proposed reconciling "manual review is allowed" with
"the system should always consider scale" by keeping *discovery* automated (offline recall
testing, no document reading) while treating *fixes* as small, bounded, reactive reviews of
one flagged paragraph — not proactive full-document reads. Still preferred the additive
hybrid over targeted splitting even with review allowed, on pure regression-risk grounds
(additive can't break what currently passes; replacement can).

**User:** "Ah okay, yes a human reading and splitting the document is too much. Imagine a
system where we had hundreds or thousands of HR documents." Claude reassessed at that order
of magnitude: keyword-detection's precision problem gets worse with document diversity;
sentence-level/sliding-window chunking stays viable but exposes a second, related scaling
threshold — `VectorIndex`'s brute-force numpy search (documented as a deliberate "no vector
DB" choice for this corpus's size) would need a real ANN index at that scale, a retrieval-
infrastructure problem distinct from chunking. Proposed LLM-assisted (semantic) chunking as
the production-standard answer for genuinely large, stylistically diverse corpora — a cheap
model processing each document once at ingest time to identify clause/exception boundaries
semantically rather than syntactically — while being explicit about its real costs: it breaks
`ingest.py`'s current fully-local, no-API-key-required design, introduces a new failure
surface at precisely the point nobody can manually check it, and raises its own question
about whether ingest-time chunking should be idempotent given the same lack of `temperature=0`
that causes query-time nondeterminism. Recommended a two-tier design: sentence-level chunking
as the free, deterministic baseline, with LLM-assisted chunking reserved for documents where
automated recall testing — not a human — flags the baseline as insufficient.

**User:** "Yes, lets take a look at this solution. When the LLM is doing the chunking can it
provide a document showing decision points it made? Also are you recording our conversation
down, that's a key part of this take home assignment" — the second question is the direct
cause of this section existing; the first is addressed in the response that follows.

## 16. Two chunking prototypes, a reverted regression, and a shipped fix

Claude answered the audit-trail question directly: yes, and non-negotiable for the
LLM-assisted tier specifically, since nobody reads the source documents — proposed a
per-decision rationale log (paragraph ID, action, rationale) as a hard requirement, not an
optional nicety, modeled on this project's own `docs/backlog/*.md` pattern applied at
ingest time instead of after the fact.

**Tier 1 attempt.** Claude implemented sentence-level splitting in `chunk_document()` via
TDD (updated/added tests, red then green), rebuilt the real index, and ran the full offline
suite — which surfaced a real regression: `test_apac_scope_is_retrievable_to_rule_out_california`
failed. Total chunk count had nearly doubled (71→136); the country-list sentence that test
protects now ranked #13 of 20 regional chunks, worse than the original near-miss `SEARCH_K`
was raised to fix. Worse, checking the fix's *own* target showed it hadn't worked either —
the `SCOPE` exclusion sentence's rank got worse, not better, for 2 of 3 originally-failing
queries (US citizen: #19→#29 of 71; California: #21→#33). Claude stopped, reported this
plainly rather than push forward ("this is worth stopping on — the actual empirical result
contradicts the hypothesis I proposed two turns ago"), and did not commit the change.

**User:** "What about chunking on semantics such as PTO entitlement, gym reimbursement, a
precedence rule?" Claude reverted the sentence-splitting experiment cleanly (`git status`
confirmed only the two touched files were dirty; `git checkout --` used correctly this time,
learning applied from the earlier mid-session incident) and evaluated the proposal properly:
semantic/topic grouping is a genuinely different lever than syntactic splitting (it can
*merge*, which sentence-splitting never can), but flagged a serious architectural risk before
anything else — semantic grouping must stay within one source document, since every existing
`doc_type`/`version_year`/`jurisdiction` filter depends on that 1:1 chunk-to-document mapping,
and cross-document topic merging would destroy the entire 2025-vs-2026 and global-vs-APAC
disambiguation this system is built around.

**User:** "Yes, prototype it." Claude built a real, working prototype: called Haiku with a
verbatim-only chunking prompt on the actual `SCOPE` section text, inserted the results into
the real 71-chunk index in place of the original two paragraphs, and re-ran the same rank
checks. Results looked promising (California: #21→#16; Chinese-national-in-CA: rank #8;
regression check passed, unlike the corpus-wide attempt) — but Claude caught an important
confound before declaring victory: the LLM's actual chunking *decisions* were byte-identical
to what mechanical sentence-splitting would have produced for this specific paragraph, and
the fix only touched 2 paragraphs instead of 71. The improvement was very likely attributable
to narrow scope, not LLM intelligence — the same lesson as the regression, restated. Also
caught, via an automated verbatim-substring check built into the prototype itself: the LLM
had silently normalized a curly apostrophe to a straight one — not a paraphrase, but not
byte-identical either.

**User:** "Yes, run that second prototype" (to actually test the LLM's differentiating value).
Claude first checked the real corpus for a second genuinely broken case requiring
cross-paragraph merging or sub-sentence splitting — checked two real candidates (the `SCOPE`
"supplements... APAC markets listed above" backward reference, and the `LOCAL LAW
PROVISIONS` "statutory minimum overrides" sub-sentence exception) and found **both already
retrieve correctly today** (ranks #1 and #3 respectively) — a real, honestly-reported finding
that this corpus doesn't currently have a second broken case, not just a failure to find one.
Built a synthetic paragraph instead (explicitly labeled as constructed, not real corpus
content, to stay consistent with the project's existing offline-fixture convention) —
one sentence, no internal punctuation, with an embedded exception. Mechanical splitting
produced 1 chunk (nothing to split on); the LLM correctly separated it into 2 verbatim,
semantically distinct chunks. A clean, honest demonstration that the capability gap is real
— just not currently exercised anywhere in this specific 3-document corpus.

**User:** "Apply the narrow fix to SCOPE now, document the LLM assisted tier as a ticket
that can be worked later." Claude checked `documents.yaml`/`src/manifest.py`/`src/models.py`
first to find the project's existing pattern for deliberate, document-specific configuration
(the `active` flag), and extended it rather than hardcoding section-name checks into
`chunking.py`: a new `DocMeta.split_sentences_in_sections` field, manifest-driven, TDD'd
across all three layers (models, manifest parsing, chunking behavior) with tests confirming
both the opt-in behavior *and* that everything else stays unchanged by default. Opted in
just `SCOPE` via `documents.yaml`. Rebuilding the real index produced 73 chunks (not 136) —
matching the first prototype's math exactly.

Running the full offline suite against the real rebuilt index surfaced one more thing: the
same regression test failed again, but only barely — the country-list sentence now ranked
#9 of 15 regional chunks (regional count grew 13→15 from splitting `SCOPE`), a near-tie with
rank #8 (score gap: 0.001), and rank #10 also named the covered countries. Claude recognized
this as literally the same pattern as the original `SEARCH_K` 5→8 fix recurring at a new
boundary, and raised `SEARCH_K` 8→10 with a comment explaining why. Full offline suite: 43/43.
Live `eval.py`: one failure on the first run — not a regression, the same recurring
`_matches()` marker-brittleness class as before (a correct "unknown" decline phrased as "no
matching handbook version found" wasn't in the marker list) — fixed the matcher, re-ran:
8/8. Direct re-tests of the two originally-failing query shapes: 5/5 correct, no rejections
(previously intermittent).

Claude wrote a third backlog ticket
(`docs/backlog/2026-08-20-llm-assisted-semantic-chunking.md`) documenting both prototypes in
full — including the honest finding that the LLM's value wasn't needed for the shipped fix —
so a future session doesn't have to re-run either experiment, and updated the existing
absence-inference ticket with a "Retrieval-side update" section clarifying that this fix
addresses one contributing cause for one query shape, not the underlying `verify_answer`
weakness itself, which remains open.

## 17. A vector-DB design, verified against the actual library ecosystem and prototyped, not assumed

**User:** "Okay, great now I want to think about how we are handling the vectors. Is there a
open source vector db we can use for this project? It should be free, lightweight and bring
either performance benefits or accuracy benefits." Rather than answer from general knowledge
of the vector-DB landscape, Claude checked real PyPI wheel metadata for FAISS, Chroma,
LanceDB, and Qdrant — and found something a normal comparison would miss: the top-level
`requires_python` field on PyPI is misleading for `abi3` wheels (it reflects the last-uploaded
file, not the union of all wheels), so the real check required inspecting actual wheel
filenames. Result: only Chroma has a genuine `cp39` wheel; FAISS/LanceDB/Qdrant's latest
releases all require Python ≥3.10, since this project is still on 3.9 (which reached
end-of-life the same year). Claude was also honest that neither performance nor accuracy
benefits were guaranteed at this corpus's size — 97% of latency is Claude API round-trips
(established earlier), and any accuracy win would need testing, not assuming, the same
discipline as every other investigation this session.

**User:** "Yes, before you prototype can you show me your proposed design for the vector db.
Schema, indexing strategy, filtering" — then, mid-turn: "Also a strategy when a document is
added/modified/deleted." Claude installed Chroma into a throwaway scratch venv first and
inspected its real, current API via `help()` rather than write against remembered training
knowledge (the library has changed significantly across versions) — and caught a subtle,
consequential detail this way: empirically verified that a Chroma metadata field entirely
*absent* on a record is **excluded** by an equality `where` filter, the exact same
wrong-direction default `VectorIndex.search()` had before the fix earlier the same day. A
naive migration would have silently reintroduced the bug this whole session had just spent
significant effort diagnosing and fixing. Designed around it: an explicit `-1` sentinel for
evergreen (APAC) documents plus an `$or` clause replicating the fixed semantics — verified
this actually works via a direct test, not just reasoned about. Also verified empirically
that Chroma's default distance metric is L2, not cosine (would silently produce different
rankings than everything validated this session) — must be set explicitly via
`configuration={"hnsw": {"space": "cosine"}}`. The document-lifecycle design (add/modify/
delete) was scoped deliberately conservative: keep the current full-rebuild default, but
shape the schema (stable per-chunk IDs, a `file` metadata key) so incremental upsert/delete
becomes possible later without a redesign — chosen over a fully incremental design from the
start, matching the project's established "don't build for hypothetical future
requirements" discipline.

**User:** "Looks good, make sure to track if this prototype finds a query your current numpy
+ pre-filter setup gets wrong that Chroma + hybrid gets right." Claude checked Chroma's
native hybrid-search API (`Bm25EmbeddingFunction`, `SparseVectorIndexConfig`) but found it
newer and less externally documented than the core API — rather than reverse-engineer it
blind, built hybrid search the transparent, standard way instead: Chroma for dense retrieval
(exactly matching the just-designed schema), a hand-rolled BM25 pass (no new dependency for a
throwaway prototype), and Reciprocal Rank Fusion to combine them. Ran a 10-query battery
against the real 73-chunk corpus, deliberately including adversarial cases beyond simple
sanity checks: a paraphrase-only query sharing zero keywords with its source text (testing
dense's strength / BM25's weakness), and the one remaining untested "general rule + exception"
merged-chunk candidate from the `SCOPE` investigation (`SECTION 8`'s local-law-override
clause). One test-design bug was caught and fixed along the way — the first "US citizen" case
was run unfiltered by mistake, producing a misleading MISS across all three systems; corrected
to use `doc_type="regional_handbook"`, matching how the live agent actually searches.

Final, honest result: **zero cases across all 10 queries where the current system missed and
hybrid caught it** — `numpy` == Chroma-dense == Chroma-hybrid on every row, with dense
matching current exactly (confirming the prototype was a faithful replication, not a broken
comparison producing a false negative by accident). Claude cleaned up fully afterward
(uninstalled the experimental `chromadb` dependency, removed the scratch venv, confirmed via
`git status` and the full 43/43 offline suite that no trace was left) before reporting the
null result.

**User:** "Sounds good lets document this. We can add this as a backlog ticket as a change.
This is something our system would need to implement if corpus grows. Include your schema,
indexing, filtering, document lifecycle details in the documentation." Claude wrote
`docs/backlog/2026-08-20-vector-db-migration-for-scale.md` — the full verified design
(schema, indexing, filtering with the sentinel fix, lifecycle), the Python-3.9-compatibility
table, and the prototype's methodology and exact results, explicitly framed as
ready-to-implement without re-investigation once triggered by real corpus growth — the same
shape as the LLM-assisted-chunking ticket, and for the same underlying reason: real,
verified capability, not yet justified by this corpus's current size.

## 18. Project layout cleanup — docs consolidated, eval scripts separated from the product CLI

**User:** "Great, can we do some general cleanup of the project. We have a docs dir but then
transcript.md and others are roaming outside. Can you logically organize the directories and
code in a way another eng can easily decipher the files." Claude surveyed the full scope
before touching anything: checked which root-level files are load-bearing by convention
(`CLAUDE.md` — Claude Code's own auto-discovery requires it at repo root; `README.md` —
universal git-hosting convention) versus which were genuinely misplaced, and checked the
`Take Home Test/` directory's contents (dated well before the project's own history) to
confirm it's the original delivered assignment materials, not something to reorganize.
Grepped for every cross-reference to `HISTORY.md`/`TRANSCRIPT.md` across the repo (25
occurrences, 11 files) before moving anything, and drew a deliberate line: update *live*
documentation (`README.md`, `CLAUDE.md`, the docs/backlog tickets' actionable instructions,
and the two files' own self-references) but leave `docs/superpowers/plans/*.md` and
`docs/superpowers/specs/*.md` untouched, since those are point-in-time planning artifacts —
a faithful record of what was written at the time, the same principle already applied to
`TRANSCRIPT.md` itself. Moved both files into `docs/` via `git mv` (preserving history) and
fixed every live reference. Along the way, auditing surfaced two real, unrelated staleness
bugs: `HISTORY.md` pointed at a `.superpowers/sdd/.../progress.md` path confirmed via
`git log` to have never been tracked — a fresh clone would never have had it — and a
`SEARCH_K = 8` decision bullet in `CLAUDE.md` that was stale (raised to 10 by the morning's
chunking fix, but the bullet still described 8 as current). Fixed both.

**User** (mid-turn, while Claude was still working): "Can you logically group the .py files
as well." Claude identified the real ambiguity at the project root: `ingest.py`/`main.py`
(the actual product CLI) sat alongside `eval.py`/`edge_cases.py` (live-API QA tooling with a
very different purpose — spend real money, check correctness, not typical usage) looking
like similar entry points. Created `evals/` as a proper package (`__init__.py`, matching
`src/`'s and `tests/`'s existing convention) and moved both scripts in via `git mv` — a pure
rename, zero content changes (confirmed via `git diff`). Anticipated and tested the real
risk before trusting it: moving a script into a subdirectory changes what lands on
`sys.path[0]` when run directly, which would break `from ingest import build_index` — instead
of guessing, verified `python -m evals.eval` (module invocation, puts the *working directory*
on `sys.path`, not the script's own directory) resolves correctly via the free "no API key
set" exit path, at zero live-API cost, before updating any documentation to point at the new
command. Updated `README.md`, `CLAUDE.md`, and the two backlog tickets' actionable regression
commands; left informal short-name mentions of "eval.py" in prose, and every narrative
mention inside `docs/HISTORY.md`/`docs/TRANSCRIPT.md` of a *literal past command*, untouched
— the same historical-record principle as before, since those commands were genuinely typed
that way at the time. 43/43 offline suite, both moved scripts confirmed via the same
zero-cost import check, one commit for the whole reorganization.

## 19. A live false-positive report leads to compound test assertions and a new test-of-tests

**User** pasted a real live response to `edge_cases.py`'s `NEGATIVE_SPACE` case "Since Taiwan
employees get unlimited PTO, how many sick days do they get?" (expected marker: `"12"`) and
asked directly: "this isn't necessarily correct, the response our system gave is accurate,
how can we ensure our test suite is not sending false positives/negatives." Rather than take
the claim at face value, Claude ran the actual `_matches()` function against the pasted
response text to see precisely what was happening, rather than reason about it abstractly —
confirmed the test passed, but for the wrong reason: "12" appeared only because the response
correctly restated the true PTO figure while correcting the false premise, and the
*separate*, genuinely-different sick-days sub-question was never actually checked by the
marker at all. Also checked, before proposing a fix, whether a naive tightening (requiring an
"unknown"-class marker too) would have worked — and found it wouldn't have: the real
response's phrasing ("No fixed number of sick days on file") wasn't caught by any existing
marker either, the same recurring class of gap already documented in `CLAUDE.md` § 4, found
again by testing rather than assuming the fix would work.

Fixed via TDD: extended `_matches()` to accept a list/tuple `expected` (AND semantics, so a
compound question can require multiple independent conditions), added the missing marker,
and updated the specific case to `["12", "unknown"]`. Before writing the fix, wrote
`tests/test_edge_cases_matching.py` — offline, zero-cost, real regression coverage of the
matching *harness itself*, not just the system under test, including a constructed
adversarial case (a hallucinated "sick days: 12" response that would have passed the old
single-marker test identically) to prove the fix actually discriminates correctly, not just
that it passes the one real example. Then scanned the rest of the 44-case + 8-case suite
heuristically for the same compound-question shape, found one other candidate (the
California `$75` gym case), and judged it genuinely different in kind — a single corrected
figure to verify, not an independent second sub-question — rather than reflexively applying
the same fix everywhere. Updated `CLAUDE.md`'s existing duplicated-marker-lists gap to note
the two `_matches()` copies have now functionally diverged (only `edge_cases.py`'s supports
compound assertions), and added a general, reusable principle for writing future
negative-space cases: compound only when the question asks two genuinely independent things,
not by default.

## 20. A live fabrication of named entities, root-caused and closed with a restrictive fix

**User** pasted a real `main.py --ask "Do employees have any sick days? What aboout 401k?
What about vision ,dental or medical insurance?"` run whose `verify_answer` rejection quoted
a draft claiming the APAC Benefits Handbook's jurisdictions were "Hong Kong/Singapore/etc.
type jurisdictions," and asked plainly: "WHat happensed here?" Claude checked the claim
directly against `index/chunks.jsonl` rather than assuming — confirmed neither "Hong Kong"
nor "Singapore" appears anywhere in the corpus; the APAC handbook's real scope is China,
Japan, and Taiwan only. This was recognized as a different bug shape from the two open
`verify_answer` tickets: those are about the verifier misreading excerpts that *were*
retrieved, while here the draft-generation step fabricated named entities never retrieved at
all — and the safety net (`verify_answer`) caught it correctly before the user ever saw it.

Added temporary debug instrumentation to `src/agent.py` (printing each search call and the
raw pre-verification draft), reproduced the user's exact question live three times before
making any change — all three came back correct and grounded, no fabrication — then reverted
the instrumentation cleanly, confirming via `git diff --stat` that only the debug lines were
dirty before reverting (a discipline adopted after an earlier session mistake where a blind
`git checkout --` wiped out real uncommitted work along with debug code). Explained the
finding to the user in full: root cause (likely pretrained/outside knowledge of "typical
APAC hubs" leaking through on named entities specifically, since the existing
outside-knowledge instruction was scoped to figures/norms and didn't explicitly name
entities), the ~1-in-4-ish observed rate, and why this differs in kind from the two existing
tickets. Used `AskUserQuestion` to offer two paths — log the ticket only, or also implement a
low-risk prompt fix now — explicitly reasoning that, unlike the two `verify_answer` tickets
(where added leniency risks false negatives), a stricter *draft-time* grounding instruction
carries no symmetric downside: it can only make the model more conservative.

**User** selected: "Also implement the low-risk prompt fix now." Added an explicit clause to
`SYSTEM_PROMPT` prohibiting any named entity not verbatim in a retrieved excerpt. Verified
with the same discipline as every other change this session: full offline suite (49/49),
live `python -m evals.eval` (8/8), and four more live reproductions of the exact fabricating
question — all four came back correct and grounded, two of them explicitly and correctly
naming "China, Japan, and Taiwan." Reported the result to the user honestly, including the
caveat that seven clean reproductions (three pre-fix, four post-fix) cannot statistically
prove a fix against a rare, roughly 1-in-4-to-1-in-8 event — and documented the full
investigation, evidence, and fix as a fifth backlog ticket
(`docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md`) rather than closing it
silently, since the fix's effectiveness is plausible but unproven.

## 21. A full review pass, re-sequenced by the user, executed item by item

**User:** "Do a full review pass on the RAG take-home system built so far. Give a
prioritized analysis of where to improve next. Key areas to focus on Eval matcher rigor,
chunking, verification logic, code quality. This pass is about correctness and coverage, not
scope expansion." Claude read every source file and the full offline test suite directly
(not relying on `CLAUDE.md`'s own accumulated self-description, which could be stale) and
empirically verified the most important suspected finding before reporting it: ran
`evals.edge_cases._matches()` directly against constructed inputs and confirmed numeric
markers matched as bare substrings — `"50"` matched inside `"$500"`, `"12"` inside `"120"`,
`"14"` inside `"2014"`, `"1,000"` inside `"$21,000"` — a real, demonstrable false-positive
risk, not a theoretical one. Reported seven prioritized findings (matcher false-positives
first; the two already-designed `verify_answer` tickets; the missing tool-loop iteration cap;
the eval-matcher duplication; verdict-parsing fragility; a stale `k=5` default; a missing
citation cross-check) plus three items correctly left alone at current scope, and
recommended an execution order.

**User** overrode the proposed sequencing with four explicit changes: (1) bundle the matcher
fix with the shared-module extraction, since both touch the same two files and doing them
separately would mean re-touching the files twice; (2) move the 5-minute iteration cap ahead
of the larger `verify_answer` fix, since more eval volume was about to run through the system
and the circuit breaker should land first; (3) require the `verify_answer` fix's adversarial
false-negative tests be written and confirmed *before* shipping, not deferred the way both
tickets had left it open — "the ticket already flags this as open — don't defer it"; (4) pull
the P2 typo-validation fix forward into this batch, since it shares the exact "config typo
silently degrades chunking" shape as the SCOPE fix. "Rest of P2 stays batched for later as
planned."

Executed in that order, TDD throughout, one commit per item:

1. **Matcher fix + shared-module extraction.** Built `evals/matching.py` with a
   digit/comma-boundary regex check for numeric markers (`(?<![0-9,])...(?![0-9,])`) and a
   `matches()` function merging both files' marker lists as their union — additive by
   construction, since markers are OR'd for "unknown" detection, so no case that passed
   before could newly fail. Renamed `tests/test_edge_cases_matching.py` to
   `tests/test_matching.py` (it now tests the shared module, not something
   `edge_cases`-specific) and added six new regression tests covering the four
   empirically-confirmed bugs plus boundary edge cases. 55/55 offline. Live verification was
   blocked mid-task: the API key wasn't available in Claude's Bash shell even after the user
   ran `! export ANTHROPIC_API_KEY=...`, since that only applies to the user's own terminal,
   not the separate shell each Bash tool call spawns — flagged honestly rather than skipped
   silently, and confirmed live (8/8) once the user supplied the key directly in chat.
2. **Iteration cap.** Added `MAX_TOOL_ITERATIONS = 8` to `src/agent.py`'s tool-use loop, set
   above the highest round count observed live for a legitimately thorough question (5).
   TDD'd with a scripted fake-client test proving an always-`tool_use` response gets cut off
   at exactly the cap, plus a positive test proving a normal short exchange is unaffected.
   57/57 offline.
3. **P2-6 typo validation.** `chunk_document()` now raises `ValueError` naming any
   `split_sentences_in_sections` entry never seen as a real heading, instead of silently
   reverting to paragraph-level chunking. TDD'd against a typo'd name over a real `SCOPE`
   heading. 58/58 offline, including the real corpus's own `documents.yaml` build (confirming
   the new check doesn't false-positive on the real, correctly-spelled `"SCOPE"` entry).
4. **`verify_answer` fix, adversarial-tested first.** Pulled the real corpus excerpts needed
   for both tickets' test cases directly from `index/chunks.jsonl` (not invented text) via a
   quick grep-style script. Wrote one shared addition to `build_verification_prompt` covering
   both tickets' patterns at once — a specific rule carving itself out of a general fallback,
   and a general default rule with no specific override — the option both tickets had
   flagged as worth evaluating but left undecided. Before landing it, wrote a scratch
   live-probe script (`verify_probe.py`, not committed — a one-off verification pass, not a
   permanent regression test, matching how this session's other live investigations stayed
   scratch work) and ran: a pre-fix baseline (4 reps each of the two previously-flaky correct
   drafts, both landed 4/4 SUPPORTED, consistent with the tickets' own "intermittent, not
   deterministic" framing rather than contradicting it); then post-fix, the same two correct
   drafts again (4/4 both) plus six adversarial drafts at 3 reps each — a fabricated number,
   an inverted-direction draft (deliberately misapplying the wrong rule in each pattern, the
   sharpest test of whether the fix over-generalized), and an unrelated fabrication, for both
   the Taiwan (specific-carve-out) and California (general-default) shapes. All 18 adversarial
   reps stayed correctly UNSUPPORTED. 59/59 offline (including a new prompt-content test),
   live `evals.eval` 8/8. Updated both backlog tickets' status to fixed, with the fix wording,
   the adversarial evidence, and an honest caveat that a clean sample cannot prove the
   false-positive rejection rate is now zero, only that this battery found no
   over-generalization.

Updated `CLAUDE.md` (decisions, gaps, and status sections) and this transcript incrementally
as each item landed, per the standing instruction to keep documentation current during the
work rather than batched at the end.

## 22. A live formatting-inconsistency report leads to a plain-prose, compound-question rule

**User** reported that asking the same compound question twice ("Do employees have any sick
days? What about 401k? What about vision, dental, or medical insurance?") produced visibly
different formatting across runs — one answer used a bulleted list with bold topic labels
plus an intro paragraph and a closing paragraph, the other used flowing prose with none of
that — and asked how to make the system's output more consistent.

Classified as a bounded brainstorming task (an existing flow — `SYSTEM_PROMPT`'s three-part
final-answer structure in `src/agent.py` — being tightened, not a new subsystem). Root cause,
confirmed by reading `src/agent.py`: the three-part verdict/reason/citation structure was
written assuming a single verdict and had no rule at all for a question bundling multiple
distinct topics, so the model improvised a different shape each time it hit that case.
Checked `main.py` and confirmed it does a bare `print(result.text)` with no markdown
renderer, so the bulleted run's `**bold**` labels were rendering as literal asterisks in the
terminal — a second, independent argument against markdown formatting beyond consistency.

Presented the two live-verified downsides of a bulleted-list fix before the user chose a
direction: (1) "verdict first" would need to hold independently inside each bullet instead of
once for the whole message; (2) citation granularity becomes ambiguous (one shared tag can't
show which bullet it backs); (3) list framing invites the same intro/outro creep already
visible in the reported bug; (4) "what counts as one bullet" (e.g. is "vision, dental, or
medical insurance" one topic or three) is itself a new source of run-to-run variance. User
weighed the scannability benefit of bullets against these, then chose the simpler, fully
unambiguous option: plain prose only, one shape for every answer regardless of question
complexity, including hedge/unknown verdicts.

TDD'd: added `test_system_prompt_forbids_structural_formatting_and_normalizes_compound_questions`
to `tests/test_agent.py` (substring assertions on `SYSTEM_PROMPT`, following the existing
`test_system_prompt_encodes_grounding_and_precedence_rules` pattern), confirmed it failed red,
then edited `SYSTEM_PROMPT` to (a) explicitly ban bullets/numbered lists/headers/bold in the
final-answer instruction, and (b) add a compound-question rule stating the three-part shape
applies once to the whole message — one verdict sentence naming every topic's outcome
together, one reason sentence covering all of them, one citation tag that may name more than
one document/section — with hedge/unknown verdicts following the identical shape. 60/60
offline tests pass.

Live-verified with the API key passed inline per command (the user's `! export
ANTHROPIC_API_KEY=...` again didn't reach Claude's separate Bash shell, same environment
limitation as session 21 — this time recognized immediately from the transcript's own
history instead of being rediscovered): 3 reps of the exact reported query all came back in
the identical plain-prose shape, no bullets or markdown in any of them. Re-ran `evals.eval`'s
8-query regression suite: 7/8 passed; the 1 failure (California PTO, no year given) was a
`verify_answer` rejection over an unrelated "is 2026 the current version" inference — not
touched by this change (`SYSTEM_PROMPT`'s version-resolution rule and `verify_answer` itself
were both left untouched). Confirmed as pre-existing flakiness, not a regression, by
re-running that specific query 3 more times: all 3 landed on the correct 15-days answer,
consistent plain-prose shape, no rejection. Updated `CLAUDE.md` (decisions and status
sections) and this transcript incrementally, per the standing instruction.

## 23. Plain prose still wasn't guaranteed apart — moved formatting into a `submit_answer` tool

**User** reported a follow-up problem with the fix above: running the same compound question
(and the 8 example queries) still showed the citation sometimes jammed directly onto the
reason sentence (`"...applies. — (Doc, Section)"`, no line break) and sometimes on its own
line, and asked to "ensure the format is answer, reason, citation separated apart," with
test-suite coverage of it, and for the format to "always be consistent."

Read `src/verification.py` and `evals/matching.py` first to confirm neither depended on any
particular whitespace layout, then proposed the actual fix: a prompt instruction can't
*guarantee* separation, since free text gives the model no structural boundary between
"reason" and "citation" — this codebase had already hit exactly this kind of live sampling
variance once before (the verdict-ordering fix, session history above). The fix instead moves
formatting out of the model's hands: a new `submit_answer` tool with three separate fields
(`verdict`, `reason`, `citation`) instead of free chat text, and a pure `format_answer()`
function in code that deterministically assembles them as three blank-line-separated
paragraphs. This makes the layout itself testable offline with zero API calls, directly
answering the "ensure the testsuite covers this" ask.

User asked one clarifying question before approving: does forcing three rigid fields fit
every answer shape (definitive, hedge, unknown/absence, compound)? Answered by walking
through each shape against the existing three-part contract (already established, unchanged
by this fix) and confirming the fields don't add a new constraint — they structurally enforce
what free text was already supposed to do. One real adjustment made in response: kept
`verdict`/`reason` as unconstrained free-text strings rather than schema-locking them to one
sentence, so the separation guarantee doesn't fight a compound question's need for a slightly
longer field.

TDD'd in `tests/test_agent.py`: new tests for `format_answer()` (blank-line separation, exact
citation wrapping, whitespace stripping — all pure, no API), a `submit_answer` tool-schema
test, a `SYSTEM_PROMPT` test asserting it requires the tool instead of plain text, and
rewrote the scripted-response tests to script a `submit_answer` tool-use response instead of
a raw text block for the final turn. Implementation: added `SUBMIT_ANSWER_TOOL`, rewrote the
final-answer section of `SYSTEM_PROMPT` to describe the three fields instead of three prose
parts, added `format_answer()`, and changed the loop to route `tool_use` blocks by name
(`submit_answer` → assemble draft and stop; anything else → `search_handbooks` as before) and
to pass `tool_choice={"type": "any"}` on every call, forcing the model to always call some
tool rather than ever falling back to unstructured chat text. 64/64 offline tests pass.

Live-verified with the API key passed inline again (same environment limitation as sessions
21–22): 3 reps of the exact reported compound query all landed in the identical three-
paragraph shape — verdict, blank line, reason, blank line, citation — every time. Re-ran
`evals.eval`'s 8-query suite: 8/8. One unrelated oddity surfaced in that run: the Taiwan-gym
query's `verify_answer` call returned raw text that opened with `"UNSUPPORTED: ..."`, reasoned
through a self-correction, and ended on `"SUPPORTED"` — since `verify_answer` checks
`.startswith("SUPPORTED")`, it took the rejection branch despite the verifier's own final
conclusion being supported, and the eval only "passed" because `"$50"` happened to appear
inside the long rejection text the matcher scanned. Confirmed as pre-existing, unrelated
flakiness (not caused by this session's change, since neither `verify_answer.py` nor
`build_verification_prompt` were touched) via 3 clean reruns of that exact query: all 3
landed correctly `SUPPORTED`, cleanly formatted, no recurrence. Flagged to the user as a
candidate follow-up rather than fixed here, since it was outside what was asked this session.
Updated `CLAUDE.md` (architecture, decisions, open questions, and status sections) and this
transcript incrementally, per the standing instruction.

## 24. A backlog ticket written for review, then implemented per the user's re-scoping

**User** asked to look at the flagged `verify_answer` prefix-parsing oddity, but wanted a
ticket written up for review first — before any implementation. Wrote
`docs/backlog/2026-08-22-verify-answer-prefix-parsing-false-rejection.md` following the two
existing `verify_answer` tickets' established structure (summary, concrete example, root
cause, suggested fix, test plan, files involved), including the exact captured verifier
response as the concrete example, a hypothesis connecting it to the two related (closed)
tickets' shared prompt addition possibly increasing verifier verbosity on borderline cases,
and a primary suggested fix (mirror the `submit_answer` pattern: enum-constrained tool field
instead of free-text prefix parsing) plus a cheaper, not-recommended alternative (more robust
text parsing).

**User** made three scoping calls on the draft before implementation: (1) skip the
occurrence-rate stress test in the test plan — the fix is worth shipping regardless of the
pre-fix rate, and live API spend to measure it isn't justified; (2) don't leave the
"connection to the recent precedence fix" as an open, still-unconfirmed thread — since the
chosen fix makes verifier verbosity structurally irrelevant to correctness, state that
explicitly as the resolution once the fix lands, independent of whether the earlier fix
actually caused more out-loud reasoning; (3) note that `evals.eval` passing the triggering
query anyway is a second, independent instance of the substring-matching blind spot already
documented for `evals/matching.py`'s numeric markers — different code path (the eval matcher
never consults `grounded`), same root-cause class (checking a substring's presence instead of
confirming it means what the check assumes) — worth cross-referencing, not fixing here. Edited
the ticket to reflect all three before starting implementation.

Implemented the primary suggested fix via TDD. Read `tests/test_verification.py` first and
confirmed `verify_answer.py` itself didn't need to change — the fix belongs entirely at the
call site, since `verify_answer`'s contract (trust a string starting with "SUPPORTED"/
"UNSUPPORTED") is fine; what needed fixing was *guaranteeing* the caller hands it exactly
that, instead of parsing whatever prose the verifier happened to write. Extracted the
previously-inline, untestable `llm_call` closure in `answer_question` into a standalone
`verify_llm_call(client, prompt)`, added `VERIFY_TOOL` (`report_verification`, `verdict`
constrained to `enum: ["SUPPORTED", "UNSUPPORTED"]`, separate `reason` field), and forced
`tool_choice={"type": "tool", "name": "report_verification"}` so no free-text fallback is
possible. Wrote the regression test directly encoding the reported bug's shape first
(`test_verify_llm_call_ignores_reasoning_verbosity_in_verdict_classification` — a long,
self-correcting-looking `reason` paired with `verdict: "SUPPORTED"`, asserting the output is
exactly `"SUPPORTED"`), confirmed it red (import error, then assertion failure against the
old closure), then implemented. Also added a tool-schema test, both classification-branch
tests, a forced-`tool_choice` test, and updated the existing scripted-response test to script
a `report_verification` tool call instead of a raw `"SUPPORTED"` text block. 69/69 offline
tests pass.

Live-verified with the API key passed inline again: 5 reps of the exact reported query
(Taiwan gym benefits) all came back cleanly formatted and correctly `grounded=True`, no
misclassification in any of them — a larger sample than the 3-rep spot-checks used earlier in
this session, since this was the specific mechanism being fixed. Re-ran `evals.eval`'s 8-query
suite: 8/8, including the previously-accidental Taiwan-gym pass now genuinely correct rather
than a substring coincidence. Updated the ticket's status to Fixed with a "Fix implemented"
section (mirroring the two related tickets' pattern), including the explicit resolution of
the "connection to the recent precedence fix" thread per the user's instruction 2 above.
Updated `CLAUDE.md` (architecture, decisions, open questions — replacing the now-fixed bullet
with the newly cross-referenced `evals/matching.py` gap, and status) and this transcript
incrementally, per the standing instruction.

## 25. `docs/DESIGN.md` written — an as-built architecture doc for engineers picking up this repo

**User** asked for a design doc covering the system's core components, tradeoffs, why each
decision was made, and what would need to improve to make this a larger-scale system —
followed shortly by a mid-turn clarification that the doc needed to be written so other
engineers could understand the tech specs and begin work in this repo, not just as a
retrospective summary.

Re-read the actual source files (`chunking.py`, `retrieval.py`, `docx_reader.py`, `models.py`,
`documents.yaml`, `ingest.py`) rather than writing purely from `CLAUDE.md`'s decision log, to
ground every claim in current code with real line numbers rather than paraphrased memory of
past sessions. Loaded the `artifact-design` skill before writing, per its own hard
requirement, and confirmed Markdown was the right call under that skill's own guidance
("fits only when... the content is bound for a Markdown-native destination") — this document
is meant to live in the repo and be read by engineers there, not primarily as a standalone
web page.

Wrote `docs/DESIGN.md`: a repo map table, a step-by-step "life of a query" trace through every
file for `main.py --ask "..."` (the fastest orientation path for someone new), two mermaid
architecture diagrams (ingest pipeline, query pipeline), six core components each with what it
does, real file/line references, and — the actual "tradeoffs" ask — the rejected alternatives
and live evidence that ruled them out (raw XML vs. `python-docx`, paragraph vs. sentence
chunking, contextual embeddings, `numpy` vs. the prototyped-and-rejected vector DB, the
tool-schema pattern used twice to fix free-text formatting bugs), a "design principles that
cut across components" section naming the throughlines worth carrying into new work, "known
limitations" grouped by risk type rather than discovery date, and a 7-item "path to scale"
roadmap ranked by what would actually break first at real traffic (observability first, since
none exists; eval-harness rigor next; then the two already-designed-and-deferred backlog
tickets correctly ranked by their real trigger condition — corpus growth, not calendar time —
rather than backlog age).

Updated `README.md`'s pointer to make `docs/DESIGN.md` the primary design reference over the
original pre-implementation spec (kept, relabeled as historical context). Published as an
artifact for easy reading/sharing (favicon 🧭), redeployable to the same URL on future edits.

## 26. `CLAUDE.md` compressed to session-continuity only; `HISTORY.md` rebuilt as a navigable index

**User** asked to compress `CLAUDE.md` down to only what's needed to maintain continuity
across different Claude sessions — now that `docs/DESIGN.md` owns architecture/tradeoffs —
and to fold `HISTORY.md` into a more navigable version of `TRANSCRIPT.md`, explicitly leaving
`TRANSCRIPT.md` and `DESIGN.md` untouched.

Rewrote `CLAUDE.md` (486 → 94 lines) around what a fresh session actually needs to avoid
repeating a settled mistake or re-deriving a settled decision, not a human-facing project
overview: a one-paragraph orientation with pointers to `DESIGN.md`/`TRANSCRIPT.md`/
`HISTORY.md`/`backlog/`; the six domain rules as an explicit correctness contract (local wins
only for PTO, more-generous-wins otherwise, latest-version-when-unstated, unknown-not-a-guess,
hedge-not-a-coinflip, no-hallucination-ever); operating rules (TDD + live-verification
discipline, the tool-schema-over-prompt-hope principle now proven twice, an explicit "don't
propose a vector DB or LLM chunking without reading `docs/backlog/` first" directive to head
off re-litigating an already-prototyped-and-deferred decision); known gotchas that would
actually bite a fresh session (the `temperature` 400 error, the thinking/`max_tokens`
interaction, the `evals` import-path requirement, the `!`-export-doesn't-reach-Bash-tool
environment quirk, the `version_year=None` sentinel semantics, the `split_sentences_in_sections`
typo validation); and a condensed current-status paragraph that honestly flags
`edge_cases.py`'s 34/36 number as stale (predates a fix that likely resolves both failures,
not rerun since).

Rebuilt `HISTORY.md` (502 → 171 lines) as a genuine index rather than a second, slightly
shorter narrative: 7 thematic groups (not strictly chronological — grouped by what the work
was actually about) covering all 24 `TRANSCRIPT.md` sections, each entry a one-to-three-
sentence hook plus a `§N` pointer. Chose plain-text `§N` references over generated anchor
links — this codebase already cites `TRANSCRIPT.md` sections this way elsewhere, and hand-
computing GitHub's heading-slug algorithm correctly for headers containing em dashes and
punctuation (several `TRANSCRIPT.md` headers do) is fragile enough to not be worth the risk
of a silently broken link. Updated `README.md`'s pointer line so it frames `HISTORY.md`
correctly as the index, not a parallel narrative.

No code changed this session — documentation-only, verified by inspection (structure,
cross-references, accurate line/section mapping) rather than a test run, since there was
nothing to test.

## 27. Closing five flagged gaps: two fixes, two confirmations, and one new finding

**User** asked to close out five items in one batch: confirm/fix the `evals/matching.py`
`grounded`-flag gap; fix the Asia-gym hedge that undercuts itself by revealing both branches'
figures; a systematic corpus grep for scope/exception language to rule out a second latent
`SCOPE`-shaped chunking bug; live stress tests of precedence logic beyond two-rule conflicts
(three overlapping rules; a benefit type the global handbook doesn't mention at all); and a
batched P2 sweep (verdict case-sensitivity defensive check, `VectorIndex.search()`'s stale
`k=5` default, a deterministic citation-name cross-check). Mid-turn, the user separately
flagged that `TRANSCRIPT.md` had gone two full sessions (the `DESIGN.md` write-up and the
`CLAUDE.md`/`HISTORY.md` compression) without an entry — closed as §25/§26 above before
continuing this batch, so there's no gap in the record.

Worked the corpus-grounded items first. Pulled the real 73-chunk corpus directly
(`index/chunks.jsonl`) and grepped every chunk for `specifically|except|for all other|
unless|supersede[sd]?|does not apply|other than|excluding|only applies|refer to|nothing in
this`. Found five distinct clauses with dilution-risk shape beyond the already-fixed `SCOPE`
case (two merged into the global handbook's `SECTION 1` welcome paragraph, one merged into
`SECTION 8`'s local-law carve-out, two already-well-tested APAC `CONFLICTS AND PRECEDENCE`
clauses) and live-tested retrieval rank for each with realistic queries via the real
`VectorIndex`: all ranked top-3 of 25 candidates, comfortably inside `SEARCH_K=10` — no second
latent bug. Then stress-tested precedence beyond two-rule conflicts, live: a genuine 3-layer
chain (Taiwan 2025 PTO — regional override, then a statutory-minimum caveat, then a correct
refusal to guess Taiwan's actual statutory figure since it's not in the corpus) held correctly
across 3 reps, as did a benefit type absent from every document (stock options/equity
compensation) across 3 reps.

TDD'd the eval-matcher fix: `evals/matching.py`'s numeric and hedge markers now require
`grounded=True`, so a rejected/ungrounded answer can never "pass" just because the expected
marker happens to appear inside the dumped rejection text by coincidence (the exact mechanism
that let a real `verify_answer` bug go unnoticed in the previous session). TDD'd the P2 sweep
together, since all three touch `verify_answer`/`VectorIndex`: `verify_answer`'s verdict check
is now case-insensitive (`.upper().startswith(...)`, defensive — `VERIFY_TOOL`'s enum already
guarantees exact case for the tool-based path, but `verify_answer()` is general-purpose);
`VectorIndex.search()`'s default `k` now matches `SEARCH_K` instead of a stale `5`; and a new
deterministic pre-check hard-fails `grounded=False` if a draft's citation names none of the
actually-retrieved documents by `display_name` — same "fail closed without a model call"
posture as the existing empty-`cited_chunks` check. Required rewriting `tests/test_verification.py`'s
fixtures to use realistic `format_answer()`-shaped drafts (with real citations) instead of bare
sentences, since the new citation check would otherwise short-circuit tests whose actual
purpose was exercising a different code path. 79/79 offline tests pass after this stretch.

The Asia-gym hedge fix needed two live-tested rounds, the same shape as this project's
verdict-ordering fix from an earlier session. Round 1 (an explicit WRONG/RIGHT example: don't
reveal what the answer would be under each branch, even if both branches converge) closed most
of it, but 1 of 4 reps still leaked "covered APAC employees would actually get the global
$50/month rate... if you're elsewhere, only the global $50/month rate applies" — almost
verbatim the WRONG example, just phrased as two separate conclusions instead of one combined
"either way" statement. Round 2 added a second, narrower closure: naming each candidate
policy's own number as "just supporting detail" for the rule is exactly as disqualifying as
naming the converged answer. Retested with 6 reps: 4 clean, but 2 hit a *different*,
newly-surfaced issue — `verify_answer` incorrectly rejecting a correct draft, reasoning that
the APAC gym rate might deserve PTO-style regional precedence (it explicitly doesn't; the same
excerpt routes "all other benefits" to the global rule). Confirmed via `eval.py`'s own
Asia-gym rep (clean) that this wasn't a regression from the hedge-wording change itself.

Wrote up the new finding as `docs/backlog/2026-08-22-verify-answer-carve-out-overgeneralization-false-rejection.md`,
following the established ticket format: root cause hypothesis (the verifier may be
over-generalizing the "specific carve-out" pattern from the two already-closed sibling tickets
to a benefit the same excerpt explicitly *doesn't* carve out), both captured rejection texts
verbatim, and a suggested fix mirroring the sibling tickets' boundary-clause approach — not
implemented, since it needs the same adversarial-testing rigor those tickets required before
shipping, which this session didn't have budget to also do.

Ran the full `evals.edge_cases` 36-case suite live to refresh a number `CLAUDE.md` had already
flagged as stale, and to check the P2/citation-check changes across more query variety than
the 8-query suite covers: 32/36. Diagnosed all 4 failures individually rather than reporting a
raw count — none were regressions from this session's changes:

1. **"Republic of China" PTO** — the model correctly hedged instead of resolving to Taiwan,
   because the corpus only ever writes "People's Republic of China" (mainland China, a
   different country) verbatim — resolving "Republic of China" would require outside
   geopolitical knowledge the entity-hallucination fix from an earlier session explicitly
   forbids. The edge case's own expectation is stale, not the system. Left a code comment on
   the case in `evals/edge_cases.py` explaining this, rather than "fixing" it by loosening the
   anti-hallucination guardrail.
2. **"Chinese national remote from California"** — an exact recurrence of the
   absence-inference ticket's own flagship reproduction, closed in an earlier session. Logged
   as a "Recurrence observed" addendum on that ticket per its own explicit instruction to
   watch for exactly this, not re-investigated (the ticket's adversarial battery already
   proved no over-generalization; a single recurrence is consistent with the intermittent
   rate it already documented, not proof of regression).
3. **Maternity leave "unknown"** — a correct answer ("No specific number of weeks/days is on
   file...") that didn't match any existing marker. Pure eval-matcher gap, fixed with a new
   `"no specific number"` marker and a TDD regression test.
4. **China conference budget** — the *draft* (not the verifier) mischaracterized gym as a
   PTO-style carve-out, and `verify_answer` correctly caught its own mistake. Added as
   corroborating evidence to the new carve-out ticket: the gym-precedence confusion shows up
   on both the draft-generation and verification sides of the loop, not just verification.

Final state: 79/79 offline, `eval.py` 8/8 live, `edge_cases.py` 32/36 with every failure
diagnosed and either fixed, logged against an existing ticket, or documented as a stale test
expectation. Updated `CLAUDE.md` (current status, backlog list) and `docs/DESIGN.md`
(components, known limitations, path-to-scale item 2) to match, and this transcript
incrementally as each item landed.

## 28. A live nondeterminism report, root-caused precisely instead of re-patched again

**User** reported the same query, run twice, giving two different answers — a correct draft
one time, a `verify_answer` rejection the other — for `"What is the PTO allowance for a
California employee in 2026?"`, one of the take-home's own 8 example queries. Framed it as a
recurring issue ("this seems to be a reoccurring issue in our system... How can we make it
more rigorous") and asked for a fix, not just a rerun.

Invoked `superpowers:brainstorming` explicitly for this. First proposal (a retry: if
`verify_answer`'s first call says `UNSUPPORTED`, try once more before falling back) was a
mitigation, not a diagnosis — presented with its real tradeoff named (retrying also gives a
genuinely wrong draft a second chance to slip through). **User pushed back directly**: "this
still leaves the possibility of returning an incorrect answer and adding additional call
overhead... probe this system carefully." Correct call — proceeded to actually investigate
before proposing again.

Wrote a scratch instrumentation probe (not committed) that monkeypatches `VectorIndex.search`
to log every query and every chunk cited, then ran the reported query 8 times live. All 8 came
back clean, and — the key finding — the APAC handbook's `SCOPE` excerpt (the one naming
China/Japan/Taiwan and saying "personnel outside these three jurisdictions should refer to the
global Acme Employee Handbook") was retrieved and cited in every single rep. This ruled out
retrieval variance as the cause before proposing anything. The actual mechanism was then
visible directly in the user's own originally-pasted rejection text: the verifier stated *the
fact that proves the claim* ("the only regional handbook provided is the APAC Benefits
Handbook covering China, Japan, and Taiwan") and then declined to draw the one-step conclusion
that California isn't covered — a specific, diagnosable gap, not generic sampling noise.
Root cause: `build_verification_prompt`'s two existing credited patterns are anchored to
specific wording ("for all other cases...", "unless a specific provision states otherwise"),
and the `SCOPE` excerpt's actual wording (an enumerated closed list + an explicit "everyone
else, refer elsewhere" instruction) doesn't pattern-match either trigger phrase, despite being
at least as strong evidence as pattern (b) requires.

Revised recommendation to a precise prompt fix — a third credited pattern, "closed-list
exclusion" — presented with the same tightened-boundary-clause and adversarial-testing
discipline as the two prior verify_answer fixes, and explicitly ranked ahead of the earlier
retry idea (held in reserve only if adversarial testing still showed residual failures).

**User** then invoked `superpowers:subagent-driven-development` directly. Flagged the mismatch
rather than force-fitting it: that skill needs a written implementation plan and independent
tasks to dispatch across subagents; this was one cohesive, sequential fix with no plan file,
matching the brainstorming skill's own "bounded" path ("implement via the normal development
workflow — no plan document") instead. Asked which the user wanted via `AskUserQuestion`;
answered "approve and implement directly."

Implemented via TDD: a new test asserting the prompt credits `"closed"`/`"enumerat"`ed-list
language plus a `"refer"` instruction, confirmed red, then added pattern (c) to
`build_verification_prompt` with the same boundary-clause discipline as (a)/(b) ("only applies
when... it's unclear whether a list is meant to be closed/exhaustive rather than illustrative,
that is a real ambiguity and should still be flagged as UNSUPPORTED"). 80/80 offline tests
pass. Adversarially tested via a second scratch probe (not committed) using the real cited
excerpts (`SCOPE`, `CONFLICTS AND PRECEDENCE`, the global handbook's `4.2 PTO` paragraph): the
correct draft went 6/6 `SUPPORTED` (previously intermittent, and this is the exact query that
started the report); three adversarial controls at 3 reps each (an inverted-direction draft
wrongly claiming California *is* covered by the closed list, a fabricated-number draft, an
unrelated-fabrication draft) all stayed correctly `UNSUPPORTED`, 9/9. End-to-end `main.py --ask`
reconfirmed clean 4/4, `evals.eval` 8/8 live, and — checked specifically since it's the same
underlying inference — the other open recurrence on this ticket ("Chinese national remote from
California," found during the prior session's `edge_cases.py` run) reconfirmed clean 3/3 too.
Updated `docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md` with a
"Second fix implemented" section, `CLAUDE.md`, and `docs/DESIGN.md`'s verification component
section to describe all three credited patterns together.

## 29. Final readability/cleanliness pass and wrap-up

**User** asked for a five-item final pass: code readability (naming, dead code, comments),
confirmed-accurate open/closed references across `CLAUDE.md`/`DESIGN.md`, a final offline +
live confirmation run, doc-set internal consistency (old spec marked superseded, `HISTORY.md`
still a short index, `CLAUDE.md`'s status current), and a README pass for cold-repo
readability.

**Readability.** Re-read every `src/`, `evals/`, and top-level `.py` file fresh. Grepped for
TODO/FIXME/XXX markers, commented-out code (regex over lines starting `#` followed by
code-like tokens), and unused imports (AST-based, across `src/`, `evals/`, `tests/`, and the
two entry points) — all clean; the codebase's established discipline (no dead code, only
"why" comments) held up under a systematic check, not just a read-through. One real, small
finding: `_format_excerpts()` in `src/agent.py` had no type hint, and `ScoredChunk` (its
actual parameter type) wasn't even imported — inconsistent with the rest of the file's full
typing. Fixed.

**Stale references.** Cross-checked all 7 backlog tickets' own `Status:` lines against every
"open"/"fixed"/"closed" claim in `CLAUDE.md` and `DESIGN.md` — all accurate, no drift either
direction. Found a different, real staleness class instead: `DESIGN.md` still described
`CLAUDE.md` as "the complete decision log... in full detail" in three places (the repo map
table, "Known limitations," "Design principles," and "Where to find more") — true when
`DESIGN.md` was originally written, false since the `CLAUDE.md` compression two sessions ago
moved that role to `TRANSCRIPT.md`/`HISTORY.md`. Fixed all four. Also found every
`src/agent.py` and `src/verification.py` line-number citation in `DESIGN.md` had drifted
(both files grew across the last two sessions' fixes — `answer_question` moved 204→214,
`format_answer` 173→183, `verify_answer` 49→60, `SEARCH_TOOL` 93→103, `SUBMIT_ANSWER_TOOL`
117→127, `VERIFY_TOOL` 144→154, `verify_llm_call` 180→190); `retrieval.py`/`models.py`/
`chunking.py` references were untouched files and still correct. Verified every citation
programmatically (read each cited line, print what's actually there) after fixing, not just
by eye.

**Doc-set consistency.** Added an explicit "Superseded by `docs/DESIGN.md`" status line
inside `docs/superpowers/specs/2026-08-19-rag-qa-system-design.md` itself (previously the
supersession was only stated from `README.md`/`DESIGN.md`'s side — someone opening the old
spec directly wouldn't have known). Confirmed `HISTORY.md` is still a genuine short index
(220 lines, 28/28 `TRANSCRIPT.md` sections covered by one-to-three-sentence hooks, not
regressed into a second narrative) via a direct `§N` cross-reference count. Rewrote
`CLAUDE.md`'s "Current status" paragraph, which had grown into a mini-narrative across two
sessions' incremental edits (violating the file's own stated "session-continuity only, not a
decision log" purpose) — trimmed to facts + pointers, and fixed a subtler staleness: the
paragraph reported `edge_cases.py`'s pre-fix 32/36 without being explicit that the fix landed
minutes earlier resolves one of those four failures, which could read as a live discrepancy
rather than a dated snapshot. Now states the number is pre-fix and points to the ticket rather
than implying present-tense accuracy it can't back up without an actual rerun.

**Final confirmation.** 80/80 offline tests pass; `evals.eval` 8/8 live (both re-run after
all doc/code edits landed, not before); a plain-import smoke check confirmed the
`ScoredChunk` import change didn't break anything.

**README pass.** Walked it as a cold reader against the literal dependency graph, not just
prose flow, and found the existing section order implied a stricter chain than actually
exists: `pytest` and both `evals/` scripts each call `ingest.build_index()` directly and
build their own in-memory index every run (confirmed by reading `tests/test_retrieval_recall.py`'s
imports) — none of them need `python ingest.py` to have been run first, only `main.py` does.
Also confirmed the three source `.docx` files are checked into git under `Take Home Test/`
(not gitignored, no separate download step needed) and that `ANTHROPIC_API_KEY` is required
only from "Ask questions" onward — `pytest` needs neither the built index nor a key. Rewrote
the README to state these dependencies explicitly rather than relying on section order to
imply them, and added a one-line Python-version note (3.9, the actual venv version, given a
backlog ticket already documents 3.9 as a real constraint for future vector-DB options).

## 30. `edge_cases.py` rerun, a genuine ticket recurrence spotted, then systematic-debugging on it

**User** asked to run `evals.edge_cases` and show the output. 31/36 this time. Diagnosed each
of the 5 failures individually rather than reporting the raw count: 1 already-known stale test
expectation, 1 verdict that omitted the actual PTO figure (a new formatting-instruction miss),
1 new phrasing variant of the already-known matcher-gameability gap ("no specific fixed
number," dodging both existing markers), and — the significant one — 1 rejection whose
reasoning was a clean match for the already-*closed* precedence-false-rejection ticket's
pattern (PTO's specific carve-out treated as an unresolved conflict with the general rule),
plus 1 more matching the still-open carve-out-overgeneralization ticket. Presented all 5 with
this categorization rather than just the pass count.

**User** asked for the exact question and full API response for the significant one (China PTO
2025). Gave the complete, unedited text — no summarizing ellipses.

**User** then asked directly: "so the issue we are seeing is still related to the verifier
bug?" Answering precisely required correcting something from the prior message: China-PTO-2025
wasn't the *carve-out-overgeneralization* ticket (which I'd called "still open" moments
earlier) — it matched the *precedence-false-rejection* ticket instead, a different, already-
*closed* ticket. Laid out all four `verify_answer` tickets in a table with what each is
actually about, and the resulting picture: three of four now show live failures (only the
prefix-parsing ticket's *structural* fix — an enum-constrained tool call — has zero
recurrences), while every ticket whose fix was a free-text prompt instruction has recurred at
least once. Named the pattern this reveals explicitly: the "guarantee structurally, don't hope
via prompt" principle isn't just a nice idea, it's the only one of these fixes holding cleanly
so far.

**User** then invoked `superpowers:systematic-debugging` directly on the carve-out-
overgeneralization ticket, with explicit constraints: don't fix until root cause is confirmed
via live instrumentation reproducing the two originally-captured rejections, and explicitly
resolve the ambiguity the ticket's own "Related tickets" section had flagged — is this a
genuinely new failure mode, or an over-broad application of pattern (a)'s existing boundary?

Phase 1 investigation, two methodologies:
1. Isolated `verify_answer()` probes against the real cited excerpts (`SCOPE`,
   `CONFLICTS AND PRECEDENCE` ×2, `REGIONAL BENEFITS` ×2, global `SECTION 3`/`SECTION 8`),
   comparing the current prompt (patterns a/b/c intact) against a surgically-stripped version
   with the entire credited-patterns block removed — 8 reps each, against two different
   reconstructed drafts (the first attempt used too simple a draft; the second more faithfully
   matched the original rejections' description of explicit $50-vs-$30 comparison language
   within a hedge). **32/32 SUPPORTED — zero reproduction either way**, meaning pattern (a)'s
   mere textual presence, holding draft and excerpts fixed, doesn't reliably trigger it alone.
2. Full end-to-end `answer_question()` reproduction with live search-call instrumentation, 12
   fresh reps of the real query. **10/12 SUPPORTED, 2 rejected** — but neither rejection
   matched the ticket's original shape. One was a genuine citation-year attribution slip
   (draft cited "2026, Section 8"; the actually-cited chunk was 2025's, textually identical
   content) — the verifier catching a real error, arguably correct behavior. The other was a
   **correct** rejection of a **genuinely wrong** draft that itself mischaracterized the APAC
   gym rate as taking precedence — a second live recurrence of the draft-generation-side
   confusion already logged in the ticket's "Corroborating evidence" section, not the
   verifier-side bug the ticket is actually about.

Resolved the ambiguity precisely: re-reading the two *original* captured rejections against
this new evidence confirmed they genuinely are over-broad pattern-(a) application — both
explicitly self-describe the analogical leap in their own reasoning text ("PTO is called out
with an explicit local-precedence carve-out, suggesting other regional benefits... are
similarly specific regional entitlements"). But 44 live reps across both methodologies could
not re-trigger that exact mechanism fresh — meaning root cause is understood with high
confidence *analytically*, without a reliable live trigger in hand to adversarially test a
candidate fix's before/after impact against, the same rigor this project's other `verify_answer`
fixes were held to before shipping. Reported this nuanced state honestly rather than either
declaring a clean reproduction that didn't happen or proceeding to a fix without one, and asked
how to proceed.

**User decision:** hold off entirely — no `build_verification_prompt` or other `verify_answer`
code change for this ticket, severity and false-rejection framing unchanged from the original
triage, document the findings. Updated the ticket with a full "Root cause investigation"
section (analytical confirmation, both reproduction attempts' results, the two new findings,
and the explicit hold decision), appended the second draft-side-confusion recurrence to
"Corroborating evidence," updated "Suggested fix"/"Test plan" to reflect what's now known
without re-writing them as if the fix had shipped, and updated `CLAUDE.md`/`DESIGN.md`'s
one-line and "Known limitations" mentions (both previously said "not yet root-caused," now
stale given the analytical confirmation).

## 31. A live timing breakdown, then three exploratory architecture questions

**User** asked for a single live query with a per-step timing breakdown, pasting the "Life of
a query" doc section verbatim as the step list to measure against. Ran one instrumented live
call and reported real per-step numbers, including the ~4.7s one-time
`sentence_transformers`/library import cost separate from `answer_question()`'s own time.

**User** then asked three exploratory questions in one message, answered conversationally
(recommendation + main tradeoff each, no code changes):
1. Would a long-lived process eliminate the ~4.7s import gap? Yes — it's a one-time
   process-startup cost, not a per-question cost; `main.py`'s own 8-query loop already only
   pays it once.
2. What would a single-Claude-call version look like? Sketched the shape and the tradeoff:
   collapsing search+answer+verify into one call would save a round-trip but give up the
   independent-verification-pass design principle this project has repeatedly relied on to
   catch real fabrications (§20) — recommended against it.
3. What would per-employee privacy isolation need? Sketched the shape (per-employee document
   scoping at retrieval time, not just prompt-level trust) without implementing anything —
   flagged as a genuinely architectural change if ever pursued, not a bounded one.

## 32. `docs/DESIGN.md` condensed to a strict Choice/Why/Tradeoff structure

**User** asked to make `DESIGN.md` more concise for an external reader: keep "Life of a query"
byte-identical, but condense every other section to design choice + 1-2 sentence why + 1-2
sentence tradeoff, without deleting the evidence entirely. Condensed all six "Core components"
subsections into that strict structure and trimmed one "Known limitations" bullet; file went
from 480 to 398 lines. Republished the existing artifact (same URL, same file path) with the
condensed content.

## 33. `DESIGN.md`'s intro merged into one section, a table of contents added

**User** asked to condense the title/intro/"System summary" split into one section and add a
table of contents. Merged the three-part opening (title paragraph, "if you're new here"
pointer, and the separate "## System summary" section) into a single flowing opening section,
then added a "## Contents" section linking every top-level heading, with numbered sub-links
for the multi-part "Core components" and "Path to scale" sections. Republished the artifact.

The user then made a manual edit directly to the intro's wording on disk (shorter, more
clipped sentences — "Doc covers what each piece does..." instead of the earlier full-sentence
phrasing) between artifact-republish requests. Treated as a deliberate style choice, not
reverted; republished as-is when asked again, and again after this session's citation-scoping
change landed.

## 34. Is the system overfit to `.docx`? What would CSV support need?

**User** asked whether the codebase is overfit to `.docx`, and what other formats like CSV
would need. Read `ingest.py`, `src/models.py`, and `src/chunking.py` before answering rather
than guessing. Finding: ingestion is genuinely `.docx`-specific (`ingest.py` hardcodes
`read_docx_paragraphs()`, no format dispatch exists), but everything downstream — chunking,
retrieval, the agent loop, verification — is already format-agnostic, since none of it touches
`.docx` internals; it only ever sees the plain `Paragraph`/`Chunk`/`DocMeta` dataclasses.
Recommended against building a speculative format-dispatch layer now (YAGNI, consistent with
how every other scale question in `docs/backlog/` has been handled) — the bounded fix, if a
real second format shows up, is a new reader module producing `Paragraph`s plus an
extension-based dispatch in `ingest.py`; `documents.yaml`'s schema doesn't need to change.

**User** followed up: "so to handle other formats we need to change ingest only?" Corrected
precisely rather than confirming loosely: no — a new reader module is also needed (e.g. a
`csv_reader.py`; `docx_reader.py` only knows OOXML), and `chunk_document()`'s heading-detection
heuristic (paragraph style + length guard) is meaningless for tabular rows, so a CSV's
chunking strategy would need checking against real CSV content rather than assumed adequate
by default. `ingest.py` changes only to dispatch to the right reader, not to do the reading
itself.

## 35. Brainstorming stronger, deterministic grounding checks

**User** invoked `superpowers:brainstorming` directly, proposing three deterministic checks to
add alongside the existing LLM-based `verify_answer` pass: citation must name a retrieved
chunk, citation must name the document actually retrieved, and cited text must be present in
the evidence. Classified Bounded (existing `verify_answer`/`format_answer` code, no new
subsystem) and read `src/agent.py` + `src/verification.py` in full before proposing anything.

Found the first two ideas were already partially implemented, but weaker than they sound: the
existing check (`if not any(c.doc.display_name in draft for c in cited_chunks)`) scans the
*whole draft* for any retrieved document's name, not the citation field specifically — so a
coincidental mention elsewhere in `reason` could mask a citation naming the wrong document
entirely. The third idea had no existing implementation and a real design risk: `reason` is
explicitly required (by `SYSTEM_PROMPT`) to be paraphrased HR-voice prose, not a quote, so a
literal substring match of `reason` against the excerpts would false-reject by design.

Asked one clarifying question on scoping idea 3 before proposing a design: full substring
match (rejected as conflicting with the paraphrase requirement), numeric-only grounding, or
numeric + named-entity grounding. **User chose numeric + named-entity grounding** — which also
directly hardens the still-open, prompt-only, unverified-at-scale fix from §20
(`docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md`) with a real structural
guarantee.

Presented a short design: (1) scope the citation check to the parsed-out citation field only
(via a regex anchor on `format_answer()`'s guaranteed `"— (...)"` trailing shape — parsing a
format the codebase itself already enforces, not fragile free-text parsing), explicitly
deferring section-level citation matching as too fragile given freeform compound citations;
(2) numeric + named-entity grounding on the verdict+reason segment, flagged as the riskiest
part (acronym/false-positive risk) and requiring the usual TDD + adversarial live-verification
discipline before shipping.

**User decision:** start with only the citation-scoping change (item 1) for now.

## 36. Citation-scoping fix: TDD, live-verified, and a fresh backlog reproduction found along the way

Implemented item 1 via TDD. Red test first: a draft with a document name mentioned in `reason`
but a fabricated document in `citation` — confirmed it passed under the old whole-draft check
(false negative demonstrated directly, not assumed). Added `_extract_citation()` (parses the
trailing `"— (...)"` segment `format_answer()` guarantees, falling back to the whole draft if
the marker's absent) and scoped the existing document-name check to that segment. 81/81
offline tests green, including the new one.

Live-verified with `python -m evals.eval` (API key supplied inline per this repo's standing
constraint that a user's own `export` doesn't reach the session's separate shell): **7/8
passed.** Confirmed via `git diff` that the one failure's cause — the LLM verifier's own
rejection reasoning, not the new deterministic check's rejection message — was untouched by
this change; it was instead a **fresh, unprompted live reproduction** of the still-open
`docs/backlog/2026-08-22-verify-answer-carve-out-overgeneralization-false-rejection.md`, the
first rejection since that ticket opened whose reasoning clearly exhibits the ticket's *core*
mechanism (pattern-(a) carve-out reasoning over-generalized onto the APAC gym rate) rather than
just the two side-mechanisms the 2026-08-23 investigation (§30) had turned up instead. Logged
this as a new "Fresh reproduction (2026-08-24)" section in that ticket, updated its Status line
accordingly, and left the ticket's "hold, don't fix" decision unchanged — a single occurrence
still isn't a before/after baseline, per that ticket's own stated bar.

Committed the citation-scoping change once the user configured git's local identity (the
commit had failed earlier in the session with "Author identity unknown").

## 37. The eval matcher redesign: brainstorming → spec → plan → subagent-driven build → merge

**User** invoked `superpowers:brainstorming` directly, asking to fix the eval matcher's
keyword/substring approach to also understand numeric equivalence, explicit unknown/hedged
answers, rejected answers, document/version correctness, and required-vs-forbidden claims.
Classified Architectural (the matcher's expectation format is the interface all ~44 existing
eval cases depend on, and two of the five asks needed data — `VerifiedAnswer.cited_chunks` —
the matcher didn't have). Read `evals/matching.py`/`eval.py`/`edge_cases.py`/
`tests/test_matching.py` in full before proposing anything; found the existing "unknown"
marker's `wording OR not grounded` logic was already a real bug-masking gap the redesign
needed to fix, not just extend. Four clarifying questions, each with a recommended option the
user picked every time: fully deterministic (no LLM-judge fallback — importing sampling
variance into the harness meant to catch that exact problem elsewhere was rejected on
principle); currency/comma/spelled-out-number equivalence only (not units); structured
metadata against real `cited_chunks`, not citation-text parsing, for document/version checks;
additive `Expectation` dataclass alongside the existing plain-string shorthand, not a full
migration. Design presented in 7 sections, approved as-is. Spec written to
`docs/superpowers/specs/2026-08-24-eval-matcher-redesign-design.md`, self-reviewed (added one
clarifying note pre-empting a specific, known-dangerous misreading: don't import
`VectorIndex.search()`'s "`None` matches any year filter" retrieval-time rule into this
after-the-fact metadata check), committed.

`superpowers:writing-plans` produced a 9-task plan
(`docs/superpowers/plans/2026-08-24-eval-matcher-redesign.md`): `VerifiedAnswer.cited_chunks`
→ `matches()` signature refactor → `Expectation` + numeric equivalence → unknown/hedge/rejected
split → doc_type/version_year checks → required/forbidden → `explain()` diagnostics → migrate
`PRECEDENCE` + add an entity-hallucination-guard category → live verification. Self-review
caught and fixed one real defect before handoff: a duplicate-import instruction in Task 3 that
would have double-imported `Expectation`.

**User** chose Subagent-Driven execution. Per the skill's own rule ("never start on
main/master without explicit consent") and given this run would make ~9+ unsupervised commits
with no per-commit check-in — a materially bigger step than this session's established
one-commit-at-a-time pattern — asked explicitly rather than assuming continuation of that
pattern. **User chose an isolated worktree.** Bypassed the native `EnterWorktree` tool
deliberately: its default `baseRef` branches from `origin/main`, which was 2 commits behind
local `main` (missing the plan/spec commits and the session's citation-scoping fix) — created
the worktree manually from local HEAD instead, after committing the plan file that would
otherwise have been left behind as an untracked file the worktree wouldn't inherit.

All 9 tasks executed: fresh implementer (haiku, since every task's plan text already contained
complete code — pure transcription-plus-testing) + fresh reviewer (sonnet) per task, each
review scoped with the specific correctness point most likely to hide a bug (the `AND` vs `OR`
logic in unknown/hedge; the `any()` vs `all()` and `version_year=None` semantics in doc/version
checks; the direction of `forbidden`'s `grounded`-gating). All 9 came back clean on first
review; one Minor (a report's self-reported test-count arithmetic, no code impact) logged and
deferred per the skill's own rule that minors never enter the fix loop.

Live verification (Task 9) found real signal beyond the plan's own predictions. `evals.eval`:
8/8. `evals.edge_cases`: 32/38 — diagnosed all 6 failures individually rather than reporting
the count: 4 were pre-existing, already-documented, unrelated-to-this-branch issues (a stale
test expectation, two `UNKNOWN_MARKERS` phrasing gaps, one LLM draft-generation sampling
miss); 1 was a fresh, cleaner, single-mechanism reproduction of the still-open carve-out-
overgeneralization ticket (§30/§36) — logged as a second same-day occurrence, left unfixed per
that ticket's standing hold; 1 was a genuine, load-bearing bug in this branch's own new
`required` capability, reproduced directly (not assumed) via a standalone regex check: the
boundary-matcher it reused from numeric markers excluded any trailing comma, so a required
word immediately followed by a comma in ordinary prose (`"China, Japan, and Taiwan"`) silently
failed to match. Ruled against patching the shared, widely-relied-upon numeric-boundary
function (would reopen the false-positive class it exists to prevent); added a new,
purpose-built word-boundary matcher instead — a deliberate deviation from the plan's literal
Task 6 text, ledgered as a ruling. Fixed via the same implementer+reviewer cycle, then
re-verified live end-to-end (not just via the offline regression test): the two
`entity_hallucination_guard` cases that had failed now passed 2/2 live.

Final whole-branch review (opus, fresh eyes on the full 10-commit diff) returned "Ready to
merge: With fixes" — no Critical findings, but a real one worth naming: the reviewer
independently verified against the live index that `VerifiedAnswer.cited_chunks` accumulates
*every* chunk retrieved across a whole conversation, not just what the answer's citation names
— meaning the new `doc_type`/`version_year` checks were satisfied by nearly any retrieval for
a precedence question, making the `PRECEDENCE` migration's own comment (claiming these checks
"assert which document actually governed the answer") false. Also found the `doc_type`/
`version_year` fields weren't `grounded`-gated (inconsistent with every sibling field), and
that `_matches_expectation()`/`explain()` fully duplicated all 8 field-checks verbatim — a
risk the branch had already tripped over once, during the Task 9 fix. Bundled 3 Important +
4 low-risk Minor findings into one fix-wave dispatch (case-insensitive `forbidden`, a stale
test rename, mid-file import hoisting, a defensive `list()` copy on `cited_chunks`);
deliberately deferred the 2 remaining findings (the deeper `cited_chunks`-semantics gap; a
narrow, currently-unreachable `required`-numeric-term edge case the Task 9 fix's own word-
boundary approach reopens) to two new backlog tickets rather than redesigning mid-fix-wave.
Fix wave landed clean on first scoped re-review (verified live, not just via the report:
re-ran the exact `grounded=False` reproduction the reviewer used). Controller directly updated
`CLAUDE.md`/`docs/DESIGN.md`'s stale test counts and the "Eval harness rigor" tradeoff/roadmap
sections afterward — docs-only, no code-review gate needed for known-facts corrections.

**User** chose to merge locally (not push/PR). Fast-forwarded onto `main` (`ab4ed50..2d7898c`,
13 files, +723/-129), re-confirmed 111/111 on the merged result from the main repo (not just
the worktree), then cleaned up: worktree removed, feature branch deleted, SDD workspace
removed (git history is the permanent record now). Final offline count: 81 → 111 across this
whole arc. Two new backlog tickets and one carve-out-ticket update are the durable trace of
what was deliberately deferred, not silently dropped.

## 38. `VerifiedAnswer.rejected_draft` removed — confirmed dead first, not assumed

**User** pointed at the exact `docs/DESIGN.md` "Known limitations" bullet flagging
`rejected_draft` as write-only dead weight and asked to delete it if a repo-wide scan confirmed
no usage. Grepped the whole repo for the field name before touching anything: four hits, all in
`tests/test_verification.py` asserting the field's value — zero production callers. Removed the
field from `VerifiedAnswer` and its two write sites in `src/verification.py`, removed the four
now-dead test assertions (kept every surrounding test intact), and fixed the three docs that
had described it as a real, load-bearing capability: `DESIGN.md`'s "Life of a query" step 7 (no
longer claims a draft is preserved anywhere) and its "Known limitations" bullet (deleted, since
the limitation it described no longer exists), and the named-entity-hallucination backlog
ticket's "Suggested follow-up" section (updated to say the field existed for exactly that
purpose but was removed as confirmed dead code, past tense). Left the already-completed
eval-matcher-redesign plan/spec files untouched — they're point-in-time execution records of
already-shipped work, same as this project has always treated superseded specs. 111/111 tests
still green (net effect: fewer assertions, same test count, since no whole test function was
deleted). Committed directly to `main` — user-directed cleanup, no brainstorming/plan overhead
for a bounded, explicitly-scoped deletion.

## 39. `DESIGN.md` restructured around 7 core questions; real, measured SLOs replace the doc's implicit "trust me"

**User** judged `DESIGN.md` too detailed and gave seven organizing questions (what the system
does, invariants, architecture, why the major decisions were made, known failure modes, what
happens at scale, how correctness is known) plus explicit follow-up asks: a "System Goals &
Invariants" section with seven named invariants stated verbatim, a "Non-goals" section stated
verbatim, replacing "never fabricate" with an accurate defense-in-depth framing (the user
supplied the exact replacement wording), and a quantitative SLO section — explicitly "don't
invent them, get real numbers from the system we have built."

Checked all seven proposed invariants against the actual code before writing any of them down,
rather than transcribing the list verbatim. Six held. The seventh —
"Reproducibility: the index records the document and embedding versions used to construct it"
— did not: `VectorIndex.save()` (`src/retrieval.py`) persists chunk text/metadata and raw
embedding vectors, but never the embedding model name or a document/corpus version stamp.
Flagged this explicitly rather than writing a false invariant into a document whose whole
purpose is "how do we know it's correct." **User decision:** ignore that invariant for now, no
code changes for this exercise — it was dropped from the section entirely, not documented as
an aspirational gap either.

Rewrote the whole document around the seven questions as top-level sections, trimming
discovery-narrative language throughout the "Why the major decisions were made" section (the
old "Core components" Choice/Why/Tradeoff writeups) — dropped phrases like "confirmed via a
10-query adversarial battery," "this needed two rounds of live strengthening," "regressed an
already-passing test" wherever the underlying decision/tradeoff could stand on its own, since
that evidence trail already lives in `docs/TRANSCRIPT.md` and duplicating it was exactly what
made the doc feel too detailed. "Life of a query" was left untouched (per the standing
instruction from earlier in this document's history to keep it byte-identical). Added the
Goals & Invariants and Non-goals sections verbatim to the user's wording. 480→335 lines net,
despite adding two new sections and a new SLO table.

For the SLO table, actually ran the system rather than estimating. Wrote a throwaway
instrumented script (not committed — scratchpad only) that ran all 46 live take-home + edge-
case queries once, timing each and recording `matches()`/`grounded` outcomes: 41/46 (89%)
correct final answer, latency p50 6.5s / p90 8.5s / p95 9.0s / max 16.0s, and — since this
project's own standing rule is "single live runs have been misleading before" — a false-
rejection number needed more than the single accidental rejection that first run happened to
catch, so ran 3 additional live reps of just the 8 canonical take-home queries specifically to
get a defensible sample (N=32 total): 3/32 (9%) false-rejection rate, and notably all three
rejections landed on gym-benefit precedence questions — a fresh, real confirmation of the
already-open, already-documented carve-out-overgeneralization ticket, not a new problem. Pulled
retrieval-correctness (11/11, 100%) from the existing offline retrieval-recall test suite
rather than re-measuring it live, since it's already a real, deterministic, currently-green
number. Reported the LLM/API transport failure rate honestly as "0 observed, sample too small
to call a rate" rather than inventing a number neither measured nor claimed as a target.

Published the restructured doc as an artifact (same URL, redeployed). **User** then made two
rounds of manual edits directly to `DESIGN.md` on disk between republish requests (once
forgetting to save, caught on the next request) — including merging the separate "What does
the system do?" section into the top intro paragraph, which orphaned a Contents entry pointing
at the now-gone heading. Flagged the dead anchor explicitly rather than silently fixing someone
else's edit; user confirmed removal on the next turn. Separately asked whether margins/font
size could be adjusted for readability — explained that Markdown-published artifacts render
through a fixed host template with no CSS hook from the file's content, offered an HTML-artifact
conversion as the real fix, and the user declined, choosing to keep the simpler Markdown
publish-and-edit-directly workflow over styling control.

## 40. Final cleanup: parallel code + doc review, findings fixed with live verification

**User** asked for a final cleanup and review of everything, plus confirmation that
`TRANSCRIPT.md` was current. Dispatched two fresh-eyes reviews in parallel rather than
reviewing inline: a whole-tree code review (opus, `src/`/`evals/`/`tests/` read in full, no
diff — this codebase had only ever been reviewed incrementally, one change at a time, never
holistically together) and a documentation consistency review (sonnet, `CLAUDE.md`/
`DESIGN.md`/`README.md`/`HISTORY.md`/`docs/backlog/*` checked against the actual repo state,
not just against each other). Handled the "is `TRANSCRIPT.md` current" question directly:
wrote §38-39 for the two sessions since the last entry (the `rejected_draft` removal, the
`DESIGN.md` restructure) before the reviews even came back.

**Doc review**: 2 Critical, 2 Important, 1 Minor. Both Criticals were the same root cause —
`CLAUDE.md` pointed at two `DESIGN.md` section names ("Path to scale," "Known limitations")
that no longer existed after §39's restructure renamed them ("What happens when it scales?",
"Known failure modes"). One finding (HISTORY.md missing §38-39) turned out to be a timing
race — already fixed by the update made minutes earlier — confirmed against the live file
before treating it as real. Fixed the other four directly: the stale section names, a
`verify_answer` line-number citation that had drifted (60→73, the same failure mode this
project has now hit three separate times after doc restructures), and `README.md`'s stale
"36-case" `edge_cases` count plus an incomplete category list.

**Code review**: 0 Critical, 5 Important, several Minor — the most substantive finding of the
whole pass. `evals/matching.py`'s `Expectation.required` field was the one assertion-shaped
check not gated on `grounded=True` (every sibling field — `numeric`/`unknown`/`hedge`/
`doc_type`/`version_year` — already was, from the final-review fix wave two sessions ago that
added the others but missed this one). The reviewer demonstrated it live: a rejected answer
satisfied `evals/edge_cases.py`'s `ENTITY_HALLUCINATION_GUARD` case 2, since `verify_answer`'s
fallback text echoes the verifier's raw rejection reason verbatim and that reason happened to
mention the required terms. Fixed via TDD (red test reproducing the exact exploit first,
confirmed failing, then fixed), and added one sentence to `_check_expectation()`'s docstring
stating the grounded-gating rule explicitly, so the next field doesn't repeat this — the
reviewer's own recommendation, treating the missing invariant statement as the actual root
cause, not just this one field's bug.

Two more real, live-prompt-facing findings: `src/verification.py`'s verifier prompt said "note
two specific reasoning patterns" while listing three — pattern (c), closed-list exclusion, was
added later (§28) and the lead-in was never updated, meaning the model was told to expect two
items before being handed three, which is exactly the shape of mismatch that could make it
under-credit the third. And `evals/edge_cases.py`'s "Republic of China" case had been carrying
a deliberately-stale `"12"` expectation since §21 (documented in place, correctly explaining
why a hedge is now the right answer) — correct as an explanation, but it meant
`python -m evals.edge_cases` could never exit 0. Converted the expectation to
`Expectation(hedge=True)`, kept the comment.

Both changes touch live LLM-facing behavior, so live-verified per this project's standing
rule rather than trusting the offline suite alone: `evals.eval` 8/8, `evals.edge_cases` 34/38,
with the Republic-of-China case and the entity-hallucination-guard exploit-case both confirmed
passing live, not just offline. The 4 remaining live failures were individually diagnosed as
pre-existing, already-documented classes (marker-phrasing gaps, one fresh instance of the
already-known `verify_answer` intermittency) — none newly introduced by these fixes.

Fixed a handful of cheap Minor findings alongside (typed `matches()`/`explain()`'s `expected`
parameter, a redundant duplicate index build, temp test files moved into `tmp_path`, one new
offline test closing real coverage gap on `answer_question`'s untested `max_tokens` fail-closed
path — 111→114 offline tests). Two findings deliberately deferred rather than fixed inline:
asked the user directly whether the verifier's raw rejection reasoning should stop leaking into
the employee-facing fallback message — **user decision: leave it, intentional for this
take-home, useful for debugging** — and appended the `cited_chunks` unbounded-duplicate-
accumulation finding to the existing `2026-08-24-eval-matcher-cited-chunks-weak-doc-version-check.md`
ticket rather than a rushed fix, since the reviewer tied it to the same root semantic question
that ticket already covers.
