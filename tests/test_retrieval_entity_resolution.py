from __future__ import annotations

import pytest

from ingest import build_index
from src.retrieval import SEARCH_K


@pytest.fixture(scope="module")
def index():
    return build_index("documents.yaml")


def _section_titles(results):
    return [r.chunk.section_title for r in results]


def test_lowercase_jurisdiction_still_surfaces_regional_pto(index):
    results = index.search("what is the pto for an employee based in taiwan", k=SEARCH_K)
    assert any("REGIONAL BENEFITS" in t or "CONFLICTS AND PRECEDENCE" in t for t in _section_titles(results))


def test_typo_jurisdiction_still_surfaces_regional_pto(index):
    results = index.search("What is the PTO for an employee based in Tiawan?", k=SEARCH_K)
    assert any("REGIONAL BENEFITS" in t or "CONFLICTS AND PRECEDENCE" in t for t in _section_titles(results))


def test_country_abbreviation_still_surfaces_regional_scope(index):
    results = index.search("What is the gym benefit for an employee in the PRC?", k=SEARCH_K)
    assert any("SCOPE" in t or "REGIONAL BENEFITS" in t for t in _section_titles(results))


def test_alternate_country_name_still_surfaces_regional_scope(index):
    results = index.search("What is the PTO for an employee based in the Republic of China?", k=SEARCH_K)
    assert any("SCOPE" in t or "REGIONAL BENEFITS" in t for t in _section_titles(results))


def test_contractor_exclusion_clause_is_retrievable(index):
    results = index.search("Does the APAC handbook cover contractors?", k=SEARCH_K)
    assert any("SCOPE" in t for t in _section_titles(results))
