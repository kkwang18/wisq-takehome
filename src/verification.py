from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.models import Chunk


@dataclass
class VerifiedAnswer:
    text: str
    grounded: bool
    rejected_draft: str | None = None


def build_verification_prompt(draft: str, cited_chunks: list[Chunk]) -> str:
    excerpts = "\n\n".join(f"[{c.doc.display_name} - {c.section_title}]\n{c.text}" for c in cited_chunks)
    return (
        "You are checking whether every factual claim in a draft answer is directly "
        "supported by the excerpts below. Respond with exactly 'SUPPORTED' if every claim "
        "is backed by the excerpts, or 'UNSUPPORTED: <reason>' if any claim is not directly "
        "backed by the excerpts. Note: if the draft states that the answer is unknown, or "
        "that the question is ambiguous and needs clarification, and this is because the "
        "excerpts genuinely do not resolve the question, treat that as SUPPORTED — "
        "accurately reporting an absence or ambiguity in the source material is not the "
        "same as making an unsupported factual claim.\n\n"
        "Also note two specific reasoning patterns that are valid, supported inferences from "
        "the excerpts, not unsupported claims — do not flag either as UNSUPPORTED merely "
        "because the excerpts also contain a different, more general rule that would produce "
        "a different answer if scope were ignored:\n"
        "(a) Specific carve-out: when an excerpt states a specific rule for a specific case, "
        "and separately states that a different, general rule applies 'for all other' cases, "
        "the specific rule is the complete and final answer for its named case — it does not "
        "need to be reconciled against the general rule.\n"
        "(b) General default: when an excerpt states a general rule applies to all cases "
        "unless a specific provision states otherwise (or equivalent wording), and no other "
        "excerpt provides a specific provision covering the case in question, the general "
        "rule is the complete and final answer for that case — the absence of a specific "
        "override does not itself need to be separately stated in the excerpts to be a valid "
        "basis for the conclusion.\n"
        "(c) Closed-list exclusion: when an excerpt enumerates a closed, finite list of cases "
        "it covers (e.g. specific named jurisdictions) and separately instructs anyone or "
        "anything not on that list to refer elsewhere (e.g. a different handbook), a case "
        "that is not named in the list is definitively excluded — the excerpt does not need "
        "to separately name that specific case to establish the exclusion. Being outside an "
        "explicitly closed list, combined with an explicit 'everyone else, refer to X' "
        "instruction, is itself the complete and final confirmation of non-coverage, not "
        "merely an absence of information. Do not flag a draft as UNSUPPORTED for stating "
        "this exclusion just because the excerpt never mentions the specific case by name.\n"
        "All three exemptions apply only when the excerpts' own wording makes the case's "
        "scope unambiguous — if the excerpts leave genuine doubt about which rule actually "
        "covers the case in the draft (not just the existence of a different rule elsewhere), "
        "or if it's unclear whether a list is meant to be closed/exhaustive rather than "
        "illustrative, that is a real ambiguity and should still be flagged as "
        "UNSUPPORTED.\n\n"
        f"Excerpts:\n{excerpts}\n\nDraft answer:\n{draft}"
    )


def verify_answer(draft: str, cited_chunks: list[Chunk], llm_call: Callable[[str], str]) -> VerifiedAnswer:
    if not cited_chunks:
        return VerifiedAnswer(
            text="No policy excerpts were retrieved, so this answer cannot be grounded in the handbooks.",
            grounded=False,
        )

    if not any(c.doc.display_name in draft for c in cited_chunks):
        return VerifiedAnswer(
            text="The answer's citation doesn't name any of the retrieved excerpts, so this "
            "cannot be confirmed as grounded.",
            grounded=False,
            rejected_draft=draft,
        )

    prompt = build_verification_prompt(draft, cited_chunks)
    verdict = llm_call(prompt).strip()

    # Case-insensitive: verify_llm_call's enum-constrained tool guarantees exact case today
    # (see docs/backlog/2026-08-22-verify-answer-prefix-parsing-false-rejection.md), but this
    # is a general-purpose function any llm_call implementation can drive. "UNSUPPORTED" does
    # not start with "SUPPORTED" even uppercased (it starts with "UN"), so this stays safe.
    if verdict.upper().startswith("SUPPORTED"):
        return VerifiedAnswer(text=draft, grounded=True)

    fallback = (
        "I can't confirm this from the retrieved policy text alone — "
        f"the verification check flagged: {verdict}"
    )
    return VerifiedAnswer(text=fallback, grounded=False, rejected_draft=draft)
