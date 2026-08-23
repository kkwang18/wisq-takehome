from __future__ import annotations

from evals.matching import matches

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


def test_single_string_expected_still_works():
    assert matches("12", "the figure is 12 days", grounded=True)
    assert not matches("12", "the figure is 15 days", grounded=True)


def test_unknown_marker_class_still_works():
    assert matches("unknown", "I don't know the answer", grounded=True)
    assert not matches("unknown", "the figure is 12 days", grounded=True)


def test_no_fixed_number_phrasing_is_recognized_as_unknown():
    # The exact phrasing the real live response used, which the marker list didn't catch
    # before this fix.
    assert matches("unknown", "There is no fixed number of sick days on file.", grounded=True)


def test_no_specific_number_phrasing_is_recognized_as_unknown():
    # Live edge_cases.py run: "No specific number of weeks/days is on file for maternity
    # leave in Japan." is a correct, properly-hedged answer, but didn't match any existing
    # marker — same recurring pattern as "no fixed number" above, different wording.
    assert matches("unknown", "No specific number of weeks/days is on file for maternity leave in Japan.", grounded=True)


def test_compound_list_requires_every_condition():
    assert matches(["12", "unknown"], "12 days, but I don't know the rest", grounded=True)
    assert not matches(["12", "unknown"], "12 days, all figures confirmed", grounded=True)
    assert not matches(["12", "unknown"], "I don't know", grounded=True)


def test_real_correct_response_requires_both_pto_correction_and_sick_days_decline():
    # This is the actual live response that exposed the bug: the OLD single-marker test
    # ("12") passed this response for the wrong reason — "12" appears only because the PTO
    # premise correction happens to restate it, not because anything verified the sick-days
    # portion was handled correctly.
    assert matches(["12", "unknown"], REAL_CORRECT_RESPONSE, grounded=True)


def test_hallucinated_sick_days_figure_is_correctly_rejected():
    # The exact false-positive risk the old single-marker test couldn't catch: a draft that
    # wrongly claims sick days = 12 (instead of declining) still contains "12", but must NOT
    # satisfy the compound assertion, since it never declines/hedges on sick days.
    assert not matches(["12", "unknown"], HALLUCINATED_RESPONSE, grounded=True)


# Numeric markers previously matched as a bare substring (`expected in result_text`), so a
# hallucinated figure could silently pass an eval expecting a different one, as long as the
# hallucinated number happened to contain the expected digits somewhere inside it. Confirmed
# live against the real matcher before this fix: "50" matched "$500", "12" matched "120",
# "14" matched "2014", and "1,000" matched "$21,000" — all four wrongly returned True.
def test_numeric_marker_does_not_match_inside_a_larger_dollar_figure():
    assert not matches("50", "The gym reimbursement is $500 per month.", grounded=True)
    assert not matches("$50", "The gym reimbursement is $500 per month.", grounded=True)


def test_numeric_marker_does_not_match_inside_a_larger_day_count():
    assert not matches("12", "Employees get 120 days of leave.", grounded=True)


def test_numeric_marker_does_not_match_inside_a_year():
    assert not matches("14", "As of 2014, the policy was different.", grounded=True)


def test_comma_separated_marker_does_not_match_inside_a_larger_figure():
    assert not matches("1,000", "The annual budget is $21,000 per year.", grounded=True)


def test_numeric_marker_still_matches_its_own_whole_number():
    assert matches("50", "The gym reimbursement is $50 per month.", grounded=True)
    assert matches("$50", "The gym reimbursement is $50 per month.", grounded=True)
    assert matches("12", "Employees get 12 days of leave.", grounded=True)
    assert matches("14", "As of 2014, the policy was 14 days.", grounded=True)
    assert matches("1,000", "The annual budget is $1,000 per year.", grounded=True)


def test_numeric_marker_matches_at_string_boundaries():
    # No character at all on one side (start/end of string) must still count as a boundary.
    assert matches("12", "12 days per year.", grounded=True)
    assert matches("12", "The allowance is 12", grounded=True)


# A live verify_answer rejection (garbled fallback text) once contained the expected "$50"
# marker by pure substring accident, so eval.py "passed" a query that was actually ungrounded
# — see docs/backlog/2026-08-22-verify-answer-prefix-parsing-false-rejection.md. Numeric and
# hedge markers must require grounded=True: a rejected answer should never satisfy an
# expectation that implies the system actually confirmed the figure/ambiguity.
def test_numeric_marker_does_not_match_an_ungrounded_rejection_even_if_the_digits_appear():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: ...the global $50/month rate winning over the regional "
        "$30/month rate... SUPPORTED"
    )
    assert not matches("$50", rejection_text, grounded=False)


def test_hedge_marker_does_not_match_an_ungrounded_rejection():
    rejection_text = (
        "I can't confirm this from the retrieved policy text alone — the verification check "
        "flagged: UNSUPPORTED: it's ambiguous which country applies here..."
    )
    assert not matches("hedge", rejection_text, grounded=False)


def test_numeric_and_hedge_markers_still_match_when_grounded():
    assert matches("$50", "The gym reimbursement is $50 per month.", grounded=True)
    assert matches("hedge", "Which specific country are you in?", grounded=True)
