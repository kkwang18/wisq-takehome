from __future__ import annotations

from types import SimpleNamespace

from src.agent import (
    MAX_TOOL_ITERATIONS,
    SEARCH_TOOL,
    SUBMIT_ANSWER_TOOL,
    SYSTEM_PROMPT,
    VERIFY_TOOL,
    answer_question,
    format_answer,
    verify_llm_call,
)
from src.models import Chunk, DocMeta, ScoredChunk


def test_system_prompt_encodes_grounding_and_precedence_rules():
    lowered = SYSTEM_PROMPT.lower()
    assert "search_handbooks" in lowered
    assert "ambiguous" in lowered or "ambiguity" in lowered
    assert "unknown" in lowered
    assert "cite" in lowered
    assert "more generous" in lowered


def test_system_prompt_forbids_structural_formatting_and_normalizes_compound_questions():
    # Live runs showed the same compound question ("sick days? 401k? insurance?") answered
    # with visibly different shapes across runs — one used a bulleted/bold-labeled list with
    # intro/outro framing, the other flowing prose. main.py just print()s the raw text (no
    # markdown renderer), so markdown formatting is also pure noise, not just inconsistent.
    lowered = SYSTEM_PROMPT.lower()
    assert "no bullet" in lowered
    assert "no headers" in lowered
    assert "markdown" in lowered
    assert "distinct topic" in lowered
    assert "same shape" in lowered


def test_system_prompt_forbids_revealing_branch_outcomes_even_when_they_converge():
    # Flagged, not fixed, from the §12 live run: the Asia-gym hedge explained what the figure
    # would be under each branch ("if you're in one of those three countries... $50 would
    # win; if elsewhere... only the global $50 applies") — undercutting the hedge even though
    # the existing instruction already said not to reveal per-branch outcomes, because a model
    # reading that instruction could plausibly reason "but both branches give the same number,
    # so it's not really revealing anything." The added example closes that reading explicitly.
    lowered = SYSTEM_PROMPT.lower()
    assert "converge" in lowered
    assert "even when" in lowered
    # Round 2: a live rep still leaked "$50 either way" reasoning after round 1's fix — this
    # closes the specific pattern of naming each side's own number as supporting detail for
    # the rule, not just naming the final converged answer.
    assert "supporting detail" in lowered


def test_system_prompt_requires_submit_answer_tool_for_final_answer():
    # A live report showed the citation sometimes jammed directly onto the reason sentence
    # ("...applies. — (Doc, Section)") and sometimes separated by a blank line — free text
    # gives the model no hard boundary between parts. The fix moves formatting out of the
    # model's hands entirely: the model supplies content via submit_answer's three fields,
    # and format_answer() assembles the guaranteed layout in code.
    lowered = SYSTEM_PROMPT.lower()
    assert "submit_answer" in lowered
    assert "never write it as plain chat text" in lowered or "never write the answer as plain text" in lowered


def test_search_tool_schema_exposes_metadata_filters():
    props = SEARCH_TOOL["input_schema"]["properties"]
    assert "query" in props
    assert "doc_type" in props
    assert "version_year" in props
    assert SEARCH_TOOL["input_schema"]["required"] == ["query"]


def test_submit_answer_tool_schema_exposes_three_fields():
    props = SUBMIT_ANSWER_TOOL["input_schema"]["properties"]
    assert set(props) == {"verdict", "reason", "citation"}
    assert set(SUBMIT_ANSWER_TOOL["input_schema"]["required"]) == {"verdict", "reason", "citation"}


def test_format_answer_separates_verdict_reason_citation_with_blank_lines():
    # This is the deterministic guarantee: no matter what the model puts in each field, the
    # assembled text always has verdict, reason, and citation as three distinct paragraphs —
    # never merged onto one line, unlike the free-text era this replaces.
    text = format_answer("15 days per year.", "The global default applies.", "Test Handbook, 4.2 PTO")
    assert text == "15 days per year.\n\nThe global default applies.\n\n— (Test Handbook, 4.2 PTO)"


def test_format_answer_strips_surrounding_whitespace_from_each_field():
    text = format_answer("  15 days per year.  ", "\nThe global default applies.\n", " Test Handbook, 4.2 PTO ")
    assert text == "15 days per year.\n\nThe global default applies.\n\n— (Test Handbook, 4.2 PTO)"


def test_verify_tool_schema_constrains_verdict_to_supported_or_unsupported():
    # docs/backlog/2026-08-22-verify-answer-prefix-parsing-false-rejection.md: verify_answer's
    # .startswith("SUPPORTED") check misfired once because the verifier's raw free text
    # reasoned aloud and only reached "SUPPORTED" at the end instead of leading with it. An
    # enum-constrained field makes the classification itself a schema guarantee, not
    # something extracted by parsing prose.
    props = VERIFY_TOOL["input_schema"]["properties"]
    assert props["verdict"]["enum"] == ["SUPPORTED", "UNSUPPORTED"]
    assert set(VERIFY_TOOL["input_schema"]["required"]) == {"verdict", "reason"}


class _ScriptedMessages:
    """Fake anthropic.Anthropic().messages: replays a fixed list of canned responses,
    repeating the last one for any call beyond the list's length."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        i = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[i]


class _ScriptedClient:
    def __init__(self, responses):
        self.messages = _ScriptedMessages(responses)


class _StubIndex:
    """Fake VectorIndex: preload_model() is a no-op, search() always returns the same
    single non-empty result, so answer_question's cited_chunks/verify_answer path is
    exercised without needing real embeddings."""

    def __init__(self):
        doc = DocMeta(file="x.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Test Handbook")
        chunk = Chunk(text="The standard global PTO entitlement is 15 days per year.", section_title="4.2 PTO", doc=doc)
        self._result = [ScoredChunk(chunk=chunk, score=0.9)]

    def preload_model(self):
        pass

    def search(self, query, k, doc_type=None, version_year=None):
        return self._result


def _search_response(call_id: str):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=call_id, name="search_handbooks", input={"query": "pto"})],
    )


def _submit_answer_response(call_id: str, verdict: str, reason: str, citation: str):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use",
                id=call_id,
                name="submit_answer",
                input={"verdict": verdict, "reason": reason, "citation": citation},
            )
        ],
    )


def _text_response(text: str):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def _verify_response(verdict: str, reason: str = ""):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use",
                id="verify_call",
                name="report_verification",
                input={"verdict": verdict, "reason": reason},
            )
        ],
    )


def test_verify_llm_call_returns_supported_verdict():
    client = _ScriptedClient([_verify_response("SUPPORTED")])
    assert verify_llm_call(client, "some prompt") == "SUPPORTED"


def test_verify_llm_call_returns_unsupported_verdict_with_reason():
    client = _ScriptedClient([_verify_response("UNSUPPORTED", "20 days is not stated in the excerpts")])
    assert verify_llm_call(client, "some prompt") == "UNSUPPORTED: 20 days is not stated in the excerpts"


def test_verify_llm_call_ignores_reasoning_verbosity_in_verdict_classification():
    # The actual reported bug: a verifier that reasons out loud before reaching its
    # conclusion must not corrupt the classification. Since verdict comes from an
    # enum-constrained field rather than prefix-parsed prose, a long, self-correcting-looking
    # reason has no way to affect whether the returned string starts with "SUPPORTED".
    rambling_reason = (
        "The draft asserts X, but this contradicts Y, which is actually consistent... "
        "however, applying the general rule, the conclusion follows correctly. "
        "This reasoning is actually supported as a valid application of the general default."
    )
    client = _ScriptedClient([_verify_response("SUPPORTED", rambling_reason)])
    assert verify_llm_call(client, "some prompt") == "SUPPORTED"


def test_verify_llm_call_forces_the_verification_tool():
    # No free-text fallback: the model must call report_verification every time, so it can
    # never end the turn with unstructured chat text instead of a classification.
    client = _ScriptedClient([_verify_response("SUPPORTED")])
    verify_llm_call(client, "some prompt")
    assert client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "report_verification"}


def test_answer_question_stops_after_max_tool_iterations():
    # A model that never stops requesting tool calls must not be allowed to loop forever —
    # unbounded API cost with no circuit breaker. Every response is a search call, so the fake
    # client would happily loop indefinitely if answer_question didn't cap it itself.
    client = _ScriptedClient([_search_response("call")])

    result = answer_question("What is PTO?", _StubIndex(), client=client)

    assert result.grounded is False
    assert len(client.messages.calls) == MAX_TOOL_ITERATIONS


def test_answer_question_completes_normally_within_iteration_cap():
    # A typical short exchange (one search call, then submit_answer, then verification) must
    # be unaffected by the cap, and the final text must be the deterministically-assembled
    # format_answer() output, not whatever layout the model happened to choose.
    client = _ScriptedClient(
        [
            _search_response("call_1"),
            _submit_answer_response("call_2", "15 days per year.", "Standard global entitlement.", "Test Handbook, 4.2 PTO"),
            _verify_response("SUPPORTED"),
        ]
    )

    result = answer_question("What is PTO?", _StubIndex(), client=client)

    assert result.grounded is True
    assert result.text == "15 days per year.\n\nStandard global entitlement.\n\n— (Test Handbook, 4.2 PTO)"
    assert len(client.messages.calls) == 3
