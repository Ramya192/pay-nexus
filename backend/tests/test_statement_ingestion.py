"""Unit tests for ingestion/normalize.py and ingestion/csv_parser.py — pure
Python row parsing, no LLM, no network. Covers the column-alias matching
and the signed-amount vs. debit/credit-column cases expense-simplifier's
original ingestion/normalize.py handled, plus date-format flexibility
(Indian DD/MM/YYYY exports, not just ISO).
"""

import pytest

from ingestion.csv_parser import parse_csv_text
from ingestion.normalize import rows_to_transactions
from models import make_transaction_id


class TestRowsToTransactions:
    def test_single_signed_amount_column(self):
        rows = [{"Date": "2026-07-01", "Description": "SWIGGY", "Amount": "-500"}]
        transactions, skipped = rows_to_transactions(rows, "HDFC Checking")
        assert skipped == []
        assert len(transactions) == 1
        assert transactions[0].amount == -500
        assert transactions[0].date.isoformat() == "2026-07-01"

    def test_separate_debit_credit_columns(self):
        rows = [
            {"Date": "2026-07-01", "Narration": "SALARY", "Debit": "", "Credit": "75000"},
            {"Date": "2026-07-02", "Narration": "RENT PAYMENT", "Debit": "18000", "Credit": ""},
        ]
        transactions, skipped = rows_to_transactions(rows, "HDFC Checking")
        assert skipped == []
        assert transactions[0].amount == 75000
        assert transactions[1].amount == -18000

    def test_ddmmyyyy_date_parsed(self):
        rows = [{"Date": "15/07/2026", "Description": "SWIGGY", "Amount": "-500"}]
        transactions, _ = rows_to_transactions(rows, "HDFC Checking")
        assert transactions[0].date.isoformat() == "2026-07-15"

    def test_row_missing_required_field_is_skipped_not_dropped_silently(self):
        rows = [
            {"Date": "2026-07-01", "Description": "SWIGGY", "Amount": "-500"},
            {"Date": "not a date", "Description": "BAD ROW", "Amount": "-100"},
        ]
        transactions, skipped = rows_to_transactions(rows, "HDFC Checking")
        assert len(transactions) == 1
        assert len(skipped) == 1

    def test_unrecognized_headers_raises(self):
        rows = [{"Col A": "x", "Col B": "y"}]
        with pytest.raises(ValueError):
            rows_to_transactions(rows, "HDFC Checking")

    def test_empty_rows_returns_empty(self):
        assert rows_to_transactions([], "HDFC Checking") == ([], [])

    def test_identical_duplicate_rows_get_distinct_ids(self):
        # Two genuinely separate transactions that happen to share date,
        # description, amount, and account (e.g. two same-day ₹500 Netflix
        # charges) must not collide onto one transaction_id — that would
        # make StatementList.tsx's handleCategoryChange() silently apply a
        # category correction meant for one row to both.
        rows = [
            {"Date": "2026-07-10", "Description": "NETFLIX", "Amount": "-500"},
            {"Date": "2026-07-10", "Description": "NETFLIX", "Amount": "-500"},
        ]
        transactions, skipped = rows_to_transactions(rows, "HDFC Checking")
        assert skipped == []
        assert len(transactions) == 2
        assert transactions[0].transaction_id != transactions[1].transaction_id

    def test_identical_duplicate_rows_still_deterministic_across_reparse(self):
        # Re-uploading the exact same file must reproduce the exact same
        # set of IDs, not fresh random ones each time.
        rows = [
            {"Date": "2026-07-10", "Description": "NETFLIX", "Amount": "-500"},
            {"Date": "2026-07-10", "Description": "NETFLIX", "Amount": "-500"},
        ]
        first, _ = rows_to_transactions(rows, "HDFC Checking")
        second, _ = rows_to_transactions(rows, "HDFC Checking")
        assert [t.transaction_id for t in first] == [t.transaction_id for t in second]


class TestParseCsvText:
    def test_parses_csv_text_end_to_end(self):
        text = "Date,Description,Amount\n2026-07-01,SWIGGY,-500\n2026-07-02,SALARY,75000\n"
        transactions, skipped = parse_csv_text(text, "HDFC Checking")
        assert skipped == []
        assert len(transactions) == 2


class TestMakeTransactionId:
    def test_deterministic_across_calls(self):
        from datetime import date

        id1 = make_transaction_id(date(2026, 7, 1), "SWIGGY", -500.0, "HDFC Checking")
        id2 = make_transaction_id(date(2026, 7, 1), "SWIGGY", -500.0, "HDFC Checking")
        assert id1 == id2

    def test_different_amount_produces_different_id(self):
        from datetime import date

        id1 = make_transaction_id(date(2026, 7, 1), "SWIGGY", -500.0, "HDFC Checking")
        id2 = make_transaction_id(date(2026, 7, 1), "SWIGGY", -501.0, "HDFC Checking")
        assert id1 != id2
