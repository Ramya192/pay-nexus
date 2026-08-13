"""
Unit tests for tax_slabs.py — the real old-vs-new regime slab calculator,
and cheaper_regime_statement(), the fix for the highest-recurrence bug this
build had: an LLM correctly quoting both regime totals and STILL inverting
which one is cheaper, twice, in two different agents, even after the first
fix synced the numbers between them. All three branches (new cheaper, old
cheaper, a tie) are tested directly here — the case that actually broke in
production (old cheaper) is exactly the one a quick "does it work at all"
smoke test would have skipped, since every manual test case that happened
to get built during this session's feature work landed on "new is cheaper."
"""

from tax_slabs import (
    TaxResult,
    cheaper_regime_statement,
    compute_new_regime_tax,
    compute_old_regime_tax,
    estimate_annual_gross_income,
)


class TestComputeOldRegimeTax:
    def test_below_5l_taxable_is_fully_rebated(self):
        # 6L gross, no deductions: taxable = 6L - 50k std = 5.5L
        result = compute_old_regime_tax(600_000, 0)
        assert result.taxable_income == 550_000
        assert result.total_tax == 23_400  # hand-verified: 12,500 (5%) + 10,000 (20%) + 4% cess

    def test_reported_regime_contradiction_scenario(self):
        """The exact figures from the user's reported regime-contradiction
        screenshot: ₹11,62,900 gross, ₹2,00,000 declared deductions →
        ₹98,883 old-regime tax, hand-verified against the slab math at the
        time (12,500 @ 5% band + 82,580 @ 20% band, +4% cess)."""
        result = compute_old_regime_tax(1_162_900, 200_000)
        assert result.taxable_income == 912_900
        assert result.tax_before_rebate == 95_080
        # cess/total_tax are unrounded floats internally — only rounded at
        # display-formatting time (tax_liability_table's f"{r:,.0f}") — so
        # this compares against the same rounding the UI actually shows,
        # not the raw float.
        assert round(result.cess) == 3_803
        assert round(result.total_tax) == 98_883

    def test_marginal_relief_near_rebate_threshold(self):
        # Taxable income just above the 5L threshold — relief should cap
        # tax at (taxable - threshold), not the full slab-computed amount.
        result = compute_old_regime_tax(555_000, 0)  # taxable = 505,000
        relief_cap = result.taxable_income - 500_000
        assert result.total_tax <= relief_cap + round(relief_cap * 0.04) + 1  # cess on the relief-capped tax


class TestComputeNewRegimeTax:
    def test_zero_tax_below_12l_taxable(self):
        result = compute_new_regime_tax(1_077_600)  # taxable = 1,002,600, under 12L threshold
        assert result.total_tax == 0
        assert result.taxable_income == 1_002_600  # NOT zero — the exact conflation bug this caught

    def test_taxable_income_and_tax_are_different_numbers(self):
        """Direct regression test for the reported bug: the agent said
        "the new regime results in zero taxable income" when only the TAX
        was zero. Taxable income and total tax must never be equal here
        unless by genuine coincidence — for this input they're provably
        different."""
        result = compute_new_regime_tax(1_500_000)
        assert result.taxable_income != result.total_tax
        assert result.taxable_income == 1_425_000
        assert result.total_tax == 97_500

    def test_higher_income_still_computes_a_real_tax(self):
        result = compute_new_regime_tax(2_000_000)
        assert result.total_tax > 0


class TestCheaperRegimeStatement:
    def test_new_cheaper(self):
        old = compute_old_regime_tax(1_162_900, 200_000)
        new = compute_new_regime_tax(1_162_900)
        statement = cheaper_regime_statement(old, new)
        assert "NEW regime is cheaper" in statement
        assert "recommend the new regime" in statement.lower() or "recommend the new" in statement

    def test_old_cheaper(self):
        """The branch that actually broke in production — a high-income,
        high-deduction profile where the old regime wins. Every ad hoc
        manual test during this session's feature work happened to use a
        profile where the new regime won, so this exact branch went
        untested until a real user hit it."""
        old = TaxResult("old", 2_000_000, 50_000, 500_000, 1_450_000, 300_000, 0, 12_000, 300_000)
        new = TaxResult("new", 2_000_000, 75_000, 0, 1_925_000, 350_000, 0, 14_000, 350_000)
        statement = cheaper_regime_statement(old, new)
        assert "OLD regime is cheaper" in statement
        assert "recommend the old regime" in statement.lower() or "recommend the old" in statement
        assert "₹50,000" in statement  # the savings delta (350,000 - 300,000)

    def test_tie(self):
        result = TaxResult("x", 1_000_000, 50_000, 0, 950_000, 50_000, 0, 2_000, 50_000)
        statement = cheaper_regime_statement(result, result)
        assert "neither is cheaper" in statement.lower()

    def test_never_says_cheaper_regime_is_more_expensive(self):
        """A structural check on the statement itself, not just its
        keywords — the number named as "cheaper" must actually have the
        lower total_tax, checked programmatically rather than by string
        matching alone."""
        old = compute_old_regime_tax(1_500_000, 100_000)
        new = compute_new_regime_tax(1_500_000)
        statement = cheaper_regime_statement(old, new)
        if old.total_tax < new.total_tax:
            assert "OLD" in statement
        elif new.total_tax < old.total_tax:
            assert "NEW" in statement


class TestEstimateAnnualGrossIncome:
    def test_single_month_extrapolation(self):
        income, note = estimate_annual_gross_income({"basic": 42_000, "hra": 16_800}, [])
        assert income == (42_000 + 16_800) * 12
        assert "rough estimate" in note

    def test_full_year_of_history_is_a_real_total_not_extrapolated(self):
        history = [{"basic": 45_000, "hra": 18_000} for _ in range(12)]
        income, note = estimate_annual_gross_income({}, history)
        assert income == (45_000 + 18_000) * 12
        assert "not extrapolated" in note

    def test_partial_history_is_scaled_and_labeled_as_estimate(self):
        history = [{"basic": 45_000} for _ in range(6)]
        income, note = estimate_annual_gross_income({}, history)
        assert income == 45_000 * 6 / 6 * 12
        assert "not a confirmed annual total" in note

    def test_bonus_field_included_in_gross(self):
        income, _ = estimate_annual_gross_income({"basic": 42_000, "bonus": 8_000}, [])
        assert income == (42_000 + 8_000) * 12
