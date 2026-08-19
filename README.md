# Acme Benefits Q&A (RAG)

Answers questions about Acme's employee handbooks using retrieval-augmented generation:
local embeddings for search, Claude for multi-hop reasoning over conflicting/versioned
policy documents, with a grounding-verification pass before any answer is returned.

See `docs/superpowers/specs/2026-08-19-rag-qa-system-design.md` for the design, and
`HISTORY.md` / `TRANSCRIPT.md` for the conversation that shaped it.

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-...

## Build the index

Run this once, and again whenever a document in `documents.yaml` is added, changed, or
deprecated:

    python ingest.py

## Ask questions

    python main.py                              # runs the 8 example queries from the take-home PDF
    python main.py --ask "What is the PTO allowance for a remote employee in Germany?"

## Tests

    pytest                    # fast, fully offline: unit tests + retrieval recall checks
    python eval.py            # slow, real Claude API calls: full end-to-end acceptance run
