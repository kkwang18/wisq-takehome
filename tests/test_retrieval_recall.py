from __future__ import annotations

import pytest

from ingest import build_index
from src.retrieval import SEARCH_K


@pytest.fixture(scope="module")
def index():
    return build_index("documents.yaml")


def test_taiwan_pto_recalls_regional_figure(index):
    results = index.search("PTO allowance Taiwan employee", k=5, doc_type="regional_handbook")
    texts = " ".join(r.chunk.text for r in results)
    assert "12 days" in texts


def test_california_pto_2025_recalls_correct_year(index):
    results = index.search("PTO allowance 2025", k=5, doc_type="global_handbook", version_year=2025)
    texts = " ".join(r.chunk.text for r in results)
    assert "14 days" in texts


def test_california_pto_2026_recalls_correct_year(index):
    results = index.search("PTO allowance 2026", k=5, doc_type="global_handbook", version_year=2026)
    texts = " ".join(r.chunk.text for r in results)
    assert "15 days" in texts


def test_gym_benefit_recalls_both_regional_and_global_amounts(index):
    regional = index.search("gym membership reimbursement", k=5, doc_type="regional_handbook")
    global_2026 = index.search("gym membership reimbursement", k=5, doc_type="global_handbook", version_year=2026)
    assert any("$30" in r.chunk.text for r in regional)
    assert any("$50" in r.chunk.text for r in global_2026)


def test_precedence_rules_are_retrievable(index):
    global_results = index.search("conflicts and precedence more generous benefit applies", k=5, doc_type="global_handbook", version_year=2026)
    regional_results = index.search("conflicts and precedence PTO takes precedence over global", k=5, doc_type="regional_handbook")
    assert any("more generous" in r.chunk.text.lower() for r in global_results)
    assert any("takes precedence" in r.chunk.text.lower() for r in regional_results)


def test_apac_scope_is_retrievable_to_rule_out_california():
    """The agent needs to be able to find that APAC only covers China/Japan/Taiwan
    in order to correctly conclude California isn't covered by it."""
    index_ = build_index("documents.yaml")
    results = index_.search("which countries does this regional handbook apply to", k=SEARCH_K, doc_type="regional_handbook")
    texts = " ".join(r.chunk.text for r in results)
    assert "Taiwan" in texts
