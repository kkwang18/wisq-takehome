from __future__ import annotations

from main import EXAMPLE_QUERIES, select_questions


def test_example_queries_match_the_take_home_pdf():
    assert len(EXAMPLE_QUERIES) == 8
    assert "Taiwanese employee" in EXAMPLE_QUERIES[0]


def test_select_questions_defaults_to_example_queries():
    assert select_questions(None) == EXAMPLE_QUERIES


def test_select_questions_uses_ask_override():
    assert select_questions("What is PTO in Germany?") == ["What is PTO in Germany?"]
