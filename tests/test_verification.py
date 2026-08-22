from __future__ import annotations

from src.models import Chunk, DocMeta
from src.verification import VerifiedAnswer, build_verification_prompt, verify_answer

DOC = DocMeta(file="x.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Test Handbook")
CHUNK = Chunk(text="The standard global PTO entitlement is 15 days per year.", section_title="4.2 PTO", doc=DOC)


def test_verify_answer_passes_through_supported_draft():
    result = verify_answer("PTO is 15 days.", [CHUNK], llm_call=lambda prompt: "SUPPORTED")
    assert result == VerifiedAnswer(text="PTO is 15 days.", grounded=True)


def test_verify_answer_downgrades_unsupported_draft():
    result = verify_answer(
        "PTO is 20 days.",
        [CHUNK],
        llm_call=lambda prompt: "UNSUPPORTED: 20 days is not stated in the excerpts",
    )
    assert result.grounded is False
    assert "20 days is not stated" in result.text
    assert result.rejected_draft == "PTO is 20 days."


def test_verify_answer_hard_fails_when_nothing_retrieved():
    calls = []
    result = verify_answer("some draft", [], llm_call=lambda p: calls.append(p) or "SUPPORTED")
    assert result.grounded is False
    assert "No policy excerpts were retrieved" in result.text
    assert result.rejected_draft is None
    assert calls == []  # nice-to-have: llm_call should not be invoked at all


def test_verification_prompt_credits_specific_carve_out_and_general_default_inferences():
    # Guards the two verify_answer false-rejection fixes (docs/backlog/2026-08-20-verify-
    # answer-{precedence,absence-inference}-false-rejection.md): a specific rule that carves
    # itself out of a general fallback, and a general default rule with no specific override,
    # must both be explicitly credited as valid supported inferences, not treated as an
    # unresolved conflict just because a different, more general rule is also present.
    prompt = build_verification_prompt("draft", [CHUNK])
    lowered = prompt.lower()
    assert "specific carve-out" in lowered
    assert "general default" in lowered
    assert "unless a specific provision states otherwise" in lowered


def test_verify_answer_prompt_includes_draft_and_excerpts():
    captured = {}

    def fake_llm_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "SUPPORTED"

    verify_answer("PTO is 15 days.", [CHUNK], llm_call=fake_llm_call)

    assert "PTO is 15 days." in captured["prompt"]
    assert "15 days per year" in captured["prompt"]
    assert "Test Handbook" in captured["prompt"]
