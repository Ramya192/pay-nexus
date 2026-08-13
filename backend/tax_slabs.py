"""
Indian income tax liability — old vs. new regime — computed exactly here in
Python and handed to the Payslip agent as an already-solved figure, same
"compute exactly, never let the LLM guess" pattern as tax_calculations.py
(deduction gaps) and payslip_trends.py (trends). Until this module existed,
every agent was explicitly instructed to refuse a real ₹ tax liability
figure — that refusal was correct given nothing computed one, not a
permanent design choice; this replaces "we can't tell you" with a real,
clearly-labeled estimate.

Two things this can NEVER be more accurate than, stated plainly so the
caveat travels with every result rather than living only here:

1. **The slab rates below have a shelf life.** FY_LABEL says which Union
   Budget these numbers come from. Income tax slabs, the standard
   deduction, and the 87A rebate threshold all change when a new Budget is
   presented (typically each February) — nothing in this codebase checks
   whether a newer Budget has superseded these figures. Whoever maintains
   this needs to update `_NEW_REGIME_SLABS` etc. by hand after each Budget;
   there is no live source.
2. **The annual income feeding this is usually an estimate, not a
   confirmed total** — see estimate_annual_gross_income() below. A single
   month's payslip multiplied by 12 doesn't account for raises, bonus
   timing, or mid-year changes; even summing several saved months is only
   as complete as what's been saved to history.

Deliberately excluded, not silently ignored: surcharge (only applies above
₹50L annual income — this app's salaried mid-income audience is very
unlikely to hit it, and surcharge itself has its own marginal-relief rules
that would meaningfully complicate this module for a case that rarely
applies here) and any non-salary income (capital gains, other-source
income, etc. — this only ever sees a payslip).
"""

from dataclasses import dataclass

FY_LABEL = "FY 2025-26 (AY 2026-27), per Union Budget 2025"

# New regime (the default regime since FY 2023-24) — slabs restructured and
# the 87A rebate threshold raised to ₹12L in Budget 2025.
_NEW_REGIME_SLABS: list[tuple[float, float]] = [
    (400_000, 0.0),
    (800_000, 0.05),
    (1_200_000, 0.10),
    (1_600_000, 0.15),
    (2_000_000, 0.20),
    (2_400_000, 0.25),
    (float("inf"), 0.30),
]
_NEW_REGIME_STANDARD_DEDUCTION = 75_000
_NEW_REGIME_REBATE_THRESHOLD = 1_200_000  # taxable income at/below this -> full rebate
_NEW_REGIME_REBATE_MAX = 60_000

# Old regime — unchanged for several Budgets; no deductions in the new
# regime, which is the entire basis for a "which regime wins" comparison.
_OLD_REGIME_SLABS: list[tuple[float, float]] = [
    (250_000, 0.0),
    (500_000, 0.05),
    (1_000_000, 0.20),
    (float("inf"), 0.30),
]
_OLD_REGIME_STANDARD_DEDUCTION = 50_000
_OLD_REGIME_REBATE_THRESHOLD = 500_000
_OLD_REGIME_REBATE_MAX = 12_500

CESS_RATE = 0.04  # health & education cess, on tax after rebate


@dataclass
class TaxResult:
    regime: str
    gross_income: float
    standard_deduction: float
    other_deductions: float
    taxable_income: float
    tax_before_rebate: float
    rebate: float
    cess: float
    total_tax: float


def _slab_tax(taxable_income: float, slabs: list[tuple[float, float]]) -> float:
    tax = 0.0
    lower = 0.0
    for upper, rate in slabs:
        if taxable_income <= lower:
            break
        band = min(taxable_income, upper) - lower
        tax += band * rate
        lower = upper
    return tax


def _apply_rebate_and_relief(tax: float, taxable_income: float, threshold: float, max_rebate: float) -> tuple[float, float]:
    """Section 87A rebate below the threshold, plus marginal relief just
    above it — without relief, taxable income a rupee over the threshold
    could owe far more tax than the extra rupee, a real cliff the rebate
    would otherwise create. Returns (tax_after_rebate, rebate_amount)."""
    if taxable_income <= threshold:
        rebate = min(tax, max_rebate)
        return tax - rebate, rebate
    relief_cap = taxable_income - threshold
    if tax > relief_cap:
        return relief_cap, tax - relief_cap  # "rebate" here is really marginal relief, same net effect
    return tax, 0.0


def compute_old_regime_tax(annual_gross_income: float, declared_deductions: float) -> TaxResult:
    taxable = max(0.0, annual_gross_income - _OLD_REGIME_STANDARD_DEDUCTION - declared_deductions)
    tax = _slab_tax(taxable, _OLD_REGIME_SLABS)
    tax_after_rebate, rebate = _apply_rebate_and_relief(tax, taxable, _OLD_REGIME_REBATE_THRESHOLD, _OLD_REGIME_REBATE_MAX)
    cess = tax_after_rebate * CESS_RATE
    return TaxResult(
        "old", annual_gross_income, _OLD_REGIME_STANDARD_DEDUCTION, declared_deductions,
        taxable, tax, rebate, cess, tax_after_rebate + cess,
    )


def compute_new_regime_tax(annual_gross_income: float) -> TaxResult:
    taxable = max(0.0, annual_gross_income - _NEW_REGIME_STANDARD_DEDUCTION)
    tax = _slab_tax(taxable, _NEW_REGIME_SLABS)
    tax_after_rebate, rebate = _apply_rebate_and_relief(tax, taxable, _NEW_REGIME_REBATE_THRESHOLD, _NEW_REGIME_REBATE_MAX)
    cess = tax_after_rebate * CESS_RATE
    return TaxResult(
        "new", annual_gross_income, _NEW_REGIME_STANDARD_DEDUCTION, 0.0,
        taxable, tax, rebate, cess, tax_after_rebate + cess,
    )


_GROSS_FIELDS = ("basic", "hra", "specialAllowance", "bonus")


def _num(value) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def estimate_annual_gross_income(payslip_data: dict, payslip_history: list[dict]) -> tuple[float, str]:
    """Prefers summing actual months on file over extrapolating from one
    month — bonuses and mid-year raises make a flat x12 unreliable, and a
    real multi-month sum is strictly better data when it's there. Returns
    (estimated_annual_gross, method_note) — the note is meant to be shown
    to the user verbatim, not just logged, since which method was used
    materially affects how much to trust the resulting figure."""
    if len(payslip_history) >= 6:
        total = sum(sum(_num(m.get(f)) for f in _GROSS_FIELDS) for m in payslip_history)
        count = len(payslip_history)
        if count >= 12:
            return total, f"Summed actual gross pay across all {count} saved months on file — a real annual total, not extrapolated."
        scaled = total / count * 12
        return scaled, (
            f"Summed actual gross pay across {count} saved months and scaled to a full year — "
            "an estimate, not a confirmed annual total."
        )
    monthly = sum(_num(payslip_data.get(f)) for f in _GROSS_FIELDS)
    return monthly * 12, (
        "Estimated by multiplying one month's payslip by 12 — a rough estimate; doesn't account "
        "for raises, bonus timing, or months not on file. Save more months to history for a "
        "better estimate."
    )


def cheaper_regime_statement(old_result: TaxResult, new_result: TaxResult) -> str:
    """The recommendation itself, computed here — not left for the LLM to
    derive from the two totals. Found necessary after a real, observed
    failure: even with both correct totals sitting right in its own
    prompt (and even after correctly quoting them in its own sentence),
    the model still inverted the comparison and recommended the more
    expensive regime. Quoting the raw numbers wasn't enough of a guardrail
    on its own — the comparison judgment itself needs to be pre-solved and
    handed over as a conclusion to narrate, the same "compute exactly,
    never let the LLM derive it" rule this codebase already applies to
    every other number, just extended to cover the comparison step too."""
    if new_result.total_tax < old_result.total_tax:
        savings = old_result.total_tax - new_result.total_tax
        return (
            f"The NEW regime is cheaper: ₹{new_result.total_tax:,.0f} vs ₹{old_result.total_tax:,.0f} "
            f"under the old regime — the new regime saves ₹{savings:,.0f}. Recommend the new regime."
        )
    if old_result.total_tax < new_result.total_tax:
        savings = new_result.total_tax - old_result.total_tax
        return (
            f"The OLD regime is cheaper: ₹{old_result.total_tax:,.0f} vs ₹{new_result.total_tax:,.0f} "
            f"under the new regime — the old regime saves ₹{savings:,.0f}. Recommend the old regime."
        )
    return f"Both regimes come to the same ₹{old_result.total_tax:,.0f} — neither is cheaper than the other."


def tax_liability_table(old_result: TaxResult, new_result: TaxResult, income_note: str) -> dict:
    def rows_for(r: TaxResult) -> list[str]:
        return [
            f"₹{r.gross_income:,.0f}",
            f"₹{r.standard_deduction:,.0f}",
            f"₹{r.other_deductions:,.0f}",
            f"₹{r.taxable_income:,.0f}",
            f"₹{r.tax_before_rebate:,.0f}",
            f"₹{r.rebate:,.0f}",
            f"₹{r.cess:,.0f}",
            f"₹{r.total_tax:,.0f}",
        ]

    old_col = rows_for(old_result)
    new_col = rows_for(new_result)
    labels = [
        "Estimated annual gross income", "Standard deduction", "Other deductions", "Taxable income",
        "Tax before rebate", "87A rebate / marginal relief", "Cess (4%)", "Total tax payable",
    ]
    return {
        "title": f"Tax liability estimate — Old vs New Regime ({FY_LABEL}). Income basis: {income_note}",
        "headers": ["", "Old Regime", "New Regime"],
        "rows": [[label, old_col[i], new_col[i]] for i, label in enumerate(labels)],
    }
