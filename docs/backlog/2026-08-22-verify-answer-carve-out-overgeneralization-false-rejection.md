# BACKLOG: `verify_answer` over-generalizes a sibling benefit's specific carve-out into false suspicion

**Status:** Open, not fixed — deliberately held. Root cause now confirmed *analytically*
(2026-08-23 investigation, see "Root cause investigation" near the bottom): the original two
captured rejections are a genuine instance of over-broad application of pattern (a), not a
distinct mechanism. But 44 live reps across two reproduction methodologies did not re-trigger
that specific pattern, so no clean before/after baseline exists to adversarially test a fix
against — the same rigor the two related tickets' fixes were held to before shipping. User
decision: hold off on any `build_verification_prompt`/`verify_answer` code change for this
ticket until reproduction is easier, rather than ship a fix untested against a real baseline.
Severity and false-rejection framing below are unchanged from the original triage.

**Discovered:** 2026-08-22, during live stress-testing of the Asia-gym hedge fix (see
`docs/TRANSCRIPT.md`'s entry for this session's 5-item closure batch). 2 of 6 reps of "What is
the gym related benefits for a employee living in Asia?" hit this; a same-day `evals.eval` run
of the same query passed clean. Sample too small to trust as an occurrence rate — see "Test
plan" below.

**Severity:** Medium, same profile as the two related tickets — degrades reliability, doesn't
cause fabrication. Arguably lower-risk than either of those: the failure direction here is a
false *rejection* of a correct draft (the system under-answers), not a false acceptance of a
wrong one.

**Related tickets:** `docs/backlog/2026-08-20-verify-answer-precedence-false-rejection.md` and
`docs/backlog/2026-08-20-verify-answer-absence-inference-false-rejection.md` (both closed
2026-08-21) taught the verifier to credit two inference patterns via a shared addition to
`build_verification_prompt`: (a) a specific rule carving itself out of a general fallback, and
(b) a general default rule with no specific override. **This ticket's failure looks like an
over-application of pattern (a)'s own guidance** to a case that pattern (a) doesn't actually
cover — see "Root cause hypothesis" below. The two related tickets' adversarial batteries
(3 cases each, run 3x live) didn't include this specific shape, which is likely why it wasn't
caught before shipping that fix.

## Summary

The real corpus's APAC `CONFLICTS AND PRECEDENCE` section gives PTO a specific regional
carve-out ("Where a conflict arises specifically with respect to PTO... the LOCAL PTO POLICY
... TAKES PRECEDENCE"), then explicitly routes every other benefit type back to the global
handbook's own rules ("For all other benefits, refer to the precedence rules in the global
Acme Employee Handbook"). Gym membership is one of those "other benefits" — it has its own
APAC-specific *rate* ($30/month, in `REGIONAL BENEFITS`), but the same document's own
precedence section says that rate does not get PTO-style local precedence; it's supposed to
compete under the global handbook's ordinary "more generous wins" rule (global $50/month wins).
A correct draft says exactly this. `verify_answer` sometimes rejects it anyway, reasoning that
the mere existence of an APAC-specific gym *rate* implies gym might also be a specific
carve-out like PTO — directly contradicting the same excerpt's explicit "for all other
benefits, refer to global" routing.

## Concrete examples

Both captured live from `python main.py --ask "What is the gym related benefits for a
employee living in Asia?"` on 2026-08-22, same session, same unmodified code:

**Rep 1:**

> "UNSUPPORTED: The draft claims that 'the precedence rule says the more generous one wins'
> applies to determine which gym rate applies, implying the $50 global rate could override the
> $30 regional rate via the general Section 8 'more generous' rule. But the APAC Handbook's
> Conflicts and Precedence section only invokes the general global precedence rule 'for all
> other benefits' — it does not say this applies to gym/wellness benefits, and in fact PTO is
> called out with an explicit local-precedence carve-out, suggesting other regional benefits
> (like gym membership) are similarly specific regional entitlements rather than subject to the
> 'more generous' comparison. The excerpts do not state that the $30 regional gym benefit is
> compared against the $50 global one under the 'more generous' rule; this is an unsupported
> inference not directly stated in the excerpts."

**Rep 2:**

> "UNSUPPORTED: The draft claims that when comparing the regional and global gym benefits, a
> 'more generous benefit applies' fallback rule applies. But per the APAC Benefits Handbook -
> CONFLICTS AND PRECEDENCE excerpt, the regional handbook sets a specific rule for gym
> membership in China/Japan/Taiwan ($30/month), and states 'for all other benefits, refer to
> the precedence rules in the global handbook' — implying the specific regional gym rule (not
> the global 'more generous' rule) governs for those three countries. The draft incorrectly
> says the 'more generous' comparison would apply there, which contradicts the specific
> carve-out established by the excerpts."

Both rejections are wrong. "For all other benefits, refer to the precedence rules in the
global Acme Employee Handbook" is not ambiguous about which rule governs gym — it explicitly
says the global rules govern, which is exactly the "more generous wins" comparison. The
existence of an APAC-specific *number* for gym doesn't make gym a *carve-out* the way PTO
explicitly is; the same sentence that gives the number also routes it back to the global rule.
This exact query, with this exact reasoning, has been run dozens of times earlier in this
project's history (every PTO/gym live-verification pass throughout `docs/TRANSCRIPT.md`) and
was correctly grounded every other time observed.

## Root cause hypothesis

The two related tickets' shared fix added this guidance to `build_verification_prompt`:

> "(a) Specific carve-out: when an excerpt states a specific rule for a specific case, and
> separately states that a different, general rule applies 'for all other' cases, the specific
> rule is the complete and final answer for its named case — it does not need to be reconciled
> against the general rule."

This guidance is about crediting a *correct* carve-out inference, not about identifying
*which* cases count as a carve-out. It's plausible the verifier sometimes over-generalizes
"this document contains a specific carve-out" (true, for PTO) into "so any other
region-specific-sounding figure in this document might also be a carve-out" (false — the same
document explicitly says otherwise for every non-PTO benefit). Both related tickets' adversarial
batteries tested two-layer scenarios (a rule either does or doesn't have a carve-out); neither
tested this three-way shape — one item *with* an explicit carve-out, a sibling item *with its
own region-specific number* but *explicitly and separately routed to the general rule in the
same breath*. That gap in adversarial coverage is the likely reason this wasn't caught before
the related tickets' fix shipped.

## Root cause investigation (2026-08-23) — confirmed analytically, not fresh-reproduced

Followed `superpowers:systematic-debugging`. Phase 1 (root cause before any fix) had two
parts: re-examine the original evidence against pattern (a)'s exact wording, and attempt a
fresh live reproduction with instrumentation.

**Analytical confirmation.** Both original captured rejections (see "Concrete examples" above)
explicitly self-describe the over-generalization in their own reasoning text — Rep 1: *"PTO is
called out with an explicit local-precedence carve-out, suggesting other regional benefits
(like gym membership) are similarly specific regional entitlements rather than subject to the
'more generous' comparison."* That is analogical reasoning from pattern (a)'s carve-out framing
onto a case pattern (a) doesn't cover, stated directly by the verifier itself. The hypothesis
above holds up under this re-reading — this is a genuine over-broad application of pattern (a),
not evidence of some other, unrelated mechanism.

**Reproduction attempts did not re-trigger this specific pattern.** Two methodologies, 44 live
reps total:

1. Isolated `verify_answer()` probes against the real cited excerpts (`SCOPE`,
   `CONFLICTS AND PRECEDENCE` ×2, `REGIONAL BENEFITS` ×2, global `SECTION 3`, global
   `SECTION 8`), with a reconstructed draft matching the shape the original rejections
   describe (explicit $50-vs-$30 comparison language within an Asia-hedge). Ran this against
   both the current prompt (patterns a/b/c intact) and a version with the entire
   credited-patterns block surgically removed, 8 reps each. **32/32 SUPPORTED — zero
   reproduction either way.** This means the bug isn't reliably triggered by pattern (a)'s
   mere textual presence alone, holding the draft and excerpt set fixed — something about the
   original failures' specific (uncaptured) draft wording or exact cited-chunk set likely
   matters too, and a hand-reconstructed approximation isn't close enough to trigger it
   on demand.
2. Full end-to-end `answer_question()` reproduction with live instrumentation (logging every
   `search_handbooks` call), 12 fresh reps of the actual query. **10/12 SUPPORTED, 2
   rejected** — but neither rejection matches the ticket's original failure shape:
   - One rejection was dominated by a genuine citation-year slip: the draft attributed a
     precedence clause to "Acme Employee Handbook 2026, Section 8," but the actually-cited
     chunk was **2025**'s Section 8 (the two years have textually identical Section 8
     wording, which likely caused the conflation). The verifier caught a real attribution
     error here — arguably correct behavior, not a bug, even though the underlying rule
     content was accurate regardless of which year it was attributed to.
   - The other rejection was a **correct** rejection of a **genuinely wrong** draft — the
     draft itself asserted the APAC $30 gym rate "takes precedence" for China/Japan/Taiwan,
     which is false. This is the *draft-generation-side* mischaracterization already logged
     below under "Corroborating evidence," recurring a second time, not the verifier-side bug
     this ticket is about.

**What this means.** The "gym precedence" area of this corpus is broadly failure-prone across
*multiple distinct mechanisms* (citation year attribution, draft-side carve-out
mischaracterization, and the verifier-side over-generalization this ticket is actually about) —
but the specific mechanism this ticket describes appears rarer than the original 2/6 sample
suggested, or requires a more specific trigger than these reproduction attempts hit. Root cause
is understood with high confidence from the original evidence itself; a fresh, reliable trigger
for adversarially testing a fix's before/after impact is not in hand. **Decision (user,
2026-08-23): hold off on any code change for this ticket rather than ship a fix without a real
baseline to test it against** — do not touch `build_verification_prompt` or any other
`verify_answer` code for this ticket until reproduction is easier. Severity stays Medium,
false-rejection direction, per the original triage above — this investigation didn't change
that assessment, only the confidence in the root cause and the difficulty of re-triggering it.

## Suggested fix (sketch, still not implemented — deliberately held, see investigation above)

Extend `build_verification_prompt` with a boundary clause for pattern (a): a specific carve-out
established for one named case does not extend to a *different* case just because that
different case also has its own region-specific figure — if the excerpts explicitly route the
different case back to the general rule ("for all other benefits, refer to..."), that explicit
routing governs, and the general rule's own comparison (e.g. "more generous wins") is the
complete and final answer for it, not a suspect inference needing extra scrutiny.

As with both related tickets: do not ship without adversarial testing that this doesn't make
the verifier *more* lenient toward a genuinely wrong "explicit carve-out doesn't apply here"
claim — a draft that wrongly claims a real carve-out (PTO) is *not* a carve-out is the sharpest
inverted-direction control to test alongside this fix. This control is now known to be
testable even without reproducing the original bug — see item 1 below.

## Test plan

1. ~~Reproduce directly via `verify_answer()` probes against the real cited excerpts~~ —
   **attempted 2026-08-23, not cleanly achieved.** 44 live reps (32 isolated `verify_answer()`
   probes with/without pattern (a)'s text present, 12 full end-to-end reproductions) found the
   original mechanism analytically confirmed but not reliably re-triggerable on demand — see
   "Root cause investigation" above for the full account, including two *different* failure
   modes surfaced instead (a citation-year attribution slip; a recurrence of the
   draft-generation-side mischaracterization already logged below). Before implementing,
   whoever picks this up should either find a more reliable trigger (a closer match to the
   original uncaptured draft wording, or a narrower/different excerpt set) or accept
   implementing against the analytical diagnosis alone, without a live before/after baseline.
2. Get a real occurrence-rate baseline before implementing — still not done, and now known to
   be harder than a fixed rep count away: the 2026-08-23 investigation's 44 reps didn't
   converge on a stable rate for *this specific* pattern (it caught 0/44 clean instances of it,
   despite 2/44 rejections overall from unrelated causes). (Optional per whoever picks this up,
   budget permitting — the user has judged this kind of stress-testing not always worth the API
   spend, twice now.)
3. Adversarial testing before shipping: the correct draft (4+ reps, must stay SUPPORTED), the
   inverted-direction control described above, and at least one fabricated-number control —
   same discipline as the two related tickets. Note: the correct-draft leg of this can be run
   today using either draft variant from the 2026-08-23 investigation (both already tested
   32/32 SUPPORTED pre-fix, so re-running post-fix would show whether the fix preserves the
   already-good baseline — it would not, by itself, prove the fix helps the failure case, since
   that case wasn't reproduced).
4. Regression: full offline suite and `python -m evals.eval` (8/8) after any fix.

## Files involved

- `src/verification.py` — `build_verification_prompt()`, likely fix location, same as both
  related tickets.

## Context for whoever picks this up

Found while stress-testing an unrelated fix (the Asia-gym hedge no longer revealing
per-branch dollar figures — see `docs/DESIGN.md`'s design principles and this session's
`docs/TRANSCRIPT.md` entry). Not caused by that fix or by anything else changed this session;
`src/verification.py` was touched this session only for the case-insensitivity and
citation-name-cross-check fixes (see `docs/DESIGN.md`'s known limitations), neither of which
touches `build_verification_prompt`'s reasoning content.

## Corroborating evidence: the same confusion also appears on the draft-generation side

A same-session `python -m evals.edge_cases` run hit a related-but-distinct failure on
"What is the annual conference and training budget for an employee based in China?" — here
the *draft itself* (not the verifier) mischaracterized gym as a PTO-style carve-out:

> "UNSUPPORTED: The draft claims 'The APAC regional handbook only overrides the global policy
> for PTO and wellness/gym benefits.' However, the excerpts only state that PTO explicitly
> takes precedence over the global handbook; wellness/gym is simply a separate regional
> benefit listed, not stated to 'override' the global policy in the same conflict-precedence
> sense... this specific characterization is an unsupported inference beyond what the
> Conflicts and Precedence section says."

`verify_answer` correctly caught this one — the draft was actually wrong to call gym a
carve-out, and the rejection is the safety net working as intended, not a false rejection.
But it's worth recording alongside this ticket: gym's precedence status (has its own regional
*rate*, but explicitly does *not* get PTO-style regional *precedence*) appears to be a
genuinely confusable point for this model on both sides of the loop — sometimes the
draft-generation step gets it wrong (this case), sometimes the verification step wrongly
distrusts a draft that got it right (this ticket's main examples). If a fix to
`build_verification_prompt` is implemented per the "Suggested fix" above, consider whether the
same clarified language would also help as SYSTEM_PROMPT draft-time guidance, since the
underlying confusion (does "for all other benefits, refer to global" also count as its own
kind of precedence override, or not) seems to affect both steps, not just verification.

**Second recurrence (2026-08-23):** the 2026-08-23 root-cause investigation's end-to-end
reproduction attempt (see "Root cause investigation" above) hit this exact same
draft-generation-side shape again, unprompted, in fresh live reps: a draft asserted the APAC
$30 gym rate "takes precedence" for China/Japan/Taiwan, and `verify_answer` correctly rejected
it. Two independent live occurrences of the same draft-side confusion, on two different
days, both correctly caught — this strengthens the case (not yet acted on) that
`SYSTEM_PROMPT` draft-time guidance may be worth the same clarification eventually, independent
of whether/when the verifier-side fix above ever ships.
