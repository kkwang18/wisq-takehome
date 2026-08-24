from __future__ import annotations

import os
import sys

from ingest import build_index
from src.agent import answer_question
from evals.matching import explain, matches

EXPECTED = [
    ("What is the PTO allowance for a Taiwanese employee?", "12"),
    ("What is the PTO allowance for a California employee?", "15"),
    ("What is the PTO allowance for a California employee in 2025?", "14"),
    ("What is the PTO allowance for a California employee in 2026?", "15"),
    ("What is the PTO allowance for a California employee in 2021?", "unknown"),
    ("What is the gym related benefits for a Taiwanese employee?", "$50"),
    ("What is the gym related benefits for a California employee?", "$50"),
    ("What is the gym related benefits for a employee living in Asia?", "hedge"),
]


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Export it before running: export ANTHROPIC_API_KEY=sk-...")

    index = build_index("documents.yaml")
    failures = []

    for question, expected in EXPECTED:
        result = answer_question(question, index)
        print(f"Q: {question}\n{result.text}\n{'-' * 80}")
        if not matches(expected, result):
            failures.append((question, expected, result))

    if failures:
        print(f"\n{len(failures)} of {len(EXPECTED)} queries did not match expectations:")
        for q, exp, result in failures:
            print(f"  Q: {q}\n  {explain(exp, result)}\n  got: {result.text}\n")
        sys.exit(1)

    print(f"\nAll {len(EXPECTED)} queries matched expectations.")


if __name__ == "__main__":
    main()
