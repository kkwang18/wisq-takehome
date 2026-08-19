from __future__ import annotations

import anthropic

from src.models import Chunk
from src.retrieval import VectorIndex
from src.verification import VerifiedAnswer, verify_answer

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are an HR policy assistant answering questions about Acme employee \
benefits using ONLY the excerpts returned by the search_handbooks tool. Never use outside \
knowledge about typical PTO or benefits norms, and never guess.

To answer well:
1. Resolve the person's stated country or state to a jurisdiction.
2. Resolve any year mentioned in the question to the applicable handbook version. If no \
year is stated, use the latest available version.
3. Check whether a regional handbook claims precedence for this specific benefit type \
(some regional handbooks only claim precedence for particular benefits, not all benefits).
4. If no regional precedence applies, use the global handbook's own precedence rule \
(commonly: the more generous benefit applies where policies conflict).
5. If the jurisdiction in the question is ambiguous and different candidate jurisdictions \
in the retrieved excerpts would give different answers, do not guess — explain the \
ambiguity and ask for clarification instead of picking one.
6. If the retrieved excerpts do not cover the time period or entity asked about, say the \
answer is unknown rather than estimating.

Call search_handbooks as many times as you need before answering — for example, to \
separately retrieve the regional policy, the correct-year global policy, and the \
precedence rules.

Every factual claim in your final answer must cite its source as (Document Name, Section). \
Do not state a figure or rule that isn't directly present in a retrieved excerpt."""

SEARCH_TOOL = {
    "name": "search_handbooks",
    "description": "Search the Acme handbooks for relevant policy excerpts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text search query, e.g. 'PTO entitlement' or 'gym membership reimbursement'",
            },
            "doc_type": {
                "type": "string",
                "enum": ["global_handbook", "regional_handbook"],
                "description": "Optional filter to only one kind of handbook",
            },
            "version_year": {
                "type": "integer",
                "description": "Optional filter to a specific handbook version year",
            },
        },
        "required": ["query"],
    },
}


def _format_excerpts(results) -> str:
    if not results:
        return "No matching excerpts found."
    return "\n\n".join(f"[{sc.chunk.doc.display_name} - {sc.chunk.section_title}]\n{sc.chunk.text}" for sc in results)


def answer_question(question: str, index: VectorIndex, client: anthropic.Anthropic | None = None) -> VerifiedAnswer:
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    cited_chunks: list[Chunk] = []
    draft = ""

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=[SEARCH_TOOL],
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            draft = "".join(block.text for block in response.content if block.type == "text")
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            results = index.search(
                block.input["query"],
                k=5,
                doc_type=block.input.get("doc_type"),
                version_year=block.input.get("version_year"),
            )
            cited_chunks.extend(sc.chunk for sc in results)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _format_excerpts(results),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    def llm_call(prompt: str) -> str:
        verify_response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in verify_response.content if b.type == "text")

    return verify_answer(draft, cited_chunks, llm_call)
