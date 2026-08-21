from __future__ import annotations

from types import SimpleNamespace

from src.agent import MAX_TOOL_ITERATIONS, SEARCH_TOOL, SYSTEM_PROMPT, answer_question
from src.models import Chunk, DocMeta, ScoredChunk


def test_system_prompt_encodes_grounding_and_precedence_rules():
    lowered = SYSTEM_PROMPT.lower()
    assert "search_handbooks" in lowered
    assert "ambiguous" in lowered or "ambiguity" in lowered
    assert "unknown" in lowered
    assert "cite" in lowered
    assert "more generous" in lowered


def test_search_tool_schema_exposes_metadata_filters():
    props = SEARCH_TOOL["input_schema"]["properties"]
    assert "query" in props
    assert "doc_type" in props
    assert "version_year" in props
    assert SEARCH_TOOL["input_schema"]["required"] == ["query"]


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


def _tool_use_response(call_id: str):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=call_id, input={"query": "pto"})],
    )


def _text_response(text: str):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def test_answer_question_stops_after_max_tool_iterations():
    # A model that never stops requesting tool calls must not be allowed to loop forever —
    # unbounded API cost with no circuit breaker. Every response is tool_use, so the fake
    # client would happily loop indefinitely if answer_question didn't cap it itself.
    client = _ScriptedClient([_tool_use_response("call")])

    result = answer_question("What is PTO?", _StubIndex(), client=client)

    assert result.grounded is False
    assert len(client.messages.calls) == MAX_TOOL_ITERATIONS


def test_answer_question_completes_normally_within_iteration_cap():
    # A typical short exchange (one tool call, then a draft, then verification) must be
    # unaffected by the cap.
    client = _ScriptedClient(
        [
            _tool_use_response("call_1"),
            _text_response("15 days per year. Standard global entitlement. — (Test Handbook, 4.2 PTO)"),
            _text_response("SUPPORTED"),
        ]
    )

    result = answer_question("What is PTO?", _StubIndex(), client=client)

    assert result.grounded is True
    assert len(client.messages.calls) == 3
