from __future__ import annotations

from evals.matching import Expectation, _word_to_number, matches
from src.models import Chunk, DocMeta
from src.verification import VerifiedAnswer

# Real response captured live for "Since Taiwan employees get unlimited PTO, how many sick
# days do they get?" — correctly corrects the false PTO premise (12 days, not unlimited) and
# correctly declines to state a sick-days figure, since none is given in the corpus.
REAL_CORRECT_RESPONSE = (
    "No fixed number of sick days on file — Taiwan employees don't actually get unlimited "
    "PTO (that premise is incorrect), and sick leave for Taiwan is governed by applicable "
    "local law and Acme policy rather than a set day count in the handbooks I can search.\n\n"
    "Taiwan employees get 12 days of PTO per year under the APAC Benefits Handbook, which "
    "takes precedence over the global PTO figure specifically for PTO. Sick leave isn't "
    "covered by that regional precedence rule, and the global handbook just defers to local "
    "law for the actual number of sick days, so I don't have a specific figure to give you "
    "— (APAC Benefits Handbook, Regional Benefits / Conflicts and Precedence; Acme Employee "
    "Handbook 2026, Section 4.4)"
)

# A plausible WRONG response: correctly corrects PTO to 12, but hallucinates that sick days
# also equal 12 instead of declining to answer. A single "12" marker cannot tell these two
# responses apart — that's exactly what a compound assertion is for.
HALLUCINATED_RESPONSE = (
    "12 days of sick leave per year. Taiwan employees get 12 days of PTO (not unlimited, "
    "correcting your premise), and sick leave follows the same 12-day allotment."
)


def _result(text: str, grounded: bool = True, cited_chunks=None) -> VerifiedAnswer:
    return VerifiedAnswer(text=text, grounded=grounded, cited_chunks=cited_chunks or [])


def test_single_string_expected_still_works():
    assert matches("12", _result("the figure is 12 days"))
    assert not matches("12", _result("the figure is 15 days"))


def test_unknown_marker_class_still_works():
    assert matches("unknown", _result("I don't know the answer"))
    assert not matches("unknown", _result("the figure is 12 days"))


def test_no_fixed_number_phrasing_is_recognized_as_unknown():
    assert matches("unknown", _result("There is no fixed number of sick days on file."))


def test_no_specific_number_phrasing_is_recognized_as_unknown():
    assert matches("unknown", _result("No specific number of weeks/days is on file for maternity leave in Japan."))


def test_compound_list_requires_every_condition():
    assert matches(["12", "unknown"], _result("12 days, but I don't know the rest"))
    assert not matches(["12", "unknown"], _result("12 days, all figures confirmed"))
    assert not matches(["12", "unknown"], _result("I don't know"))


def test_real_correct_response_requires_both_pto_correction_and_sick_days_decline():
    assert matches(["12", "unknown"], _result(REAL_CORRECT_RESPONSE))


def test_hallucinated_sick_days_figure_is_correctly_rejected():
    assert not matches(["12", "unknown"], _result(HALLUCINATED_RESPONSE))


def test_numeric_marker_does_not_match_inside_a_larger_dollar_figure():
    assert not matches("50", _result("The gym reimbursement is $500 per month."))
    assert not matches("$50", _result("The gym reimbursement is $500 per month."))


def test_numeric_marker_does_not_match_inside_a_larger_day_count():
    assert not matches("12", _result("Employees get 120 days of leave."))


def test_numeric_marker_does_not_match_inside_a_year():
    assert not matches("14", _result("As of 2014, the policy was different."))


def test_comma_separated_marker_does_not_match_inside_a_larger_figure():
    assert not matches("1,000", _result("The annual budget is $21,000 per year."))


def test_numeric_marker_still_matches_its_own_whole_number():
    assert matches("50", _result("The gym reimbursement is $50 per month."))
    assert matches("$50", _result("The gym reimbursement is $50 per month."))
    assert matches("12", _result("Employees get 12 days of leave."))
    assert matches("14", _result("As of 2014, the policy was 14 days."))
    assert matches("1,000", _result("The annual budget is $1,000 per year."))


def test_numeric_marker_matches_at_string_boundaries():
    assert matches("12", _result("12 days per year."))
    assert matches("12", _result("The allowance is 12"))


def test_numeric_marker_does_not_match_an_ungrounded_rejection_even_if_the_digits_appear():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: ...the global $50/month rate winning over the regional "
        "$30/month rate... SUPPORTED"
    )
    assert not matches("$50", _result(rejection_text, grounded=False))


def test_hedge_marker_does_not_match_an_ungrounded_rejection():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: it's ambiguous which country applies here..."
    )
    assert not matches("hedge", _result(rejection_text, grounded=False))


def test_numeric_and_hedge_markers_still_match_when_grounded():
    assert matches("$50", _result("The gym reimbursement is $50 per month."))
    assert matches("hedge", _result("Which specific country are you in?"))


def test_word_to_number_handles_small_and_compound_phrases():
    assert _word_to_number("fifty") == "50"
    assert _word_to_number("one thousand") == "1000"
    assert _word_to_number("twelve") == "12"
    assert _word_to_number("not a number") is None


def test_expectation_numeric_matches_plain_digit():
    assert matches(Expectation(numeric="50"), _result("The gym reimbursement is $50 per month."))


def test_expectation_numeric_matches_currency_formatting_variant():
    assert matches(Expectation(numeric="$1,000"), _result("The annual budget is $1000 per year."))


def test_expectation_numeric_matches_spelled_out_number():
    assert matches(Expectation(numeric="12"), _result("Employees get twelve days of PTO per year."))


def test_expectation_numeric_does_not_match_wrong_figure():
    assert not matches(Expectation(numeric="50"), _result("The gym reimbursement is $30 per month."))


def test_expectation_numeric_does_not_match_inside_a_larger_number():
    assert not matches(Expectation(numeric="50"), _result("The gym reimbursement is $500 per month."))


def test_expectation_numeric_requires_grounded():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: ...the global $50/month rate..."
    )
    assert not matches(Expectation(numeric="50"), _result(rejection_text, grounded=False))


def test_expectation_unknown_requires_grounded_and_explicit_wording():
    assert matches(Expectation(unknown=True), _result("There is no fixed number of sick days on file."))
    assert not matches(Expectation(unknown=True), _result("12 days per year."))


def test_expectation_unknown_does_not_count_an_ungrounded_rejection():
    # The key gap this splits from today's plain "unknown" marker (which is satisfied by
    # `not grounded` alone): a verifier rejection must not silently pass as if the system had
    # correctly determined the answer is unknown.
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: the draft's figure isn't stated in the excerpts."
    )
    assert not matches(Expectation(unknown=True), _result(rejection_text, grounded=False))


def test_expectation_hedge_requires_grounded_and_hedge_wording():
    assert matches(Expectation(hedge=True), _result("Which specific country are you in?"))
    assert not matches(Expectation(hedge=True), _result("15 days per year."))


def test_expectation_rejected_requires_grounded_false():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: the draft wrongly claims $30 applies."
    )
    assert matches(Expectation(rejected=True), _result(rejection_text, grounded=False))
    assert not matches(Expectation(rejected=True), _result("15 days per year."))


_GLOBAL_DOC = DocMeta(file="g.docx", doc_type="global_handbook", jurisdictions=None, version_year=2026, display_name="Acme Employee Handbook 2026")
_APAC_DOC = DocMeta(file="a.docx", doc_type="regional_handbook", jurisdictions=["China", "Japan", "Taiwan"], version_year=None, display_name="APAC Benefits Handbook")
_GLOBAL_CHUNK = Chunk(text="Standard PTO is 15 days.", section_title="4.2 PTO", doc=_GLOBAL_DOC)
_APAC_CHUNK = Chunk(text="Regional PTO is 12 days.", section_title="Regional Benefits", doc=_APAC_DOC)


def test_expectation_doc_type_matches_any_cited_chunk():
    result = _result("12 days per year.", cited_chunks=[_GLOBAL_CHUNK, _APAC_CHUNK])
    assert matches(Expectation(doc_type="regional_handbook"), result)


def test_expectation_doc_type_fails_when_no_cited_chunk_matches():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    assert not matches(Expectation(doc_type="regional_handbook"), result)


def test_expectation_version_year_matches_any_cited_chunk():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    assert matches(Expectation(version_year=2026), result)


def test_expectation_version_year_none_does_not_match_a_specific_year():
    # The evergreen APAC handbook's version_year=None must not satisfy a specific-year
    # expectation — a plain equality check on real chunk metadata, not the
    # VectorIndex.search() "None matches any year filter" retrieval-time special case.
    result = _result("12 days per year.", cited_chunks=[_APAC_CHUNK])
    assert not matches(Expectation(version_year=2026), result)


def test_expectation_doc_type_and_version_year_combine_with_numeric():
    result = _result("15 days per year.", cited_chunks=[_GLOBAL_CHUNK])
    assert matches(Expectation(numeric="15", doc_type="global_handbook", version_year=2026), result)
    assert not matches(Expectation(numeric="15", doc_type="global_handbook", version_year=2025), result)


def test_expectation_required_and_forbidden_together():
    text = "12 days per year. Taiwan is covered by the APAC regional handbook."
    assert matches(Expectation(required=["12", "Taiwan"], forbidden=["Singapore"]), _result(text))


def test_expectation_required_fails_when_a_term_is_missing():
    text = "12 days per year."
    assert not matches(Expectation(required=["12", "Taiwan"]), _result(text))


def test_expectation_required_uses_numeric_boundary_matching():
    assert not matches(Expectation(required=["50"]), _result("The gym reimbursement is $500 per month."))


def test_expectation_forbidden_fails_when_term_present():
    text = "The APAC handbook covers China, Japan, Taiwan, and Singapore."
    assert not matches(Expectation(forbidden=["Singapore"]), _result(text))


def test_expectation_forbidden_is_skipped_on_an_ungrounded_rejection():
    # Same false-positive-risk rationale as the existing numeric/hedge grounded-gating: a
    # rejected draft's dumped verifier reasoning can echo almost any text from the source
    # excerpts while explaining why something is wrong — that's not the system claiming it.
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: the draft wrongly named Singapore as covered."
    )
    assert matches(Expectation(forbidden=["Singapore"]), _result(rejection_text, grounded=False))
