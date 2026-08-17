"""Pure-Python tests for aa_transaction_mapping.py — no network, no Setu
sandbox involved. Fixtures below intentionally mirror the FI data shape
confirmed from Setu's docs (see aa_transaction_mapping.py's module
docstring): `{"account": {"transactions": {"transaction": [...]}}}`.
"""

from aa_transaction_mapping import _description_for, map_fi_data_to_transactions


def _fi_data(transactions) -> dict:
    return {"account": {"maskedAccNumber": "XXXX1234", "transactions": {"transaction": transactions}}}


class TestSignHandling:
    def test_credit_is_positive_amount(self):
        fi_data = _fi_data(
            [{"amount": "5000", "type": "CREDIT", "mode": "UPI", "transactionTimestamp": "2026-07-05T10:00:00+00:00"}]
        )
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert skipped == []
        assert len(transactions) == 1
        assert transactions[0].amount == 5000.0

    def test_debit_is_negative_amount(self):
        fi_data = _fi_data(
            [{"amount": "1200", "type": "DEBIT", "mode": "UPI", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert skipped == []
        assert transactions[0].amount == -1200.0

    def test_type_is_case_insensitive(self):
        fi_data = _fi_data(
            [{"amount": "100", "type": "credit", "mode": "UPI", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert skipped == []
        assert transactions[0].amount == 100.0


class TestDescriptionFallback:
    def test_prefers_narration_over_mode_type(self):
        fi_data = _fi_data(
            [
                {
                    "amount": "100",
                    "type": "DEBIT",
                    "mode": "UPI",
                    "narration": "Swiggy order #123",
                    "transactionTimestamp": "2026-07-06T10:00:00+00:00",
                }
            ]
        )
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions[0].description == "Swiggy order #123"

    def test_falls_back_through_description_fields_in_order(self):
        fi_data = _fi_data(
            [
                {
                    "amount": "100",
                    "type": "DEBIT",
                    "mode": "UPI",
                    "remarks": "  Zomato  ",
                    "particulars": "should not be used",
                    "transactionTimestamp": "2026-07-06T10:00:00+00:00",
                }
            ]
        )
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions[0].description == "Zomato"

    def test_falls_back_to_mode_and_type_when_no_narration_field(self):
        fi_data = _fi_data(
            [{"amount": "100", "type": "CREDIT", "mode": "NEFT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions[0].description == "NEFT CREDIT"

    def test_falls_back_to_type_alone_when_no_mode_present(self):
        # A row must have a valid CREDIT/DEBIT type to survive
        # map_fi_data_to_transactions's own validation at all, so the
        # "nothing present" case (truly empty mode+type) is only reachable
        # by calling _description_for directly — see the test below.
        fi_data = _fi_data([{"amount": "100", "type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}])
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions[0].description == "CREDIT"

    def test_description_for_falls_back_to_generic_label_when_nothing_present(self):
        assert _description_for({}) == "Bank transaction"


class TestDateHandling:
    def test_reads_date_from_transaction_timestamp(self):
        fi_data = _fi_data(
            [{"amount": "100", "type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions[0].date.isoformat() == "2026-07-06"

    def test_falls_back_to_value_date_when_no_timestamp(self):
        fi_data = _fi_data([{"amount": "100", "type": "CREDIT", "valueDate": "2026-07-09"}])
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions[0].date.isoformat() == "2026-07-09"


class TestSkippedRows:
    def test_missing_date_is_skipped_not_raised(self):
        fi_data = _fi_data([{"amount": "100", "type": "CREDIT"}])
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions == []
        assert len(skipped) == 1

    def test_missing_amount_is_skipped(self):
        fi_data = _fi_data([{"type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}])
        _, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert len(skipped) == 1

    def test_unrecognized_type_is_skipped(self):
        fi_data = _fi_data(
            [{"amount": "100", "type": "REVERSAL", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        _, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert len(skipped) == 1

    def test_non_numeric_amount_is_skipped(self):
        fi_data = _fi_data(
            [{"amount": "not-a-number", "type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        _, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert len(skipped) == 1

    def test_valid_and_invalid_rows_both_reported_in_one_call(self):
        fi_data = _fi_data(
            [
                {"amount": "100", "type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"},
                {"amount": "bad", "type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"},
            ]
        )
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert len(transactions) == 1
        assert len(skipped) == 1


class TestSingleTransactionDictQuirk:
    def test_single_transaction_as_bare_dict_not_list(self):
        """A known XML->JSON conversion quirk (see module docstring): a lone
        transaction sometimes arrives unwrapped instead of a one-item list."""
        fi_data = {
            "account": {
                "transactions": {
                    "transaction": {
                        "amount": "250",
                        "type": "DEBIT",
                        "transactionTimestamp": "2026-07-06T10:00:00+00:00",
                    }
                }
            }
        }
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert skipped == []
        assert len(transactions) == 1
        assert transactions[0].amount == -250.0


class TestSourceAccountAndId:
    def test_source_account_is_stamped_on_every_transaction(self):
        fi_data = _fi_data(
            [
                {"amount": "100", "type": "CREDIT", "transactionTimestamp": "2026-07-06T10:00:00+00:00"},
                {"amount": "200", "type": "DEBIT", "transactionTimestamp": "2026-07-07T10:00:00+00:00"},
            ]
        )
        transactions, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert all(t.source_account == "HDFC (via Setu)" for t in transactions)

    def test_reparsing_same_data_produces_same_ids(self):
        """make_transaction_id is content-hashed — re-fetching the same
        consent's data twice (e.g. after a status re-check) should dedup the
        same way re-uploading a statement twice already does."""
        fi_data = _fi_data(
            [{"amount": "100", "type": "CREDIT", "narration": "Salary", "transactionTimestamp": "2026-07-06T10:00:00+00:00"}]
        )
        first, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        second, _ = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert first[0].transaction_id == second[0].transaction_id

    def test_empty_transaction_list_returns_empty_not_error(self):
        fi_data = _fi_data([])
        transactions, skipped = map_fi_data_to_transactions(fi_data, "HDFC (via Setu)")
        assert transactions == []
        assert skipped == []

    def test_missing_account_key_returns_empty_not_error(self):
        transactions, skipped = map_fi_data_to_transactions({}, "HDFC (via Setu)")
        assert transactions == []
        assert skipped == []
