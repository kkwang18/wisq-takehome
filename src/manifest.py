from __future__ import annotations

import yaml

from src.models import DocMeta


def load_manifest(path: str) -> list[DocMeta]:
    with open(path) as f:
        raw_entries = yaml.safe_load(f) or []

    docs = []
    for entry in raw_entries:
        if not entry.get("active", False):
            continue
        docs.append(
            DocMeta(
                file=entry["file"],
                doc_type=entry["doc_type"],
                jurisdictions=entry.get("jurisdictions"),
                version_year=entry.get("version_year"),
                display_name=entry["display_name"],
            )
        )
    return docs
