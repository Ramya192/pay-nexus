"""Unit tests for payslip_math.py — the net-pay/gross-pay arithmetic that
didn't exist anywhere in this codebase before 2026-09-15 (see the module's
own docstring for the real user question that surfaced the gap)."""

from payslip_math import (
    EDITABLE_PAYSLIP_FIELDS,
    apply_field_change,
    compute_gross_pay,
    compute_net_pay,
    field_label,
    net_pay_table,
)

_PAYSLIP = {
    "month": "2026-07",
    "basic": 50_000,
    "hra": 20_000,
    "specialAllowance": 5_000,
    "pfEmployee": 6_000,
    "pfEmployer": 6_000,
    "professionalTax": 200,
    "tds": 3_000,
    "bonus": 0,
    "rentPaid": 18_000,
}


class TestGrossAndNetPay:
    def test_gross_pay_sums_only_earning_components(self):
        # basic + hra + specialAllowance + bonus = 50,000 + 20,000 + 5,000 + 0
        assert compute_gross_pay(_PAYSLIP) == 75_000

    def test_net_pay_subtracts_employee_pf_professional_tax_and_tds_only(self):
        # 75,000 gross - 6,000 PF - 200 PT - 3,000 TDS
        assert compute_net_pay(_PAYSLIP) == 65_800

    def test_employer_pf_never_reduces_net_pay(self):
        with_bigger_employer_pf = {**_PAYSLIP, "pfEmployer": 50_000}
        assert compute_net_pay(with_bigger_employer_pf) == compute_net_pay(_PAYSLIP)

    def test_rent_paid_never_reduces_net_pay(self):
        with_bigger_rent = {**_PAYSLIP, "rentPaid": 90_000}
        assert compute_net_pay(with_bigger_rent) == compute_net_pay(_PAYSLIP)

    def test_missing_fields_default_to_zero_not_an_error(self):
        assert compute_net_pay({"basic": 40_000}) == 40_000

    def test_bool_is_not_treated_as_a_number(self):
        # isinstance(True, int) is True in Python -- must be excluded explicitly.
        assert compute_gross_pay({"basic": True, "hra": 10_000}) == 10_000


class TestApplyFieldChange:
    def test_unknown_field_returns_none(self):
        assert apply_field_change(_PAYSLIP, "notARealField", new_value=100) is None

    def test_pf_employer_is_not_editable(self):
        # Doesn't affect the employee's own pay at all -- see module docstring.
        assert "pfEmployer" not in EDITABLE_PAYSLIP_FIELDS
        assert apply_field_change(_PAYSLIP, "pfEmployer", new_value=99_999) is None

    def test_rent_paid_is_not_editable(self):
        assert "rentPaid" not in EDITABLE_PAYSLIP_FIELDS

    def test_absolute_new_value(self):
        result = apply_field_change(_PAYSLIP, "basic", new_value=60_000)
        assert result.baseline_value == 50_000
        assert result.scenario_value == 60_000
        assert result.scenario_payslip["basic"] == 60_000
        # Original dict untouched -- caller still has the real baseline.
        assert _PAYSLIP["basic"] == 50_000

    def test_rupee_delta(self):
        result = apply_field_change(_PAYSLIP, "hra", delta_amount=2_000)
        assert result.scenario_value == 22_000

    def test_negative_rupee_delta(self):
        result = apply_field_change(_PAYSLIP, "tds", delta_amount=-1_000)
        assert result.scenario_value == 2_000

    def test_percent_of_basic_delta_is_the_pf_motivating_case(self):
        # "What would my net pay be if I contributed 2% more to PF?"
        # 2% of 50,000 basic = 1,000 extra PF.
        result = apply_field_change(_PAYSLIP, "pfEmployee", delta_percent_of_basic=2.0)
        assert result.scenario_value == 7_000  # 6,000 baseline + 1,000

    def test_result_never_goes_negative(self):
        result = apply_field_change(_PAYSLIP, "tds", delta_amount=-999_999)
        assert result.scenario_value == 0.0

    def test_no_change_kind_given_returns_none(self):
        assert apply_field_change(_PAYSLIP, "basic") is None

    def test_new_value_takes_precedence_over_delta_amount(self):
        result = apply_field_change(_PAYSLIP, "basic", new_value=60_000, delta_amount=5_000)
        assert result.scenario_value == 60_000


class TestFieldLabel:
    def test_known_field(self):
        assert field_label("pfEmployee") == "PF — employee"

    def test_unknown_field_falls_back_to_the_raw_name(self):
        assert field_label("somethingNew") == "somethingNew"


class TestNetPayTable:
    def test_includes_computed_gross_and_net_rows(self):
        table = net_pay_table(_PAYSLIP)
        row_labels = [row[0] for row in table["rows"]]
        assert "Gross pay (computed)" in row_labels
        assert "Net pay (computed)" in row_labels
        net_row = next(r for r in table["rows"] if r[0] == "Net pay (computed)")
        assert net_row[1] == "₹65,800"

    def test_empty_payslip_produces_no_rows(self):
        table = net_pay_table({"month": "2026-07"})
        assert table["rows"] == []

    def test_title_includes_month(self):
        table = net_pay_table(_PAYSLIP)
        assert "2026-07" in table["title"]
