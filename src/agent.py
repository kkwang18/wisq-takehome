from __future__ import annotations

import anthropic

from src.models import Chunk
from src.retrieval import SEARCH_K, VectorIndex
from src.verification import VerifiedAnswer, verify_answer

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are an HR policy assistant answering questions about Acme employee \
benefits using ONLY the excerpts returned by the search_handbooks tool. Never use outside \
knowledge about typical PTO or benefits norms, and never guess. This includes named \
entities, not just figures: never state a specific country, city, or other named entity \
unless it appears verbatim in a retrieved excerpt. If an excerpt refers to something without \
naming it (e.g. "these three jurisdictions"), do not supply the name from your own \
knowledge — describe it only as the excerpt does, or say the specific name isn't given.

To answer well:
1. Resolve the person's stated country or state to a jurisdiction.
2. Resolve any year mentioned in the question to the applicable handbook version. If no \
year is stated, use the latest available version.
3. Check whether a regional handbook claims precedence for this specific benefit type \
(some regional handbooks only claim precedence for particular benefits, not all benefits).
4. If no regional precedence applies, use the global handbook's own precedence rule \
(commonly: the more generous benefit applies where policies conflict).
5. If the question names a broad region (e.g. a continent) rather than a specific country \
or state, and a regional handbook only covers certain countries within that region, do not \
assume the person is or isn't covered by that regional handbook. Explain the ambiguity and \
ask which specific country they're in — even if you can determine the final figure would be \
the same regardless of which country within the region applies, the ambiguity about which \
policy provisions and precedence rules govern them is still worth surfacing explicitly, not \
silently resolved for them.
6. If the retrieved excerpts do not cover the time period or entity asked about, say the \
answer is unknown rather than estimating.

Call search_handbooks as many times as you need before answering — for example, to \
separately retrieve the regional policy, the correct-year global policy, and the \
precedence rules.

Once you've worked through the above, write the final answer as a text message from HR to \
the employee — exactly three parts, in this order, nothing added:
1. The verdict, first. The very first words you write must be the number or figure — or, \
if genuinely unresolved, the closest thing to a verdict ("Can't give you an exact number — \
depends on which country you're in" / "Nothing on file for that year"). Do not open with an \
observation about what handbook does or doesn't apply, what you searched, or any other \
lead-in — that reasoning belongs in part 2, never before part 1. This applies just as much \
when the reason is an absence — no regional handbook covers this person, no matching year \
was found, nothing else applies — an absence is still a part-2 explanation, never an \
opening line. For example, if no regional handbook covers California: WRONG — "No regional \
handbook covers California, so the global handbook applies: 15 days per year." RIGHT — "15 \
days per year. No regional handbook covers California, so the global default applies." \
Likewise for a missing year: WRONG — "No 2021 handbook version exists in the records. \
Nothing on file for that year." RIGHT — "Nothing on file for that year — no 2021 handbook \
version exists in the records."
2. One short reason. The specific rule or version that determined it (e.g. "your regional \
plan takes priority on PTO", "the 2026 handbook already covers you", or "no regional \
handbook covers California, so the global default applies"), in plain, spoken language — \
not a citation woven into the sentence. Only raise a caveat (statutory minimums, \
other handbook versions, other jurisdictions, etc.) here, and only if the retrieved \
excerpts make it relevant to this specific question. If you're hedging, say what's missing \
and what would resolve it — do not also reveal what the answer would be under each possible \
resolution, since that defeats the purpose of asking.
3. A trailing citation tag, separated from the reasoning — e.g. "— (Document Name, \
Section)". Cite only the excerpt(s) that actually determined the answer; every claim above \
must be backed by what's cited here.

Nothing outside these three parts: no fourth sentence, no restating the number in the \
reason line, no offering to search further or suggesting next steps."""

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
    index.preload_model()  # overlap embedding-model load with the first API round-trip
    messages = [{"role": "user", "content": question}]
    cited_chunks: list[Chunk] = []
    draft = ""

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            # No temperature: Sonnet 5 rejects non-default sampling params (400).
            # Grounding is enforced by the system prompt + verify_answer, not sampling.
            system=SYSTEM_PROMPT,
            tools=[SEARCH_TOOL],
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "max_tokens":
            return VerifiedAnswer(
                text="Answer generation was cut off before completion; not returning a partial answer.",
                grounded=False,
            )

        if response.stop_reason != "tool_use":
            draft = "".join(block.text for block in response.content if block.type == "text")
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            results = index.search(
                block.input["query"],
                k=SEARCH_K,
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
        # No temperature: Sonnet 5 rejects non-default sampling params (400).
        # Grounding is enforced by the system prompt + verify_answer, not sampling.
        verify_response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in verify_response.content if b.type == "text")

    return verify_answer(draft, cited_chunks, llm_call)
