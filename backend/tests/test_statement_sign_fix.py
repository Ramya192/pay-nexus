"""statement_extraction._fix_signs_from_balances and the new rule keywords --
pure Python, no LLM."""

from categorization.rules import apply_rules
from statement_extraction import _fix_signs_from_balances


def _row(amount, balance):
    return {"date": "2025-09-11", "description": "x", "amount": amount, "balance": balance}


class TestFixSignsFromBalances:
    def test_deposit_misread_as_outflow_is_corrected(self):
        rows = [_row(-100, 1000), _row(-475000, 476000)]  # balance rose by 475000
        _fix_signs_from_balances(rows)
        assert rows[1]["amount"] == 475000

    def test_withdrawal_misread_as_deposit_is_corrected(self):
        rows = [_row(-100, 1000), _row(500, 500)]  # balance fell by 500
        _fix_signs_from_balances(rows)
        assert rows[1]["amount"] == -500

    def test_newest_first_statement(self):
        # Listed newest first: the first row's amount explains the drop to the next row.
        rows = [_row(300, 700), _row(-50, 1000)]  # 1000 -> 700 means row 0 was -300
        _fix_signs_from_balances(rows)
        assert rows[0]["amount"] == -300

    def test_rows_without_balance_or_that_dont_reconcile_are_left_alone(self):
        rows = [_row(-100, None), _row(-200, 5000), _row(-999, 9999)]
        _fix_signs_from_balances(rows)
        assert [r["amount"] for r in rows] == [-100, -200, -999]


class TestDefaultFallback:
    def test_unplaceable_rows_default_to_income_for_credits_and_other_for_debits(self, monkeypatch):
        from datetime import date

        import categorization.categorize as categorize_module
        from models import Transaction

        monkeypatch.setattr(categorize_module, "_categorize_batch", lambda descriptions: ["Uncategorized"] * len(descriptions))
        txns = [
            Transaction(transaction_id="a", date=date(2026, 7, 1), description="MYSTERY IN", amount=500, source_account="X"),
            Transaction(transaction_id="b", date=date(2026, 7, 2), description="MYSTERY OUT", amount=-500, source_account="X"),
        ]
        categorize_module.categorize_transactions(txns, [])
        assert (txns[0].category, txns[0].category_source) == ("Income", "default")
        assert (txns[1].category, txns[1].category_source) == ("Other", "default")


class TestNewRules:
    def test_categories(self):
        assert apply_rules("UPI-CRED CRED.CLUB@AXISB") == "Credit Card Payment"
        assert apply_rules("EMI 112328952 CHQ S1123") == "Loans & EMI"
        assert apply_rules("IMPS-525407399659-SOMEONE") == "Transfers"
        assert apply_rules("IMPS-5255-ZERODHA BROKING") == "Investments"  # specific beats generic

    def test_whole_word_keywords_dont_overmatch(self):
        assert apply_rules("INSURANCE PREMIUM") is None
        assert apply_rules("CREDITOR REFUND") is None


class TestPayslipOrdering:
    """Snapshots uploaded out of order (2026 files before 2025) must still
    give first=oldest, last=newest and 'latest payslip'=newest."""

    def _snaps(self):
        months = ["2026-01", "2026-02", "2025-11", "2025-12"]  # upload order, not chronological
        return [{"month": m, "basic": 1000 + i, "tds": 100 * (i + 1)} for i, m in enumerate(months)]

    def test_trends_use_chronological_first_and_last(self):
        from payslip_trends import compute_trends

        tds = next(t for t in compute_trends(self._snaps()) if t.field == "tds")
        assert (tds.first_month, tds.last_month) == ("2025-11", "2026-02")

    def test_fallback_payslip_is_the_newest_month(self):
        from payslip_trends import resolve_effective_payslip

        effective, used_fallback = resolve_effective_payslip({}, self._snaps())
        assert used_fallback and effective["month"] == "2026-02"


class TestLatestMonthChange:
    def _snaps(self):
        # Deliberately out of order; latest = 2026-06, previous = 2026-05.
        return [
            {"month": "2026-06", "basic": 1000, "hra": 400, "tds": 300, "bonus": 0},
            {"month": "2026-04", "basic": 1000, "hra": 400, "tds": 100, "bonus": 0},
            {"month": "2026-05", "basic": 1000, "hra": 400, "tds": 100, "bonus": 0},
        ]

    def test_compares_newest_month_with_the_one_before_it(self):
        from payslip_trends import compute_latest_change

        prev_month, latest_month, rows = compute_latest_change(self._snaps())
        assert (prev_month, latest_month) == ("2026-05", "2026-06")
        by_label = {r.label: r for r in rows}
        assert by_label["TDS"].delta == 200
        assert by_label["Net pay (take-home)"].delta == -200
        assert by_label["Basic"].delta == 0

    def test_table_and_prompt_text_agree(self):
        from payslip_trends import format_latest_change_for_prompt, latest_change_table

        table = latest_change_table(self._snaps())
        assert table["headers"][1:3] == ["2026-05", "2026-06"]
        assert table["rows"][0][0] == "Net pay (take-home)" and "200" in table["rows"][0][3]
        assert "down ₹200" in format_latest_change_for_prompt(self._snaps())

    def test_none_with_fewer_than_two_snapshots(self):
        from payslip_trends import compute_latest_change

        assert compute_latest_change([{"month": "2026-06", "basic": 1}]) is None
