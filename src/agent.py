from __future__ import annotations

import anthropic

from src.models import Chunk, ScoredChunk
from src.retrieval import SEARCH_K, VectorIndex
from src.verification import VerifiedAnswer, verify_answer

MODEL = "claude-sonnet-5"

# Safety cap on the tool-use loop: a non-converging model would otherwise call
# search_handbooks indefinitely, with no circuit breaker on API cost. Real multi-hop
# questions in this corpus (retrieving the regional policy, the correct-year global policy,
# and the precedence rules separately) have been observed to need up to 5 rounds live — set
# generously above that so the cap only trips on genuine non-convergence, not a legitimately
# thorough question.
MAX_TOOL_ITERATIONS = 8

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

Once you've worked through the above, call submit_answer exactly once to give the final \
answer — never write it as plain chat text. Write each field in the voice of a text message \
from HR to the employee: concise and plain-spoken, not a memo. submit_answer takes three \
separate fields, each plain prose only — no bullet points, no numbered lists, no headers, no \
bold or other markdown formatting — in the exact same shape every time no matter how many \
distinct topics the question asks about, and never restate one field's content inside \
another:
1. verdict — first, and alone. The field's content must open with the number or figure — or, \
if genuinely unresolved, the closest thing to a verdict ("Can't give you an exact number — \
depends on which country you're in" / "Nothing on file for that year"). Do not include an \
observation about what handbook does or doesn't apply, what you searched, or any other \
lead-in — that reasoning belongs in reason, never in verdict. This applies just as much when \
the reason is an absence — no regional handbook covers this person, no matching year was \
found, nothing else applies — an absence is still reason-field content, never part of \
verdict. For example, if no regional handbook covers California: WRONG verdict — "No \
regional handbook covers California, so the global handbook applies: 15 days per year." \
RIGHT verdict — "15 days per year." (with the explanation moved entirely into reason). \
Likewise for a missing year: WRONG verdict — "No 2021 handbook version exists in the \
records. Nothing on file for that year." RIGHT verdict — "Nothing on file for that year."
2. reason — one short reason: the specific rule or version that determined it (e.g. "your \
regional plan takes priority on PTO", "the 2026 handbook already covers you", or "no \
regional handbook covers California, so the global default applies"), in plain, spoken \
language — not a citation woven into the sentence, and not a restatement of verdict's \
figure. Only raise a caveat (statutory minimums, other handbook versions, other \
jurisdictions, etc.) here, and only if the retrieved excerpts make it relevant to this \
specific question. If you're hedging, say what's missing and what would resolve it — do not \
also reveal what the answer would be under each possible resolution, since that defeats the \
purpose of asking, even when every resolution happens to converge on the same figure. For \
example, if a regional handbook covers only part of a broader named region: WRONG — "Depends \
on your country, but either way you'd get $50/month since the global rate is more generous \
than the regional one." RIGHT — "I need to know your specific country to confirm the rate." \
Naming what each branch resolves to is exactly as disqualifying as naming the number itself, \
even when the branches happen to agree. This includes naming each candidate policy's own \
number as supporting detail for the rule ("the regional rate is $30, the global rate is $50, \
so the more generous one applies") — that still lets the person compute the answer themselves \
without confirming the missing fact, so it's disqualifying too. Describe which rule would \
decide it ("whichever policy is more generous would apply") without stating either side's \
number.
3. citation — cite only the excerpt(s) that actually determined the answer, e.g. "Document \
Name, Section". Do not include a leading dash or parentheses; those are added automatically \
when the fields are assembled. Every claim in verdict and reason must be backed by what's \
named here.

If the question bundles more than one distinct topic (e.g. sick days, 401k, and insurance \
in one message), do not call submit_answer once per topic — call it exactly once for the \
whole message, in the same shape. verdict still names every topic's outcome together (e.g. \
"No fixed sick-day count, no 401k, and no vision/dental/medical insurance are on file."); \
reason still covers all of them together; citation may name more than one document or \
section. A hedge or "unknown" verdict follows this same shape too: state the hedge or \
"unknown" first in verdict, then the reason, then the citation.

Nothing outside these three fields: no fourth field, no restating the number in reason, no \
offering to search further or suggesting next steps."""

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

SUBMIT_ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Give the final answer to the employee's question, as three separate "
    "fields. Call this exactly once, after all needed search_handbooks calls, instead of "
    "writing the answer as plain chat text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "description": "The verdict or figure, first and alone — no reasoning, no citation.",
            },
            "reason": {
                "type": "string",
                "description": "The one short reason the verdict is what it is — no citation, "
                "no restating verdict's figure.",
            },
            "citation": {
                "type": "string",
                "description": "The document/section name(s) that determined the answer, e.g. "
                "'Acme Employee Handbook 2026, Section 4.2'. No leading dash or parentheses.",
            },
        },
        "required": ["verdict", "reason", "citation"],
    },
}

VERIFY_TOOL = {
    "name": "report_verification",
    "description": "Report whether every factual claim in the draft answer is directly "
    "supported by the excerpts. Call this exactly once with your final classification.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["SUPPORTED", "UNSUPPORTED"],
                "description": "SUPPORTED if every claim is backed by the excerpts, UNSUPPORTED otherwise.",
            },
            "reason": {
                "type": "string",
                "description": "If UNSUPPORTED, briefly explain which claim isn't backed and why. "
                "Leave empty if SUPPORTED.",
            },
        },
        "required": ["verdict", "reason"],
    },
}


def _format_excerpts(results: list[ScoredChunk]) -> str:
    if not results:
        return "No matching excerpts found."
    return "\n\n".join(f"[{sc.chunk.doc.display_name} - {sc.chunk.section_title}]\n{sc.chunk.text}" for sc in results)


def format_answer(verdict: str, reason: str, citation: str) -> str:
    """Deterministically assemble the three submit_answer fields into the final answer text,
    so verdict/reason/citation separation is a code guarantee, not something the model has to
    remember to format consistently."""
    return f"{verdict.strip()}\n\n{reason.strip()}\n\n— ({citation.strip()})"


def verify_llm_call(client: anthropic.Anthropic, prompt: str) -> str:
    """Classify a draft answer as SUPPORTED/UNSUPPORTED via report_verification instead of
    parsing free text. Verdict comes from an enum-constrained tool field, so the verifier's
    reasoning can be as verbose or self-correcting as it likes in `reason` without ever
    corrupting the classification verify_answer parses (see docs/backlog/2026-08-22-verify-
    answer-prefix-parsing-false-rejection.md — a verifier that reasoned aloud from
    "UNSUPPORTED" to a self-corrected "SUPPORTED" tripped a prior startswith("SUPPORTED")
    check on raw free text)."""
    # No temperature: Sonnet 5 rejects non-default sampling params (400).
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        thinking={"type": "disabled"},
        tools=[VERIFY_TOOL],
        tool_choice={"type": "tool", "name": "report_verification"},
        messages=[{"role": "user", "content": prompt}],
    )
    block = next(b for b in response.content if b.type == "tool_use")
    verdict = block.input["verdict"]
    if verdict == "SUPPORTED":
        return "SUPPORTED"
    return f"UNSUPPORTED: {block.input['reason'].strip()}"


def answer_question(question: str, index: VectorIndex, client: anthropic.Anthropic | None = None) -> VerifiedAnswer:
    client = client or anthropic.Anthropic()
    index.preload_model()  # overlap embedding-model load with the first API round-trip
    messages = [{"role": "user", "content": question}]
    cited_chunks: list[Chunk] = []
    draft = ""
    iterations = 0

    while True:
        iterations += 1
        if iterations > MAX_TOOL_ITERATIONS:
            return VerifiedAnswer(
                text="Answer generation required too many tool calls to converge; not returning a partial answer.",
                grounded=False,
                cited_chunks=cited_chunks,
            )
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            # No temperature: Sonnet 5 rejects non-default sampling params (400).
            # Grounding is enforced by the system prompt + verify_answer, not sampling.
            system=SYSTEM_PROMPT,
            tools=[SEARCH_TOOL, SUBMIT_ANSWER_TOOL],
            # Force a tool call every turn: the model must either search or submit_answer,
            # never fall back to writing the final answer as free chat text (which is exactly
            # what made verdict/reason/citation separation inconsistent before this fix).
            tool_choice={"type": "any"},
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "max_tokens":
            return VerifiedAnswer(
                text="Answer generation was cut off before completion; not returning a partial answer.",
                grounded=False,
                cited_chunks=cited_chunks,
            )

        if response.stop_reason != "tool_use":
            draft = "".join(block.text for block in response.content if block.type == "text")
            break

        tool_results = []
        submit_input = None
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_answer":
                submit_input = block.input
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
        if submit_input is not None:
            draft = format_answer(submit_input["verdict"], submit_input["reason"], submit_input["citation"])
            break
        messages.append({"role": "user", "content": tool_results})

    return verify_answer(draft, cited_chunks, lambda prompt: verify_llm_call(client, prompt))
