from __future__ import annotations

from src.models import Chunk, DocMeta
from src.verification import VerifiedAnswer, verify_answer

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


def test_verify_answer_prompt_includes_draft_and_excerpts():
    captured = {}

    def fake_llm_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return "SUPPORTED"

    verify_answer("PTO is 15 days.", [CHUNK], llm_call=fake_llm_call)

    assert "PTO is 15 days." in captured["prompt"]
    assert "15 days per year" in captured["prompt"]
    assert "Test Handbook" in captured["prompt"]
