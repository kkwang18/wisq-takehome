# Acme Benefits Q&A (RAG)

Answers questions about Acme's employee handbooks using retrieval-augmented generation:
local embeddings for search, Claude for multi-hop reasoning over conflicting/versioned
policy documents, with a grounding-verification pass before any answer is returned.

See `docs/DESIGN.md` for the current system design (invariants, architecture, known failure
modes, and the roadmap to scale), `docs/TRANSCRIPT.md` for the full conversation that
shaped it (`docs/HISTORY.md` is a short, section-linked index into it — start there), and
`docs/backlog/` for known gaps and deferred work with full write-ups (not just a one-line
TODO each). `docs/superpowers/specs/2026-08-19-rag-qa-system-design.md` is the original
pre-implementation proposal, kept for historical context.

Requires Python 3.9+ (developed and tested against 3.9). The three source `.docx` files and
the take-home brief are already checked into `Take Home Test/` — no separate download needed.

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

No API key needed yet — everything below this line works offline until you reach "Ask
questions."

## Build the index

Only needed for `main.py` below (`pytest` and the `evals/` scripts each build their own index
in memory from `documents.yaml` on every run, so they don't need this step). Run it once, and
again whenever a document in `documents.yaml` is added, changed, or deprecated:

    python ingest.py

## Ask questions

Needs a real API key from here on:

    export ANTHROPIC_API_KEY=sk-...
    python main.py                              # runs the 8 example queries from the take-home PDF
    python main.py --ask "What is the PTO allowance for a remote employee in Germany?"

## Tests

    pytest                       # fast, fully offline, no API key: unit tests + retrieval recall checks
    python -m evals.eval         # needs ANTHROPIC_API_KEY: the 8 take-home example queries
    python -m evals.edge_cases   # needs ANTHROPIC_API_KEY, slower and pricier: 38-case
                                  # production-readiness suite (entity resolution, negative
                                  # space, grounding, consistency, precedence generalization,
                                  # entity-hallucination guard) — run on demand, not on every
                                  # commit
