from __future__ import annotations

from evals.matching import matches
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
