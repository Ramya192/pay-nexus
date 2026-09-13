"""
Unit tests for tax_calculations.py — 80C/80D/24(b) deduction-gap math. Pure
functions, no network, no DB.

Most of these figures were hand-verified against the real slab/section
rules earlier in this build (see README.md's dated fix entries) before
ever being wired into an agent prompt — this file is what turns that
one-off hand-verification into something that keeps checking itself.
"""

from tax_calculations import (
    SECTION_24B_LIMIT,
    SECTION_80C_LIMIT,
    SECTION_80D_LIMIT_SENIOR,
    SECTION_80D_LIMIT_STANDARD,
    compute_24b,
    compute_80c,
    compute_80d,
    compute_all_gaps,
    financial_profile_table,
    format_financial_profile_for_prompt,
    format_gaps_for_prompt,
    gaps_table,
)


class TestCompute80C:
    def test_basic_sum_no_pf(self):
        gap = compute_80c({"elssMutualFunds": 50_000, "lifeInsurancePremium": 35_853, "homeLoanPrincipalPaid": 20_000})
        assert gap.used == 105_853
        assert gap.remaining == SECTION_80C_LIMIT - 105_853
        assert gap.note is None  # no payslip_data given — no PF note

    def test_pf_annualized_from_payslip_data(self):
        """The exact mechanism behind the "two agents disagreed on the same
        total" bug: 80C includes the payslip's employee PF, annualized
        (monthly x 12) — whichever agent's payslip_data this is called
        with determines the total, which is why resolve_effective_payslip
        (tested separately) had to become the one shared source of truth."""
        gap = compute_80c({"lifeInsurancePremium": 35_853}, {"pfEmployee": 5_040})
        assert gap.used == 35_853 + 5_040 * 12  # 96,333 — the exact figure from a real reported bug
        assert gap.note is not None and "annualized" in gap.note

    def test_no_pf_when_payslip_data_missing_pf_key(self):
        gap = compute_80c({"lifeInsurancePremium": 35_853}, {"month": "2026-03"})
        assert gap.used == 35_853
        assert gap.note is None

    def test_caps_at_limit(self):
        gap = compute_80c({"elssMutualFunds": 200_000})
        assert gap.used == SECTION_80C_LIMIT
        assert gap.remaining == 0

    def test_negative_or_missing_fields_treated_as_zero(self):
        gap = compute_80c({})
        assert gap.used == 0
        assert gap.remaining == SECTION_80C_LIMIT


class TestCompute80D:
    def test_standard_cap(self):
        gap = compute_80d({"healthInsurancePremium": 80_000})
        assert gap.limit == SECTION_80D_LIMIT_STANDARD
        assert gap.used == SECTION_80D_LIMIT_STANDARD  # capped
        assert gap.remaining == 0

    def test_senior_citizen_raises_cap(self):
        gap = compute_80d({"healthInsurancePremium": 80_000, "healthInsuranceForSeniorCitizen": True})
        assert gap.limit == SECTION_80D_LIMIT_SENIOR
        assert gap.used == SECTION_80D_LIMIT_SENIOR
        assert gap.remaining == 0

    def test_under_cap_not_truncated(self):
        gap = compute_80d({"healthInsurancePremium": 10_000})
        assert gap.used == 10_000
        assert gap.remaining == SECTION_80D_LIMIT_STANDARD - 10_000


class TestCompute24B:
    def test_under_and_over_cap(self):
        assert compute_24b({"homeLoanInterestPaid": 50_000}).used == 50_000
        capped = compute_24b({"homeLoanInterestPaid": 500_000})
        assert capped.used == SECTION_24B_LIMIT
        assert capped.remaining == 0

    def test_no_home_loan(self):
        gap = compute_24b({})
        assert gap.used == 0
        assert gap.remaining == SECTION_24B_LIMIT


class TestComputeAllGaps:
    def test_returns_three_sections_in_order(self):
        gaps = compute_all_gaps({"lifeInsurancePremium": 35_853, "healthInsurancePremium": 80_000}, {})
        assert [g.section for g in gaps] == ["80C", "80D", "24(b)"]

    def test_reproduces_the_reported_regime_contradiction_scenario(self):
        """The exact profile from the user's screenshot that first exposed
        the deduction-total inconsistency bug — total used should be
        ₹1,46,333 when a payslip with PF is in play, matching the figure
        both agents were expected to (and, after the fix, do) agree on."""
        gaps = compute_all_gaps(
            {"lifeInsurancePremium": 35_853, "healthInsurancePremium": 80_000, "healthInsuranceForSeniorCitizen": True},
            {"pfEmployee": 9_207},
        )
        total = sum(g.used for g in gaps)
        assert total == 35_853 + 9_207 * 12 + 50_000  # 146,337 — matches the hand-verified figure from that session


class TestFormatting:
    def test_format_financial_profile_lists_declared_fields_only(self):
        text = format_financial_profile_for_prompt({"lifeInsurancePremium": 35_853, "elssMutualFunds": 0})
        assert "Life insurance premium: ₹35,853" in text
        assert "ELSS" not in text  # zero/falsy fields are omitted, not shown as ₹0

    def test_format_financial_profile_empty_returns_empty_string(self):
        assert format_financial_profile_for_prompt({}) == ""

    def test_gaps_table_shape(self):
        table = gaps_table(compute_all_gaps({"lifeInsurancePremium": 35_853}, {}))
        assert table["headers"] == ["Section", "Used", "Limit", "Remaining"]
        assert len(table["rows"]) == 3

    def test_financial_profile_table_none_when_empty(self):
        assert financial_profile_table({}) is None

    def test_format_gaps_for_prompt_includes_note(self):
        gaps = [compute_80d({"healthInsurancePremium": 80_000})]
        text = format_gaps_for_prompt(gaps)
        assert "parents" in text  # the 80D note about the separate parents' bucket
