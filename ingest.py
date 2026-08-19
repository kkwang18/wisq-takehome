from __future__ import annotations

import argparse

from src.chunking import chunk_document
from src.docx_reader import read_docx_paragraphs
from src.manifest import load_manifest
from src.models import Chunk
from src.retrieval import VectorIndex


def build_index(manifest_path: str) -> VectorIndex:
    docs = load_manifest(manifest_path)
    all_chunks: list[Chunk] = []
    for doc_meta in docs:
        paragraphs = read_docx_paragraphs(doc_meta.file)
        all_chunks.extend(chunk_document(paragraphs, doc_meta))
    return VectorIndex.build(all_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the RAG index from documents.yaml")
    parser.add_argument("--manifest", default="documents.yaml")
    parser.add_argument("--out", default="index")
    args = parser.parse_args()

    index = build_index(args.manifest)
    index.save(args.out)
    print(f"Indexed {len(index.chunks)} chunks from {args.manifest} into {args.out}/")


if __name__ == "__main__":
    main()
