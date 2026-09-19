"""
Net pay / gross pay arithmetic from a payslip's raw components.

This closes a real gap found 2026-09-15 answering a user question directly
("what would my net pay be if I contributed 2% more to PF?"): nothing
anywhere in this codebase actually computed a net pay figure. agents/
payslip_agent.py handed the LLM raw components (basic, HRA, PF, TDS, ...)
and let it narrate/derive take-home in its own words — exactly the "LLM
invents a number" failure mode every OTHER money calculation here
(tax_calculations.py, tax_slabs.py, payslip_trends.py) was specifically
built to avoid. This module is the missing "compute exactly in Python"
piece for net pay, used by both the Payslip Reasoning agent's regular
narration (a real, always-on fix, not just a hypothetical-only one) and
the new "what if I changed X on my payslip" scenario in agents/whatif_agent.py.

Formula, stated exactly rather than left implicit:
    Gross pay = Basic + HRA + Special Allowance + Bonus
    Net pay   = Gross pay - PF (employee) - Professional Tax - TDS

`pfEmployer` is deliberately excluded from both gross and net — it's paid
BY the employer INTO the employee's PF account, never part of the
employee's own gross or take-home pay, despite appearing as a line item on
most Indian payslips. `rentPaid` is also excluded — it isn't a payslip
deduction at all, just an input to the HRA exemption calculation elsewhere
(tax_slabs.py doesn't touch it either).

Known, stated simplifications (same "flagged plainly, not silently baked
in" standard as tax_calculations.py's own docstring): no loss-of-pay/
unpaid-leave proration, no ESI, no loan-EMI or other ad hoc deductions some
employers list separately — this only models the 9 numeric fields
ManualEntryForm.tsx / payslip_extraction.py actually collect.
"""

from dataclasses import dataclass

# Same 4 fields as tax_slabs.py's private _GROSS_FIELDS (annual income
# estimation) — duplicated rather than imported, since that name is private
# to that module and the two concepts (one month's gross pay vs. an annual
# income estimate) are related but not the same computation. If one changes,
# check whether the other should too.
GROSS_PAY_FIELDS = ("basic", "hra", "specialAllowance", "bonus")
NET_PAY_DEDUCTION_FIELDS = ("pfEmployee", "professionalTax", "tds")

# Matches payslip_agent.py's old _COMPONENT_LABELS and ManualEntryForm.tsx's
# field labels exactly — the single source of truth for both the live
# components table and the what-if scenario table now.
FIELD_LABELS = {
    "basic": "Basic",
    "hra": "HRA received",
    "specialAllowance": "Special Allowance",
    "pfEmployee": "PF — employee",
    "pfEmployer": "PF — employer",
    "professionalTax": "Professional Tax",
    "tds": "TDS",
    "bonus": "Bonus this month",
    "rentPaid": "Monthly rent paid",
}

# Fields a what-if scenario can actually change. Excludes pfEmployer
# (doesn't affect the employee's own pay at all — see module docstring) and
# rentPaid (an HRA-exemption input elsewhere, not a payslip amount whose
# change flows through net pay the same way).
EDITABLE_PAYSLIP_FIELDS = (
    "basic", "hra", "specialAllowance", "pfEmployee", "professionalTax", "tds", "bonus",
)


def _num(value) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def compute_gross_pay(payslip: dict) -> float:
    return sum(_num(payslip.get(f)) for f in GROSS_PAY_FIELDS)


def compute_net_pay(payslip: dict) -> float:
    return compute_gross_pay(payslip) - sum(_num(payslip.get(f)) for f in NET_PAY_DEDUCTION_FIELDS)


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field)


@dataclass
class PayslipFieldChange:
    field: str
    scenario_payslip: dict
    baseline_value: float
    scenario_value: float


def apply_field_change(
    payslip: dict,
    field: str,
    *,
    new_value: float | None = None,
    delta_amount: float | None = None,
    delta_percent_of_basic: float | None = None,
) -> PayslipFieldChange | None:
    """Returns None if `field` isn't a real editable field, or none of the
    three change kinds were given. Precedence when more than one is set
    (shouldn't normally happen — whatif_extraction.py's prompt asks for at
    most one per question — but resolved deterministically rather than
    silently combined if it does): an absolute new_value wins, then a rupee
    delta_amount, then a percent-of-basic delta.

    delta_percent_of_basic exists specifically for the most common way a PF
    change is actually phrased ("2% more to PF") — the LLM extractor hands
    back the raw percentage it was given, and this function does the actual
    rupee arithmetic against the real basic figure, rather than trusting an
    LLM to multiply correctly (the same "never let the model do money math"
    rule as everywhere else in this codebase).
    """
    if field not in EDITABLE_PAYSLIP_FIELDS:
        return None
    baseline_value = _num(payslip.get(field))
    if new_value is not None:
        scenario_value = _num(new_value)
    elif delta_amount is not None:
        scenario_value = baseline_value + _num(delta_amount)
    elif delta_percent_of_basic is not None:
        scenario_value = baseline_value + (_num(delta_percent_of_basic) / 100.0) * _num(payslip.get("basic"))
    else:
        return None
    scenario_value = max(0.0, scenario_value)
    scenario_payslip = {**payslip, field: scenario_value}
    return PayslipFieldChange(field, scenario_payslip, baseline_value, scenario_value)


def net_pay_table(payslip: dict, *, title_suffix: str = "") -> dict:
    """Same shape payslip_agent.py's old _components_table built, plus a
    real, Python-computed Net Pay row (and a Gross Pay row) appended — the
    live fix for the gap this module's docstring describes, not just the
    what-if scenario's own table below."""
    rows = [
        [FIELD_LABELS[f], f"₹{_num(payslip[f]):,.0f}"]
        for f in FIELD_LABELS
        if isinstance(payslip.get(f), (int, float)) and not isinstance(payslip.get(f), bool)
    ]
    if not rows:
        return {"title": "Payslip components", "headers": ["Component", "Amount"], "rows": []}
    rows.append(["Gross pay (computed)", f"₹{compute_gross_pay(payslip):,.0f}"])
    rows.append(["Net pay (computed)", f"₹{compute_net_pay(payslip):,.0f}"])
    month = payslip.get("month", "")
    title = f"Payslip components{f' — {month}' if month else ''}{title_suffix}"
    return {"title": title, "headers": ["Component", "Amount"], "rows": rows}
