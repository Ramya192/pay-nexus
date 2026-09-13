"""
Exact deduction-gap arithmetic for the old tax regime's capped sections —
80C (₹1.5L), 80D (₹25k/₹50k), 24(b) home loan interest (₹2L). Computed here
in Python and handed to the Nudge Agent as already-correct figures to
narrate, rather than left for the LLM to derive — a smaller model got an
80C subtraction wrong in earlier testing (see agents/nudge_agent.py's
prompt history); this removes that failure mode for the figures it can
compute, rather than just asking the model to double-check its own math.

Simplifications, stated plainly rather than silently baked in:
- 80C counts ELSS mutual funds + home loan principal + life insurance
  premium + the payslip's employee PF contribution (annualized as
  monthly x 12 — an estimate when only one month's payslip is on file, not
  a real annual total). PPF, NSC, tax-saver FDs, tuition fees, and several
  other real 80C instruments aren't collected by FinancialProfile at all,
  so aren't counted here.
- 80D is treated as one combined premium against one cap (₹25k, or ₹50k if
  `healthInsuranceForSeniorCitizen` is set). The real rule has a separate
  bucket for parents' premiums that can push the true combined cap to ₹1L
  — this undercounts a household paying for both their own and senior
  parents' policies. Flagged in the returned `note`, not just here.
- All of this is old-regime-only — none of these deductions exist under
  the new regime (see the New vs Old Regime FAQ already in the RAG
  corpus). Nothing in this module decides which regime is better; it just
  computes the old-regime numbers so the agents don't have to guess them.
"""

from dataclasses import dataclass

SECTION_80C_LIMIT = 150_000
SECTION_80D_LIMIT_STANDARD = 25_000
SECTION_80D_LIMIT_SENIOR = 50_000
SECTION_24B_LIMIT = 200_000

# Matches frontend/src/store/financialProfileStore.ts's FinancialProfile
# keys and frontend/src/components/FinancialProfile/FinancialProfileForm.tsx's
# field labels — used so an agent can answer "what have I entered" directly
# from the raw declared figures, not just the section-level gap rollups
# below (which sum several fields together and lose the per-field detail).
_FIELD_LABELS = {
    "elssMutualFunds": "ELSS mutual funds",
    "otherMutualFunds": "Other mutual funds",
    "stocks": "Stocks",
    "fdPrincipal": "Fixed deposits — principal",
    "fdInterestEarned": "Fixed deposits — interest earned",
    "rdPrincipal": "Recurring deposits — principal",
    "rdInterestEarned": "Recurring deposits — interest earned",
    "homeLoanPrincipalPaid": "Home loan — principal repaid",
    "homeLoanInterestPaid": "Home loan — interest paid",
    "lifeInsurancePremium": "Life insurance premium",
    "healthInsurancePremium": "Health insurance premium",
}


@dataclass
class DeductionGap:
    label: str
    section: str
    limit: int
    used: int
    remaining: int
    note: str | None = None


def _num(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def compute_80c(financial_profile: dict, payslip_data: dict | None = None) -> DeductionGap:
    elss = _num(financial_profile.get("elssMutualFunds"))
    life_insurance = _num(financial_profile.get("lifeInsurancePremium"))
    home_loan_principal = _num(financial_profile.get("homeLoanPrincipalPaid"))

    pf_note = None
    pf_annualized = 0.0
    if payslip_data and payslip_data.get("pfEmployee") is not None:
        pf_annualized = _num(payslip_data.get("pfEmployee")) * 12
        pf_note = "Includes PF annualized as one month's payslip figure x 12 — an estimate, not a confirmed annual total."

    raw_used = elss + life_insurance + home_loan_principal + pf_annualized
    used = min(raw_used, SECTION_80C_LIMIT)
    return DeductionGap(
        label="Section 80C",
        section="80C",
        limit=SECTION_80C_LIMIT,
        used=round(used),
        remaining=round(SECTION_80C_LIMIT - used),
        note=pf_note,
    )


def compute_80d(financial_profile: dict) -> DeductionGap:
    premium = _num(financial_profile.get("healthInsurancePremium"))
    senior = bool(financial_profile.get("healthInsuranceForSeniorCitizen"))
    limit = SECTION_80D_LIMIT_SENIOR if senior else SECTION_80D_LIMIT_STANDARD
    used = min(premium, limit)
    return DeductionGap(
        label="Section 80D",
        section="80D",
        limit=limit,
        used=round(used),
        remaining=round(limit - used),
        note=(
            "Combined self/family cap only — the real Section 80D has a separate bucket for "
            "parents' premiums (also ₹25k, or ₹50k if senior citizens) that this doesn't include."
        ),
    )


def compute_24b(financial_profile: dict) -> DeductionGap:
    interest = _num(financial_profile.get("homeLoanInterestPaid"))
    used = min(interest, SECTION_24B_LIMIT)
    return DeductionGap(
        label="Section 24(b) — home loan interest",
        section="24(b)",
        limit=SECTION_24B_LIMIT,
        used=round(used),
        remaining=round(SECTION_24B_LIMIT - used),
    )


def compute_all_gaps(financial_profile: dict, payslip_data: dict | None = None) -> list[DeductionGap]:
    return [
        compute_80c(financial_profile, payslip_data),
        compute_80d(financial_profile),
        compute_24b(financial_profile),
    ]


def format_financial_profile_for_prompt(financial_profile: dict) -> str:
    """The raw declared figures, field by field — e.g. for "what have I
    entered?" questions, which format_gaps_for_prompt's section-level
    rollups can't answer (₹85,853 "80C used" doesn't say how much of that
    was life insurance vs. ELSS vs. home loan principal). Complements the
    gap totals below rather than replacing them; a caller typically wants
    both sections in the prompt."""
    lines = [
        f"{label}: ₹{_num(financial_profile[key]):,.0f}"
        for key, label in _FIELD_LABELS.items()
        if financial_profile.get(key)
    ]
    if financial_profile.get("healthInsuranceForSeniorCitizen"):
        lines.append("Health insurance covers a senior citizen (80D cap raised to ₹50,000)")
    if not lines:
        return ""
    return "Declared investments/loans/insurance, as entered:\n" + "\n".join(lines)


def format_gaps_for_prompt(gaps: list[DeductionGap]) -> str:
    """Renders gaps as plain lines ready to drop into an agent's user
    prompt — the agent's job is to narrate and suggest, not recompute
    these numbers."""
    lines = []
    for gap in gaps:
        line = f"{gap.label} ({gap.section}): ₹{gap.used:,} used of ₹{gap.limit:,} limit → ₹{gap.remaining:,} remaining"
        if gap.note:
            line += f" [{gap.note}]"
        lines.append(line)
    return "\n".join(lines)


# --- Table builders, for the frontend's actual <table> rendering ---
#
# Built directly here in Python from the same DeductionGap/dict data the
# format_*_for_prompt functions above already render as prose — never from
# the LLM's own output — so a chat response's table and its narration can
# never show different numbers for the same question (the failure mode a
# free-text "detail" paragraph doesn't structurally prevent). Agent nodes
# attach these to their state update directly; the LLM never sees or
# produces table data. Shape: {"title": str, "headers": [str, ...],
# "rows": [[str, ...], ...]} — frontend/src/components/Chat/DataTable.tsx
# renders exactly this shape.


def gaps_table(gaps: list[DeductionGap]) -> dict:
    return {
        "title": "Deduction gaps (old regime)",
        "headers": ["Section", "Used", "Limit", "Remaining"],
        "rows": [
            [gap.label, f"₹{gap.used:,}", f"₹{gap.limit:,}", f"₹{gap.remaining:,}"] for gap in gaps
        ],
    }


def financial_profile_table(financial_profile: dict) -> dict | None:
    rows = [
        [label, f"₹{_num(financial_profile[key]):,.0f}"]
        for key, label in _FIELD_LABELS.items()
        if financial_profile.get(key)
    ]
    if not rows:
        return None
    return {"title": "Declared investments, loans & insurance", "headers": ["Item", "Amount"], "rows": rows}
