from __future__ import annotations

import numpy as np
import pytest
from sentence_transformers import SentenceTransformer

from src.models import Chunk, DocMeta
from src.retrieval import VectorIndex, embed_text

GLOBAL_2025 = DocMeta(file="g25.docx", doc_type="global_handbook", jurisdictions=None, version_year=2025, display_name="Global Handbook 2025")
GLOBAL_2026 = DocMeta(file="g26.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Global Handbook 2026")
REGIONAL = DocMeta(file="apac.docx", doc_type="regional_handbook", jurisdictions=["Taiwan"], version_year=None, display_name="APAC Benefits Handbook")


@pytest.fixture(scope="module")
def model():
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def sample_chunks():
    return [
        Chunk(text="The standard global PTO entitlement is 14 days per year.", section_title="4.2 PTO", doc=GLOBAL_2025),
        Chunk(text="The standard global PTO entitlement is 15 days per year.", section_title="4.2 PTO", doc=GLOBAL_2026),
        Chunk(text="Eligible employees in Taiwan are entitled to 12 days of PTO per year.", section_title="PTO", doc=REGIONAL),
        Chunk(text="The standard global gym membership benefit is $50 per month.", section_title="Section 3", doc=GLOBAL_2026),
    ]


def test_embed_text_includes_metadata_header():
    text = embed_text(sample_chunks()[1])
    assert "Global Handbook 2026" in text
    assert "2026" in text
    assert "4.2 PTO" in text
    assert "15 days per year" in text


def test_search_ranks_topically_relevant_chunk_first(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("gym membership reimbursement", k=1)
    assert results[0].chunk.text.startswith("The standard global gym")


def test_search_filters_by_doc_type(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("PTO entitlement", k=10, doc_type="regional_handbook")
    assert len(results) == 1
    assert results[0].chunk.doc.doc_type == "regional_handbook"


def test_search_filters_by_version_year(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("PTO entitlement", k=10, version_year=2025)
    result_years = {r.chunk.doc.version_year for r in results}
    assert 2026 not in result_years
    assert 2025 in result_years


def test_search_version_year_filter_always_includes_undated_chunks(model):
    # A chunk with version_year=None (e.g. the APAC regional handbook, which has no
    # yearly editions) must survive every version_year filter, not just an absent one —
    # otherwise a query that names a year alongside a regional jurisdiction (e.g. "Taiwan
    # PTO in 2025") silently excludes the regional precedence chunk from that search call.
    index = VectorIndex.build(sample_chunks(), model=model)
    for year in (2025, 2026, 1999):
        results = index.search("PTO entitlement", k=10, version_year=year)
        assert any(r.chunk.doc.version_year is None for r in results), f"undated chunk missing for version_year={year}"


def test_search_returns_empty_when_filters_match_nothing(model):
    index = VectorIndex.build(sample_chunks(), model=model)
    results = index.search("PTO entitlement", k=10, doc_type="global_handbook", version_year=1999)
    assert results == []


def test_preload_model_runs_in_background_and_get_model_reuses_it():
    index = VectorIndex(sample_chunks(), np.zeros((4, 384)))
    assert index._model is None

    index.preload_model()
    index.preload_model()  # idempotent: must not start a second background load

    loaded = index._get_model()
    assert isinstance(loaded, SentenceTransformer)
    assert index._get_model() is loaded  # subsequent calls reuse the same instance


def test_save_and_load_round_trip(tmp_path, model):
    index = VectorIndex.build(sample_chunks(), model=model)
    index.save(str(tmp_path / "idx"))

    loaded = VectorIndex.load(str(tmp_path / "idx"), model=model)

    assert len(loaded.chunks) == len(index.chunks)
    assert loaded.chunks[0].text == index.chunks[0].text
    assert loaded.chunks[0].doc == index.chunks[0].doc
    results = loaded.search("gym membership reimbursement", k=1)
    assert results[0].chunk.text.startswith("The standard global gym")
