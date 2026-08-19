from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.models import Chunk


@dataclass
class VerifiedAnswer:
    text: str
    grounded: bool


def build_verification_prompt(draft: str, cited_chunks: list[Chunk]) -> str:
    excerpts = "\n\n".join(f"[{c.doc.display_name} - {c.section_title}]\n{c.text}" for c in cited_chunks)
    return (
        "You are checking whether every factual claim in a draft answer is directly "
        "supported by the excerpts below. Respond with exactly 'SUPPORTED' if every claim "
        "is backed by the excerpts, or 'UNSUPPORTED: <reason>' if any claim is not directly "
        "backed by the excerpts.\n\n"
        f"Excerpts:\n{excerpts}\n\nDraft answer:\n{draft}"
    )


def verify_answer(draft: str, cited_chunks: list[Chunk], llm_call: Callable[[str], str]) -> VerifiedAnswer:
    prompt = build_verification_prompt(draft, cited_chunks)
    verdict = llm_call(prompt).strip()

    if verdict.startswith("SUPPORTED"):
        return VerifiedAnswer(text=draft, grounded=True)

    fallback = (
        "I can't confirm this from the retrieved policy text alone — "
        f"the verification check flagged: {verdict}"
    )
    return VerifiedAnswer(text=fallback, grounded=False)
