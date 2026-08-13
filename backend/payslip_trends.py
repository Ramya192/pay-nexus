"""
Exact month-over-month trend computation over saved payslip snapshots —
computed here in Python and handed to the Nudge Agent as already-correct
figures, same pattern as tax_calculations.py (which does the same thing for
80C/80D/24(b) deduction gaps). A trend needs at least two snapshots with
that field filled in; with fewer, this says so rather than inventing a
direction from a single data point.

Only compares first vs. last snapshot with data for a given field — not a
full regression or a "which month spiked" analysis. That's a deliberate
scope limit: first-vs-last answers "is this going up or down overall,"
which is what the Nudge Agent's prompts actually need, without pretending
to a precision (trend lines, seasonality) this data doesn't support.
"""

from dataclasses import dataclass

# Gradual fields — first-vs-last is a meaningful trend. Bonus is handled
# separately below: it's a lump-sum spike field, not a gradual one, and
# first-vs-last on it is actively misleading (a real mid-period bonus reads
# as "flat" if the months on either end both happen to be zero — caught by
# testing this against fabricated data with a June bonus that vanished from
# the trend entirely).
_TREND_FIELDS = (
    ("basic", "Basic salary"),
    ("tds", "TDS"),
    ("hra", "HRA"),
)


@dataclass
class FieldTrend:
    field: str
    label: str
    first_month: str
    first_value: float
    last_month: str
    last_value: float
    delta: float
    direction: str  # "up" | "down" | "flat"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compute_trends(snapshots: list[dict]) -> list[FieldTrend]:
    """`snapshots` should already be sorted oldest → newest (GET
    /payslip/snapshots orders by month ascending, so the client doesn't
    need to re-sort before calling anything downstream of this)."""
    trends = []
    for field, label in _TREND_FIELDS:
        points = [(s.get("month", "?"), s[field]) for s in snapshots if _is_number(s.get(field))]
        if len(points) < 2:
            continue
        first_month, first_value = points[0]
        last_month, last_value = points[-1]
        delta = last_value - first_value
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        trends.append(
            FieldTrend(field, label, first_month, first_value, last_month, last_value, delta, direction)
        )
    return trends


def _bonus_summary(snapshots: list[dict]) -> str | None:
    """Bonus months, not a first-vs-last trend — see _TREND_FIELDS comment
    for why. Lists every month a bonus was actually paid, so the Nudge
    Agent can connect a mid-period bonus to, say, a same-month TDS jump."""
    paid = [(s.get("month", "?"), s["bonus"]) for s in snapshots if _is_number(s.get("bonus")) and s["bonus"] > 0]
    if not paid:
        return None
    total = sum(v for _, v in paid)
    detail = ", ".join(f"₹{v:,.0f} in {m}" for m, v in paid)
    return f"Bonus paid in {len(paid)} of {len(snapshots)} months on file, totaling ₹{total:,.0f}: {detail}"


def resolve_effective_payslip(payslip_data: dict, payslip_history: list[dict]) -> tuple[dict, bool]:
    """Falls back to the most recently saved payslip_history snapshot when
    no payslip is active this session (nothing set via "Use this payslip").
    Shared by agents/payslip_agent.py and agents/nudge_agent.py so BOTH
    agents compute 80C/80D/24(b) deduction gaps (tax_calculations.py, which
    factors in this payslip's employee PF contribution) from the same
    effective payslip within one conversation. Found as a real bug in
    testing: with no session-active payslip, payslip_agent fell back to
    history but nudge_agent didn't, so the same conversation stated two
    different total-deduction figures for the same user — one including a
    saved payslip's annualized PF, one not — depending on which agent
    answered a given question. Returns (effective_payslip, used_fallback).
    """
    if not payslip_data and payslip_history:
        return payslip_history[-1], True  # most recent — GET /payslip/snapshots orders ascending
    return payslip_data, False


def detect_duplicate_months(snapshots: list[dict]) -> list[tuple[str, int]]:
    """Which months have more than one saved snapshot — e.g. a batch upload
    run twice before POST /payslip/save started rejecting a second save for
    the same month (see api/routes/payslip.py). Returns [(month, count),
    ...] for months with count > 1 only, in the order first seen; empty
    list means no duplicates. Deliberately exact/deterministic, same reason
    as compute_trends above: "are there duplicates" is a factual question
    with one right answer, not something to leave an LLM to eyeball from a
    raw snapshot dump."""
    counts: dict[str, int] = {}
    for s in snapshots:
        month = s.get("month")
        if month:
            counts[month] = counts.get(month, 0) + 1
    return [(month, count) for month, count in counts.items() if count > 1]


def format_duplicates_for_prompt(snapshots: list[dict]) -> str:
    duplicates = detect_duplicate_months(snapshots)
    if not duplicates:
        return "Duplicate-month check (already computed): no duplicate months found in payslip history."
    detail = ", ".join(f"{month} ({count} copies)" for month, count in duplicates)
    return (
        f"Duplicate-month check (already computed): {len(duplicates)} month(s) have more than one "
        f"saved snapshot — {detail}. Chat can't delete them (no agent can write to storage) — if the "
        "user wants them removed, point them to the \"Remove duplicates\" button in the Payslip "
        "history section of the sidebar, not offer to do it here."
    )


def format_trends_for_prompt(snapshots: list[dict]) -> str:
    trends = compute_trends(snapshots)
    count = len(snapshots)
    bonus_line = _bonus_summary(snapshots)

    if not trends and not bonus_line:
        return (
            f"{count} payslip snapshot(s) on file — not enough to compute a trend yet "
            "(needs at least 2 months with the same field filled in)."
        )

    lines = [f"{count} payslip snapshots on file. Computed trends (already correct — quote directly, do not recompute):"]
    for t in trends:
        arrow = "↑" if t.direction == "up" else "↓" if t.direction == "down" else "→"
        lines.append(
            f"{t.label}: ₹{t.first_value:,.0f} ({t.first_month}) {arrow} ₹{t.last_value:,.0f} ({t.last_month}) "
            f"— change of ₹{abs(t.delta):,.0f} ({t.direction})"
        )
    if bonus_line:
        lines.append(bonus_line)
    return "\n".join(lines)


# --- Table builders, for the frontend's actual <table> rendering — same
# rationale as tax_calculations.py's: built here in Python from the same
# data the format_*_for_prompt functions above already render as prose,
# never from the LLM, so a table and its narration can't disagree. Shape:
# {"title": str, "headers": [str, ...], "rows": [[str, ...], ...]}.


def trends_table(snapshots: list[dict]) -> dict | None:
    trends = compute_trends(snapshots)
    bonus_line = _bonus_summary(snapshots)
    if not trends and not bonus_line:
        return None
    rows = [
        [t.label, f"₹{t.first_value:,.0f} ({t.first_month})", f"₹{t.last_value:,.0f} ({t.last_month})",
         f"{'↑' if t.direction == 'up' else '↓' if t.direction == 'down' else '→'} ₹{abs(t.delta):,.0f}"]
        for t in trends
    ]
    if bonus_line:
        rows.append(["Bonus", bonus_line, "", ""])
    return {"title": "Payslip trends", "headers": ["Field", "First", "Last", "Change"], "rows": rows}


def duplicates_table(snapshots: list[dict]) -> dict | None:
    duplicates = detect_duplicate_months(snapshots)
    if not duplicates:
        return None
    return {
        "title": "Duplicate months found",
        "headers": ["Month", "Saved copies"],
        "rows": [[month, str(count)] for month, count in duplicates],
    }
