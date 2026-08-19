from __future__ import annotations

import os
import sys

from ingest import build_index
from src.agent import answer_question

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


def _matches(expected: str, result_text: str, grounded: bool) -> bool:
    lowered = result_text.lower()
    if expected == "unknown":
        unknown_markers = [
            "unknown",
            "don't have enough information",
            "do not have enough information",
            "cannot determine",
            "can't determine",
            "no reliable basis",
            "not enough information",
            "insufficient information",
            "unable to confirm",
            "can't confirm",
            "cannot confirm",
            "don't know",
            "do not know",
            "cannot answer this question with confidence",
            "can't answer this question with confidence",
            "no factual basis",
            "don't have a factual basis",
            "do not have a factual basis",
            "would require guessing",
            "avoid guessing",
            "should avoid guessing",
            "should avoid stating",
        ]
        return any(marker in lowered for marker in unknown_markers) or not grounded
    if expected == "hedge":
        return any(word in lowered for word in ["ambig", "clarif", "which country", "unclear", "depends on"])
    return expected in result_text


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Export it before running: export ANTHROPIC_API_KEY=sk-...")

    index = build_index("documents.yaml")
    failures = []

    for question, expected in EXPECTED:
        result = answer_question(question, index)
        print(f"Q: {question}\n{result.text}\n{'-' * 80}")
        if not _matches(expected, result.text, result.grounded):
            failures.append((question, expected, result.text))

    if failures:
        print(f"\n{len(failures)} of {len(EXPECTED)} queries did not match expectations:")
        for q, exp, got in failures:
            print(f"  Q: {q}\n  expected marker: {exp!r}\n  got: {got}\n")
        sys.exit(1)

    print(f"\nAll {len(EXPECTED)} queries matched expectations.")


if __name__ == "__main__":
    main()
