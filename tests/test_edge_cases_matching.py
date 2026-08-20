from __future__ import annotations

from evals.edge_cases import _matches

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
    assert _matches("12", "the figure is 12 days", grounded=True)
    assert not _matches("12", "the figure is 15 days", grounded=True)


def test_unknown_marker_class_still_works():
    assert _matches("unknown", "I don't know the answer", grounded=True)
    assert not _matches("unknown", "the figure is 12 days", grounded=True)


def test_no_fixed_number_phrasing_is_recognized_as_unknown():
    # The exact phrasing the real live response used, which the marker list didn't catch
    # before this fix.
    assert _matches("unknown", "There is no fixed number of sick days on file.", grounded=True)


def test_compound_list_requires_every_condition():
    assert _matches(["12", "unknown"], "12 days, but I don't know the rest", grounded=True)
    assert not _matches(["12", "unknown"], "12 days, all figures confirmed", grounded=True)
    assert not _matches(["12", "unknown"], "I don't know", grounded=True)


def test_real_correct_response_requires_both_pto_correction_and_sick_days_decline():
    # This is the actual live response that exposed the bug: the OLD single-marker test
    # ("12") passed this response for the wrong reason — "12" appears only because the PTO
    # premise correction happens to restate it, not because anything verified the sick-days
    # portion was handled correctly.
    assert _matches(["12", "unknown"], REAL_CORRECT_RESPONSE, grounded=True)


def test_hallucinated_sick_days_figure_is_correctly_rejected():
    # The exact false-positive risk the old single-marker test couldn't catch: a draft that
    # wrongly claims sick days = 12 (instead of declining) still contains "12", but must NOT
    # satisfy the compound assertion, since it never declines/hedges on sick days.
    assert not _matches(["12", "unknown"], HALLUCINATED_RESPONSE, grounded=True)
