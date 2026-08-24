# Build History — index

A navigable index into `docs/TRANSCRIPT.md`'s full raw conversation. Each entry below is a
one-to-three-sentence hook, not a retelling — jump to the cited `§N` in `TRANSCRIPT.md` for
the real detail (root causes, verbatim evidence, exact fixes). For *why the system is built
the way it is today* (components, tradeoffs, current tuning), see `docs/DESIGN.md` instead —
this file is chronological narrative, not current-state reference.

## The task

Build a Q&A system over three Acme HR documents that must retrieve (chunk + embed + search)
rather than stuff full documents into every prompt, must never fabricate, and must answer the
take-home's 8 example queries correctly — including two with no clean numeric answer
(`unknown`, `hedge`). → `§1`

## 1. Brainstorming & design (§1–4)

- **§1 — Reading the brief.** The take-home brief and its 8 example queries were read and
  the hard cases (version conflict, regional precedence, jurisdiction ambiguity) identified
  before any design work started.
- **§2 — Brainstorming.** The six domain rules now pinned in `CLAUDE.md` ("Domain rules the
  system must preserve") were extracted here from the handbooks' own "Conflicts and
  Precedence" sections, not invented for the test set. Also where "agentic multi-hop
  retrieval" (a `search_handbooks` tool Claude calls repeatedly, not single-shot top-k) and "a
  separate grounding-verification pass" were decided as the concrete mechanisms behind
  "never fabricate," not just prompt instructions.
- **§3 — Design presented, a gap caught.** The initial design was presented in chat before
  any code was written; the user caught a real gap in it before implementation began.
- **§4 — A working-style instruction.** The user set the standing expectation for this
  project: strict red/green TDD, YAGNI, DRY — applied throughout every session since.

## 2. Spec, plan, and first build (§5–9)

- **§5 — Writing the spec found real bugs before writing code.** Inspecting the actual
  `.docx` XML (not trusting assumptions) surfaced two real problems that changed the design:
  section headers live inside single-cell "banner" tables that `python-docx` silently drops
  (fixed by reading `word/document.xml` directly, dropping the dependency entirely), and the
  two document families don't share one heading convention — APAC's `pStyle="Compact"` also
  appears on 5 real body paragraphs, which a naive heading rule misclassified and dropped.
- **§6 — Implementation plan.** The spec was broken into 12 concrete tasks before any
  implementation began.
- **§7 — Execution.** Built via subagent-driven development. The offline retrieval-recall
  test suite caught a real near-miss here: the APAC country-scope paragraph ranked 7th of 13
  for a jurisdiction query, just outside the top-5 cutoff — fixed by raising `k` 5→8, in both
  the test and the live search tool.
- **§8 — The whole-branch review found the system had never actually run.** No API key had
  been available during the build, so the real request shape was untested. The review found
  two Critical defects: `temperature=0` (Sonnet 5 rejects any non-default sampling param, 400
  error — the system couldn't answer a single question) and `max_tokens=200` on the
  verification call (silently starved by default thinking tokens, downgrading every answer).
- **§9 — The first live run caught a third defect class no static check could.** The
  "gym benefits in Asia" query sometimes returned a definitive number instead of the required
  hedge, because the ambiguity rule only fired when different candidate jurisdictions would
  produce *different* figures — which this query doesn't. Fixed by hedging on the ambiguity
  itself. The lesson carried forward from §5+§8+§9 together: every defect class in this build
  was invisible at the layer it was introduced and visible only once something real ran
  against it — the origin of this project's standing "verify live, multiple reps" discipline.

## 3. Post-launch tightening: verbosity, latency, structure (§10–12)

- **§10 — Verbosity, then a latency fix that broke correctness.** Answers were tightened
  from padded multi-paragraph responses to 2-4 sentences citing only the determinative
  excerpts. Investigating ~5-10s latency found a real ~6.2s one-time embedding-model load cost
  that wasn't overlapping with the first API round-trip (fixed with `preload_model()` on a
  background thread) — but a second candidate fix (batch tool calls via a prompt nudge) was
  live-ablated (0/4 failures reverted vs. 2/4 with it in place) and reverted after it was
  shown to destabilize `verify_answer` on absence-inference questions.
- **§11 — Prompt caching, investigated and shelved.** A live timing breakdown showed 97% of
  call time is Claude generation, not input reprocessing — caching would save a small amount
  of cost, not the latency that motivated the question. Shelved, not implemented.
- **§12 — The rigid three-part answer structure.** Verdict-first, one reason, one citation —
  iterated against live reruns until it held reliably, closing two real "reasoning leaks
  before the verdict" gaps along the way. (This is the structure that later got fully
  formalized into the `submit_answer` tool — see §23.)

## 4. Production-readiness & the chunking investigation (§13–16)

- **§13 — Designing the edge-case test matrix found two real bugs first.** Grounding the
  test design in the actual retrieved corpus (not assumption) predicted a risk — the
  evergreen APAC handbook's `version_year=None` could get silently excluded by a
  year-filtered search — which the user then hit live. Root-caused as **two independent,
  stacking bugs**, not one: the predicted retrieval bug, and a separate `verify_answer`
  weakness misreading a valid specific-carve-out inference as unresolved ambiguity. Bug 1
  fixed immediately (TDD, `version_year=None` now means "matches any year"); Bug 2 written up
  as a backlog ticket after the user asked the sharp question "could this open up false
  negatives?"
- **§14 — The edge-case plan executed.** Bug 1 shipped (`b7411e4`), the 36-case suite built
  and reviewed. One judgment call worth knowing: an implementer's report mischaracterized 2
  failures as "corpus limitations" — caught and corrected against the real corpus text before
  the task was accepted as complete.
- **§15 — A live nondeterminism report reopened the chunking design.** Running the merged
  system, the user hit the same question giving a correct answer once and a wrong rejection
  once. Chasing it found a genuinely new gap: the single most relevant sentence for
  out-of-APAC PTO questions ranked #19-21 of 71 chunks. Led to a from-scratch chunking-strategy
  discussion (seven strategies considered) that landed on a two-tier design: deterministic
  splitting as the free baseline, LLM-assisted chunking reserved for where testing — never
  manual reading — flags the baseline as insufficient.
- **§16 — The chunking fix, chased through two failed hypotheses.** A corpus-wide
  sentence-split looked right and was wrong in practice (regressed a passing test, didn't even
  improve its target queries). An LLM-semantic-chunking prototype turned out to match plain
  regex splitting exactly on the case tested. What shipped: a manifest-driven,
  per-section opt-in (`documents.yaml`'s `split_sentences_in_sections`) scoped to just the one
  confirmed-broken section, plus a `SEARCH_K` 8→10 follow-up raise for the same reason as the
  original 5→8 fix.

## 5. Retrieval at scale & project cleanup (§17–19)

- **§17 — A vector-DB design, verified rather than assumed.** Real PyPI wheel data (not
  general knowledge) showed only Chroma supports this project's Python 3.9. A live prototype
  (real corpus, real Chroma, hand-rolled BM25 + Reciprocal Rank Fusion) against 10
  deliberately-hard queries found no case where hybrid search beat what's already shipped —
  documented as a ready-to-implement backlog ticket instead of adopted.
- **§18 — Project layout cleanup.** Docs consolidated into `docs/`, eval scripts separated
  into `evals/` from the `main.py`/`ingest.py` product CLI — every cross-reference (25 across
  11 files) checked before moving anything.
- **§19 — A live false positive led to compound test assertions and a test-of-tests.** A
  `"12"` marker passed against a correct answer for the *wrong* reason — the actual
  sub-question being tested was never checked. Fixed by adding compound (AND) assertion
  support to the matcher, plus real offline test coverage of the matcher itself.

## 6. Grounding fixes & a full review pass (§20–21)

- **§20 — A live fabrication, caught by the safety net.** A draft claimed the APAC handbook
  covered "Hong Kong/Singapore" — neither name appears anywhere in the corpus. `verify_answer`
  correctly rejected it before the user saw it. Root-caused as draft-time entity hallucination
  (a different bug shape from the two open `verify_answer` tickets — this was never retrieved
  at all, not misread after retrieval). Fixed with a restrictive `SYSTEM_PROMPT` addition;
  documented as a backlog ticket anyway since 7 clean reproductions can't statistically prove
  a fix against a rare event.
- **§21 — A full review pass, re-sequenced by the user.** Found and fixed, in the order the
  user set (not the order proposed): a real eval-matcher false-positive bug (`"50"` matching
  inside `"$500"`), the shared `evals/matching.py` extraction, the tool-loop iteration cap,
  and — closing both previously-open `verify_answer` tickets at once — a shared
  `build_verification_prompt` addition, adversarially tested (18 live reps, 6 cases) before
  shipping.

## 7. Answer formatting & verification reliability (§22–24)

- **§22 — A formatting-inconsistency report → a plain-prose, compound-question rule.** The
  same compound question came back as a bulleted list in one run, flowing prose in another —
  `SYSTEM_PROMPT`'s structure was written for one verdict, with no rule for a question
  bundling several. The user chose plain prose over bullets, weighing scannability against
  bullets' own real downsides (verdict-first per-bullet, ambiguous citation granularity, list
  framing inviting intro/outro creep).
- **§23 — Plain prose still wasn't guaranteed apart → the `submit_answer` tool.** A prompt
  instruction can't guarantee layout the model has no structural boundary for. Fixed by moving
  formatting out of the model entirely: three separate tool fields (`verdict`/`reason`/
  `citation`) plus a pure, offline-testable `format_answer()` that assembles them
  deterministically. The user's approval question — does forcing three rigid fields fit every
  answer shape? — is worth reading in full; the answer is that the fields enforce the same
  contract that already existed, they don't add a new one.
- **§24 — A ticket written for review, then implemented.** The user asked for a backlog
  ticket *before* any fix to the `verify_answer` prefix-parsing bug (a verifier that reasoned
  aloud and only reached "SUPPORTED" at the end tripped a `.startswith("SUPPORTED")` check).
  Same fix pattern as §23: an enum-constrained `report_verification` tool instead of free-text
  parsing. The user made three scoping calls worth knowing if this pattern recurs: skip
  measuring an occurrence rate when the fix is worth shipping regardless of it, resolve an
  open hypothesis-thread explicitly once a fix makes it moot rather than leaving it dangling,
  and cross-reference a second finding (the eval matcher's `grounded`-blind-spot) instead of
  scope-creeping the fix to cover it.

## 8. Documentation restructuring (§25–26)

- **§25 — `docs/DESIGN.md` written.** An as-built architecture doc for engineers picking up
  this repo cold: repo map, a step-by-step "life of a query" trace, mermaid diagrams, six
  components each with real file/line references and the rejected alternatives that shaped
  them, and a 7-item scale roadmap ranked by actual trigger condition, not backlog age.
  Published as an artifact; `README.md` repointed to it as the primary design reference.
- **§26 — `CLAUDE.md` compressed; `HISTORY.md` rebuilt as this index.** `CLAUDE.md` cut from
  486 to 94 lines — orientation, the six domain rules as an explicit correctness contract,
  operating rules, and gotchas that would actually bite a fresh session, with everything else
  pointed at `DESIGN.md`/`TRANSCRIPT.md`/`backlog/`. `HISTORY.md` rebuilt from a second,
  slightly-shorter narrative into the genuine index you're reading now.

## 9. Closing five flagged gaps (§27)

- **§27 — Two fixes, two confirmations, one new finding.** A batched closure of five
  flagged items: fixed `evals/matching.py`'s `grounded`-blind-spot (numeric/hedge markers now
  require `grounded=True`); fixed the Asia-gym hedge that revealed both branches' figures
  (took two live-tested rounds, same shape as the earlier verdict-ordering fix); a systematic
  corpus grep for `SCOPE`-shaped exception language found no second latent chunking bug (every
  candidate ranks top-3 of 25); live-tested precedence beyond two-rule conflicts (a genuine
  3-layer chain, an entirely-absent benefit type) with no bugs found; and shipped a batched P2
  sweep (case-insensitive verdict check, `SEARCH_K`-matching default, a deterministic
  citation-name cross-check). Stress-testing the hedge fix surfaced a real, unrelated
  `verify_answer` weakness — over-generalizing one benefit's specific carve-out into false
  suspicion of a sibling benefit the same excerpt explicitly doesn't carve out — written up as
  a new ticket rather than fixed inline. A full `edge_cases.py` refresh (32/36) diagnosed every
  failure individually: one stale test expectation (now commented, not "fixed" by weakening
  the anti-hallucination guardrail), one recurrence of an already-known, already-flagged
  `verify_answer` intermittency (logged against that ticket), one genuine eval-matcher gap
  (fixed), and one more data point for the new carve-out ticket.

## 10. A nondeterminism report, root-caused precisely instead of re-patched (§28)

- **§28 — "Probe this system carefully" instead of accepting a retry band-aid.** The user
  reported the flagship take-home query nondeterministically failing and pushed back hard on
  a first-pass retry proposal ("still leaves the possibility of returning an incorrect
  answer... probe this system carefully"). A live instrumentation probe (8 reps, logging
  every search call) ruled out retrieval variance — the decisive excerpt was cited every
  time — and the actual mechanism turned out to be visible directly in the user's own pasted
  rejection text: the verifier stated the fact that proves the claim, then declined to draw
  the one-step conclusion, because that excerpt's wording didn't match either of the two
  existing credited inference patterns. Fixed with a third pattern, "closed-list exclusion,"
  adversarially tested (6/6 correct-draft reps now `SUPPORTED`, 9/9 controls stayed correctly
  `UNSUPPORTED`) before shipping. Also flagged a real skill-selection mismatch along the way:
  the user's follow-up `/subagent-driven-development` invocation needs a written plan and
  independent tasks, and this was one cohesive fix with neither — routed back to direct TDD
  implementation instead of force-fitting the heavier process.

## 11. Final readability/cleanliness pass and wrap-up (§29)

- **§29 — A five-item final pass caught real doc drift a read-through would have missed.**
  Systematic (grep/AST-based, not just eyeballed) checks found the codebase itself already
  clean — one missing type hint was the only real finding. The docs were a different story:
  `DESIGN.md` still described `CLAUDE.md` as "the complete decision log" in four places, true
  before the `CLAUDE.md` compression two sessions ago but false since; every `src/agent.py`/
  `src/verification.py` line-number citation in `DESIGN.md` had drifted from two sessions of
  fixes growing those files. Also found the README's section order implied a stricter
  run-order dependency than actually exists (`pytest` and both `evals/` scripts build their
  own index in memory — only `main.py` needs `python ingest.py` first). All fixed; 80/80
  offline + `evals.eval` 8/8 live reconfirmed after every edit landed.

## 12. A ticket recurrence, then systematic-debugging confirms root cause but can't retrigger it (§30)

- **§30 — `edge_cases.py` re-run (31/36) surfaced a real ticket mix-up worth correcting live.**
  Diagnosing all 5 failures individually (not just reporting the count) found one that matched
  the *closed* precedence-false-rejection ticket's pattern, not the *open*
  carve-out-overgeneralization ticket flagged moments earlier — corrected this precisely when
  asked "is this still the verifier bug?" rather than letting an imprecise label stand. The
  resulting picture: three of the four `verify_answer` tickets now show live recurrence;
  only the one fix that's structural (an enum-constrained tool call) instead of a free-text
  prompt instruction has zero recurrences.
- **`superpowers:systematic-debugging` on the carve-out ticket:** 44 live reps across two
  methodologies (isolated `verify_answer()` probes with/without pattern (a)'s text, and full
  end-to-end reproduction with search-call instrumentation) could not re-trigger the ticket's
  original failure shape — instead surfacing two *different* phenomena (a citation-year
  attribution slip; a second recurrence of an already-logged draft-side confusion). Re-reading
  the original two captured rejections against this new evidence confirmed the root cause
  analytically anyway — both self-describe the over-broad pattern-(a) analogy in their own
  reasoning text. Reported this nuanced state (root cause understood, no fresh reproducible
  trigger to test a fix against) rather than overclaiming either a clean reproduction or a
  ready fix. **User decision: hold — no code change for this ticket**, document the findings
  instead. Updated the ticket, `CLAUDE.md`, and `DESIGN.md` accordingly.

## 13. Docs polish, an architecture Q&A, and a scoped-down grounding fix (§31–36)

- **§31 — A live timing breakdown, then three exploratory architecture questions.** One
  instrumented live query gave real per-step numbers, including the ~4.7s one-time library
  import cost. Three follow-up questions answered conversationally, no code changes: a
  long-lived process would eliminate that import gap (it's one-time, not per-question); a
  single-Claude-call version would save a round-trip but give up the independent-verification
  principle that's caught real fabrications before (recommended against); per-employee privacy
  isolation would be a genuinely architectural change, sketched but not built.
- **§32–33 — `DESIGN.md` condensed twice for an external reader.** First pass: every "Core
  components" subsection condensed to a strict Choice/Why/Tradeoff structure (480→398 lines),
  "Life of a query" kept byte-identical. Second pass: the title/intro/"System summary" split
  merged into one opening section, plus a new "Contents" table of contents. Republished as the
  same artifact both times; the user's own later manual wording edit to the intro was left as
  a deliberate style choice, not reverted.
- **§34 — Is the system overfit to `.docx`?** Read the actual ingestion/chunking code before
  answering: `ingest.py` hardcodes a `.docx`-specific reader with no format dispatch, but
  chunking/retrieval/agent/verification are already format-agnostic (they only see plain
  `Paragraph`/`Chunk` dataclasses). Recommended against building a speculative dispatch layer
  now (YAGNI). A precise follow-up question ("so only `ingest.py` changes?") got a precise
  correction: a new format-specific reader module is also needed, plus a check that CSV's
  row-shaped data actually fits the paragraph-heading chunking model before assuming so.
- **§35–36 — Brainstorming stronger grounding checks, then shipping the scoped-down first
  piece.** The user proposed three deterministic checks to add alongside the LLM-based
  `verify_answer` pass. Found the existing citation check was weaker than it looked (scanned
  the whole draft, not just the citation field) and flagged that literal-text matching for the
  third idea would conflict with `SYSTEM_PROMPT`'s required paraphrased-prose style — narrowed
  via one clarifying question to numeric + named-entity grounding, which would also harden the
  still-open, prompt-only fix from §20. **User scoped the first round to citation-tightening
  only.** Shipped via TDD (a red test proving the old check's false-negative, not assumed);
  live verification (`evals.eval`, 7/8) surfaced a genuine, unprompted fresh reproduction of
  the open carve-out-overgeneralization ticket (§30) — confirmed via `git diff` as unrelated to
  this change, logged as new evidence on that ticket rather than acted on, per that ticket's
  standing "hold" decision. Committed once git identity was configured.

## Process

Built with the superpowers plugin: brainstorming → design spec → implementation plan →
subagent-driven execution (fresh implementer + fresh reviewer per task, true red/green TDD,
YAGNI, DRY) → final whole-branch review → live acceptance run. Every non-trivial judgment
call during the original build was recorded in an SDD ledger at
`.superpowers/sdd/2026-08-19-rag-qa-system/progress.md` — a local, git-ignored workspace
deleted once the plan landed (per `superpowers:subagent-driven-development`'s own
convention); a fresh clone won't have it. The commits and `TRANSCRIPT.md` are the permanent
record.
