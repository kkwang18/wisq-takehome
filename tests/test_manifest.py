from __future__ import annotations

from pathlib import Path

from src.manifest import load_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_manifest.yaml"


def test_load_manifest_filters_to_active_entries():
    docs = load_manifest(str(FIXTURE))
    assert len(docs) == 1
    assert docs[0].file == "fake_a.docx"
    assert docs[0].doc_type == "global_handbook"
    assert docs[0].jurisdictions is None
    assert docs[0].version_year == 2025
    assert docs[0].display_name == "Fake Handbook 2025"


def test_load_manifest_preserves_jurisdictions_list():
    import yaml

    raw = yaml.safe_load(FIXTURE.read_text())
    raw[1]["active"] = True
    tmp = FIXTURE.parent / "sample_manifest_all_active.yaml"
    tmp.write_text(yaml.safe_dump(raw))
    try:
        docs = load_manifest(str(tmp))
        regional = [d for d in docs if d.doc_type == "regional_handbook"][0]
        assert regional.jurisdictions == ["Testland"]
    finally:
        tmp.unlink()
