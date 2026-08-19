from __future__ import annotations

import argparse
import os
import sys

from src.agent import answer_question
from src.retrieval import VectorIndex

EXAMPLE_QUERIES = [
    "What is the PTO allowance for a Taiwanese employee?",
    "What is the PTO allowance for a California employee?",
    "What is the PTO allowance for a California employee in 2025?",
    "What is the PTO allowance for a California employee in 2026?",
    "What is the PTO allowance for a California employee in 2021?",
    "What is the gym related benefits for a Taiwanese employee?",
    "What is the gym related benefits for a California employee?",
    "What is the gym related benefits for a employee living in Asia?",
]


def select_questions(ask: str | None) -> list[str]:
    return [ask] if ask else EXAMPLE_QUERIES


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the Acme benefits Q&A system a question")
    parser.add_argument("--ask", default=None, help="Ask a single ad hoc question instead of running the example set")
    parser.add_argument("--index", default="index", help="Path to the prebuilt index directory")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Export it before running: export ANTHROPIC_API_KEY=sk-...")

    index = VectorIndex.load(args.index)

    for question in select_questions(args.ask):
        print(f"Q: {question}\n")
        result = answer_question(question, index)
        print(result.text)
        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
