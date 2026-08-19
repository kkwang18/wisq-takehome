from __future__ import annotations

from src.agent import SEARCH_TOOL, SYSTEM_PROMPT


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
