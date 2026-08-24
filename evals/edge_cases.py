from __future__ import annotations

import os
import sys

from ingest import build_index
from src.agent import answer_question
from evals.matching import explain, matches

# Entity resolution: one representative case per distinct lexical/semantic mechanism, not
# per jurisdiction — typo/casing/abbreviation exercise the same retrieval code path
# regardless of which jurisdiction they're pointed at, so testing multiple adds no signal.
ENTITY_RESOLUTION = [
    ("what is the pto for an employee based in taiwan", "12"),
    ("What is the PTO for an employee based in Tiawan?", "12"),
    ("What is the gym benefit for an employee in the PRC?", "50"),
    # This expectation is stale as of the entity-hallucination restriction added later
    # (docs/backlog/2026-08-20-draft-time-named-entity-hallucination.md): "Republic of China"
    # is Taiwan's official name, never written verbatim in the corpus (which only ever says
    # "People's Republic of China," a different country) — resolving it to "12" would require
    # outside geopolitical knowledge the system prompt now explicitly forbids for named
    # entities. A live run correctly hedges instead ("ambiguous... need to know which
    # jurisdiction you mean") rather than guessing. Don't "fix" this by loosening that
    # restriction; the hedge is the safer, now-intended behavior. Left as-is rather than
    # rewritten, so this note stays attached to the case it explains.
    ("What is the PTO for an employee based in the Republic of China?", "12"),
    ("What is the PTO for a Chinese national who works remotely from California?", "15"),
    ("What is the PTO for a contractor based in Taiwan?", "15"),
    ("What is the PTO for an employee who splits time between Japan and the United States?", "hedge"),
]

# Negative space: false premises and never-mentioned benefits.
NEGATIVE_SPACE = [
    # Compound: correcting the false "unlimited" premise (must state the true figure, 12)
    # and separately declining the sick-days sub-question (must not fabricate a number) are
    # two independent claims — a single "12" marker would pass even if sick days were
    # wrongly hallucinated as 12 too, since the PTO correction alone satisfies it.
    ("Since Taiwan employees get unlimited PTO, how many sick days do they get?", ["12", "unknown"]),
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
            if not matches(expected, result):
                failures.append((category, question, expected, result))

    if failures:
        print(f"\n{len(failures)} of {total} edge cases did not match expectations:")
        for cat, q, exp, result in failures:
            print(f"  [{cat}] Q: {q}\n  {explain(exp, result)}\n  got: {result.text}\n")
        sys.exit(1)

    print(f"\nAll {total} edge cases matched expectations.")


if __name__ == "__main__":
    main()
