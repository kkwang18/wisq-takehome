from __future__ import annotations

import re

# Union of both files' marker lists as they stood before this extraction — eval.py had
# "no matching handbook version"/"no handbook version exists"; edge_cases.py had "no fixed
# number". Neither file loses a marker it relied on; since these are OR'd, a superset can
# only make "unknown" detection more permissive, never break a currently-passing case.
UNKNOWN_MARKERS = [
    "unknown",
    "don't have enough information",
    "do not have enough information",
    "cannot determine",
    "can't determine",
    "no reliable basis",
    "not enough information",
    "insufficient information",
    "unable to confirm",
    "can't confirm",
    "cannot confirm",
    "don't know",
    "do not know",
    "cannot answer this question with confidence",
    "can't answer this question with confidence",
    "no factual basis",
    "don't have a factual basis",
    "do not have a factual basis",
    "would require guessing",
    "avoid guessing",
    "should avoid guessing",
    "should avoid stating",
    "nothing on file",
    "no policy on record",
    "not on record",
    "no matching handbook version",
    "no handbook version exists",
    "no fixed number",
    "no specific number",
]

HEDGE_MARKERS = ["ambig", "clarif", "which country", "specific country", "unclear", "depends on"]


def _numeric_boundary_matches(marker: str, text: str) -> bool:
    """Substring match requiring non-digit, non-comma characters on both sides, so a
    numeric/currency marker like "50" or "1,000" can't match inside a larger number it
    isn't actually part of (e.g. "50" inside "$500", "1,000" inside "$21,000",
    "14" inside "2014") — confirmed live as a real false-positive risk, not theoretical."""
    pattern = r"(?<![0-9,])" + re.escape(marker) + r"(?![0-9,])"
    return re.search(pattern, text) is not None


def matches(expected, result_text: str, grounded: bool) -> bool:
    # A list/tuple of conditions means ALL must hold — for a compound question that mixes a
    # false premise with a genuinely-unanswerable sub-question, a single marker can't tell a
    # correct answer from one that got the premise right by luck while hallucinating the
    # other half (see tests/test_matching.py for the live case that exposed this).
    if isinstance(expected, (list, tuple)):
        return all(matches(e, result_text, grounded) for e in expected)
    lowered = result_text.lower()
    if expected == "unknown":
        return any(marker in lowered for marker in UNKNOWN_MARKERS) or not grounded
    if expected == "hedge":
        # Unlike "unknown", a hedge/numeric expectation implies the system actually confirmed
        # the figure or ambiguity — an ungrounded rejection must never satisfy it just because
        # the rejection text happens to contain a matching word/digit by accident (a rejected
        # draft's dumped verifier reasoning can echo almost anything from the source excerpts).
        return grounded and any(word in lowered for word in HEDGE_MARKERS)
    return grounded and _numeric_boundary_matches(expected, result_text)
