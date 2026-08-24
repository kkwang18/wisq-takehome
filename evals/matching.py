from __future__ import annotations

import re

from src.verification import VerifiedAnswer

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

from dataclasses import dataclass, field


@dataclass
class Expectation:
    numeric: str | None = None
    unknown: bool = False
    hedge: bool = False
    rejected: bool = False
    required: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    doc_type: str | None = None
    version_year: int | None = None


_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000}

_WORD_NUMBER_PATTERN = re.compile(
    r"\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|thousand)[\s-]*)+\b",
    re.IGNORECASE,
)
_NUMBER_TOKEN_PATTERN = re.compile(r"[0-9][0-9,]*")


def _word_to_number(phrase: str) -> str | None:
    """Convert a small English number phrase (e.g. "fifty", "one thousand") to a digit
    string, or None if `phrase` isn't a recognized number word/phrase. Deliberately scoped to
    the small integers this corpus's real answers use (day counts, dollar amounts up to a few
    thousand) — not a general English-number parser."""
    words = phrase.lower().replace("-", " ").split()
    if not words:
        return None
    total = 0
    current = 0
    for word in words:
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word in _SCALES:
            current = (current or 1) * _SCALES[word]
            if _SCALES[word] == 1000:
                total += current
                current = 0
        else:
            return None
    return str(total + current)


def _normalize_numbers(text: str) -> set[str]:
    """Extract every number-like token from `text`, normalized: `$`/commas stripped from
    digit runs, and small English number words/phrases converted to their digit-string
    equivalent via `_word_to_number`."""
    found = set()
    for match in _NUMBER_TOKEN_PATTERN.finditer(text.replace("$", "")):
        digits = match.group().replace(",", "")
        if digits:
            found.add(digits)
    for match in _WORD_NUMBER_PATTERN.finditer(text):
        number = _word_to_number(match.group())
        if number is not None:
            found.add(number)
    return found


def _matches_numeric_expectation(numeric: str, result: VerifiedAnswer) -> bool:
    if not result.grounded:
        return False
    expected_normalized = _normalize_numbers(numeric)
    if not expected_normalized:
        return False
    return bool(expected_normalized & _normalize_numbers(result.text))


def _matches_expectation(expectation: Expectation, result: VerifiedAnswer) -> bool:
    if expectation.numeric is not None:
        if not _matches_numeric_expectation(expectation.numeric, result):
            return False
    return True


def _numeric_boundary_matches(marker: str, text: str) -> bool:
    """Substring match requiring non-digit, non-comma characters on both sides, so a
    numeric/currency marker like "50" or "1,000" can't match inside a larger number it
    isn't actually part of (e.g. "50" inside "$500", "1,000" inside "$21,000",
    "14" inside "2014") — confirmed live as a real false-positive risk, not theoretical."""
    pattern = r"(?<![0-9,])" + re.escape(marker) + r"(?![0-9,])"
    return re.search(pattern, text) is not None


def matches(expected, result: VerifiedAnswer) -> bool:
    if isinstance(expected, Expectation):
        return _matches_expectation(expected, result)
    # A list/tuple of conditions means ALL must hold — for a compound question that mixes a
    # false premise with a genuinely-unanswerable sub-question, a single marker can't tell a
    # correct answer from one that got the premise right by luck while hallucinating the
    # other half (see tests/test_matching.py for the live case that exposed this).
    if isinstance(expected, (list, tuple)):
        return all(matches(e, result) for e in expected)
    lowered = result.text.lower()
    if expected == "unknown":
        return any(marker in lowered for marker in UNKNOWN_MARKERS) or not result.grounded
    if expected == "hedge":
        # Unlike "unknown", a hedge/numeric expectation implies the system actually confirmed
        # the figure or ambiguity — an ungrounded rejection must never satisfy it just because
        # the rejection text happens to contain a matching word/digit by accident (a rejected
        # draft's dumped verifier reasoning can echo almost anything from the source excerpts).
        return result.grounded and any(word in lowered for word in HEDGE_MARKERS)
    return result.grounded and _numeric_boundary_matches(expected, result.text)
