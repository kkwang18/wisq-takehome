from __future__ import annotations

from src.models import Chunk, DocMeta
from src.verification import VerifiedAnswer, build_verification_prompt, verify_answer

DOC = DocMeta(file="x.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Test Handbook")
CHUNK = Chunk(text="The standard global PTO entitlement is 15 days per year.", section_title="4.2 PTO", doc=DOC)

# Matches the real format_answer() shape: verdict, reason, citation naming the actual
# retrieved document — realistic input now that agent.py always constructs drafts this way.
SUPPORTED_DRAFT = "15 days per year.\n\nStandard global entitlement.\n\n— (Test Handbook, 4.2 PTO)"
UNSUPPORTED_DRAFT = "20 days per year.\n\nStandard global entitlement.\n\n— (Test Handbook, 4.2 PTO)"


def test_verify_answer_passes_through_supported_draft():
    result = verify_answer(SUPPORTED_DRAFT, [CHUNK], llm_call=lambda prompt: "SUPPORTED")
    assert result == VerifiedAnswer(text=SUPPORTED_DRAFT, grounded=True)


def test_verify_answer_accepts_a_lowercase_or_mixed_case_supported_verdict():
    # Defensive check: verify_llm_call's enum-constrained tool guarantees exact case today
    # (see docs/backlog/2026-08-22-verify-answer-prefix-parsing-false-rejection.md), but
    # verify_answer() is a general-purpose function any llm_call implementation can drive —
    # it shouldn't silently reject a correct verdict just because of casing.
    result = verify_answer(SUPPORTED_DRAFT, [CHUNK], llm_call=lambda prompt: "supported")
    assert result.grounded is True
    result = verify_answer(SUPPORTED_DRAFT, [CHUNK], llm_call=lambda prompt: "Supported")
    assert result.grounded is True


def test_verify_answer_downgrades_unsupported_draft():
    result = verify_answer(
        UNSUPPORTED_DRAFT,
        [CHUNK],
        llm_call=lambda prompt: "UNSUPPORTED: 20 days is not stated in the excerpts",
    )
    assert result.grounded is False
    assert "20 days is not stated" in result.text
    assert result.rejected_draft == UNSUPPORTED_DRAFT


def test_verify_answer_still_rejects_uppercase_unsupported_as_unsupported():
    # UNSUPPORTED must never be mistaken for SUPPORTED under case-insensitive matching —
    # "UNSUPPORTED".upper() starts with "UN", not "SUPPORTED", so this is safe by construction,
    # but it's the sharpest test of the case-insensitivity fix above.
    result = verify_answer(UNSUPPORTED_DRAFT, [CHUNK], llm_call=lambda prompt: "unsupported: nope")
    assert result.grounded is False


def test_verify_answer_hard_fails_when_nothing_retrieved():
    calls = []
    result = verify_answer("some draft", [], llm_call=lambda p: calls.append(p) or "SUPPORTED")
    assert result.grounded is False
    assert "No policy excerpts were retrieved" in result.text
    assert result.rejected_draft is None
    assert calls == []  # nice-to-have: llm_call should not be invoked at all


def test_verify_answer_hard_fails_when_citation_names_no_retrieved_document():
    # Deterministic check, independent of the LLM verification pass: a citation tag that
    # doesn't name any actually-retrieved document/section is a fabricated citation, and no
    # LLM call is needed to know that — same "fail closed without a model call" posture as
    # the empty-cited-chunks case above.
    calls = []
    draft = "15 days per year.\n\nStandard global entitlement.\n\n— (Fake Handbook, Section 1)"
    result = verify_answer(draft, [CHUNK], llm_call=lambda p: calls.append(p) or "SUPPORTED")
    assert result.grounded is False
    assert "citation" in result.text.lower()
    assert result.rejected_draft == draft
    assert calls == []


def test_verify_answer_accepts_citation_naming_one_of_several_retrieved_documents():
    # A compound-question answer may cite only some of the documents actually searched — the
    # check only requires at least one match, not all of cited_chunks to be named.
    other_doc = DocMeta(file="y.docx", doc_type="regional_handbook", jurisdictions=["Taiwan"], version_year=None, display_name="Other Handbook")
    other_chunk = Chunk(text="Some other provision.", section_title="Other Section", doc=other_doc)
    draft = "15 days per year.\n\nStandard global entitlement.\n\n— (Test Handbook, 4.2 PTO)"
    result = verify_answer(draft, [CHUNK, other_chunk], llm_call=lambda prompt: "SUPPORTED")
    assert result.grounded is True


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


def test_verification_prompt_credits_closed_list_exclusion_inference():
    # Live bug: the verifier's own rejection text stated "the only regional handbook covers
    # China, Japan, and Taiwan" and then refused to credit that this excludes California —
    # a real gap distinct from (a)/(b) above, since the APAC SCOPE excerpt's wording (an
    # enumerated list + "everyone else, refer to global") doesn't pattern-match either
    # existing trigger phrase. See docs/backlog/2026-08-20-verify-answer-absence-inference-
    # false-rejection.md's "Recurrence observed" addendum.
    prompt = build_verification_prompt("draft", [CHUNK])
    lowered = prompt.lower()
    assert "closed" in lowered and "enumerat" in lowered
    assert "refer" in lowered


def test_verify_answer_prompt_includes_draft_and_excerpts():
    captured = {}

    def fake_llm_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "SUPPORTED"

    verify_answer(SUPPORTED_DRAFT, [CHUNK], llm_call=fake_llm_call)

    assert SUPPORTED_DRAFT in captured["prompt"]
    assert "15 days per year" in captured["prompt"]
    assert "Test Handbook" in captured["prompt"]
