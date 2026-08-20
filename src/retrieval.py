from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from src.models import Chunk, DocMeta, ScoredChunk

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SEARCH_K = 8


def embed_text(chunk: Chunk) -> str:
    """The string actually embedded for a chunk: its own text prefixed with a
    metadata header. The 2025 and 2026 PTO paragraphs are nearly identical
    except the number itself, so nothing in the raw text says which version
    it belongs to — embedding the header alongside the text makes the vector
    itself version/jurisdiction-aware. Queries are embedded raw (see
    VectorIndex.search); only chunk-side text gets this treatment."""
    jurisdictions = ", ".join(chunk.doc.jurisdictions) if chunk.doc.jurisdictions else "global"
    year = chunk.doc.version_year if chunk.doc.version_year is not None else "n/a"
    header = (
        f"[{chunk.doc.display_name} · {chunk.doc.doc_type} · "
        f"jurisdictions: {jurisdictions} · version_year: {year} · "
        f"Section: {chunk.section_title}]"
    )
    return f"{header}\n{chunk.text}"


class VectorIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, model: SentenceTransformer | None = None):
        self.chunks = chunks
        self.embeddings = embeddings
        self._model = model
        self._model_load_thread: threading.Thread | None = None

    @classmethod
    def build(cls, chunks: list[Chunk], model: SentenceTransformer | None = None) -> "VectorIndex":
        model = model or SentenceTransformer(MODEL_NAME)
        texts = [embed_text(c) for c in chunks]
        vectors = np.array(model.encode(texts, normalize_embeddings=True))
        return cls(chunks, vectors, model=model)

    def preload_model(self) -> None:
        """Start loading the embedding model on a background thread, so the load
        (~3s of import + instantiation) overlaps with whatever the caller does next
        (e.g. the first Claude API round-trip) instead of blocking the first search()."""
        if self._model is not None or self._model_load_thread is not None:
            return
        thread = threading.Thread(target=lambda: setattr(self, "_model", SentenceTransformer(MODEL_NAME)))
        thread.start()
        self._model_load_thread = thread

    def _get_model(self) -> SentenceTransformer:
        if self._model_load_thread is not None:
            self._model_load_thread.join()
            self._model_load_thread = None
        if self._model is None:
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    def search(
        self,
        query: str,
        k: int = 5,
        doc_type: str | None = None,
        version_year: int | None = None,
    ) -> list[ScoredChunk]:
        candidate_indices = [
            i
            for i, c in enumerate(self.chunks)
            if (doc_type is None or c.doc.doc_type == doc_type)
            and (version_year is None or c.doc.version_year is None or c.doc.version_year == version_year)
        ]
        if not candidate_indices:
            return []

        model = self._get_model()
        q_vec = np.array(model.encode([query], normalize_embeddings=True))[0]

        scored = [
            ScoredChunk(chunk=self.chunks[i], score=float(np.dot(self.embeddings[i], q_vec)))
            for i in candidate_indices
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return scored[:k]

    def save(self, dir_path: str) -> None:
        out = Path(dir_path)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "chunks.jsonl", "w") as f:
            for c in self.chunks:
                f.write(
                    json.dumps(
                        {
                            "text": c.text,
                            "section_title": c.section_title,
                            "doc": {
                                "file": c.doc.file,
                                "doc_type": c.doc.doc_type,
                                "jurisdictions": c.doc.jurisdictions,
                                "version_year": c.doc.version_year,
                                "display_name": c.doc.display_name,
                            },
                        }
                    )
                    + "\n"
                )
        np.save(out / "embeddings.npy", self.embeddings)

    @classmethod
    def load(cls, dir_path: str, model: SentenceTransformer | None = None) -> "VectorIndex":
        src = Path(dir_path)
        chunks = []
        with open(src / "chunks.jsonl") as f:
            for line in f:
                data = json.loads(line)
                doc = DocMeta(**data["doc"])
                chunks.append(Chunk(text=data["text"], section_title=data["section_title"], doc=doc))
        embeddings = np.load(src / "embeddings.npy")
        return cls(chunks, embeddings, model=model)
