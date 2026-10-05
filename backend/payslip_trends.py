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

from payslip_math import compute_net_pay

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


def chronological(snapshots: list[dict]) -> list[dict]:
    """Oldest -> newest by each snapshot's "month" ("YYYY-MM", so string order
    is chronological). The frontend normally sends them sorted, but a batch
    uploaded in a different order (e.g. 2026 files before 2025 ones) arrives
    in upload order until the page is reloaded -- and "first", "last" and
    "this month" below all depend on order. Stable, so snapshots with no month
    keep their relative position."""
    return sorted(snapshots, key=lambda s: str(s.get("month") or ""))


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _compute_net_pay_trend(snapshots: list[dict]) -> FieldTrend | None:
    """Same first-vs-last method as the raw-field trends below, but for
    payslip_math.compute_net_pay()'s DERIVED figure rather than a single
    raw field. Added 2026-09-15 alongside payslip_math.py, closing a real
    gap: "why did my take-home drop" previously had individual basic/HRA/
    TDS trends to look at but no actual net-pay number computed across
    months, only ever the current month's (agents/payslip_agent.py's
    components table) — leaving the LLM to mentally combine three separate
    trends into a take-home conclusion itself, the exact "let the model do
    money math" failure mode this module otherwise avoids.

    Gated on `basic` being present, not on every net-pay-affecting field —
    same reasoning as compute_net_pay() itself: a missing field defaults to
    zero rather than excluding the snapshot outright. A snapshot with
    basic but nothing else is a sparse/test-data edge case in practice, not
    the common real path, and still produces an honest (if partial)
    number rather than silently dropping the month from the trend."""
    points = [(s.get("month", "?"), compute_net_pay(s)) for s in chronological(snapshots) if _is_number(s.get("basic"))]
    if len(points) < 2:
        return None
    first_month, first_value = points[0]
    last_month, last_value = points[-1]
    delta = last_value - first_value
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    return FieldTrend("net_pay", "Net pay (computed)", first_month, first_value, last_month, last_value, delta, direction)


def compute_trends(snapshots: list[dict]) -> list[FieldTrend]:
    """`snapshots` should already be sorted oldest → newest (GET
    /payslip/snapshots orders by month ascending, so the client doesn't
    need to re-sort before calling anything downstream of this)."""
    trends = []
    snapshots = chronological(snapshots)
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
    if (net_pay_trend := _compute_net_pay_trend(snapshots)) is not None:
        trends.append(net_pay_trend)
    return trends


def _bonus_summary(snapshots: list[dict]) -> str | None:
    """Bonus months, not a first-vs-last trend — see _TREND_FIELDS comment
    for why. Lists every month a bonus was actually paid, so the Nudge
    Agent can connect a mid-period bonus to, say, a same-month TDS jump."""
    paid = [(s.get("month", "?"), s["bonus"]) for s in chronological(snapshots) if _is_number(s.get("bonus")) and s["bonus"] > 0]
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
        return chronological(payslip_history)[-1], True  # most recent by month
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
    """Distinguishes 'no payslip history at all' from 'history exists, no
    duplicates in it' — found as a real bug in testing: nudge_agent.py used
    to skip calling this function entirely when snapshots was empty, so a
    "check for duplicates" question with zero saved payslips got answered
    with no grounding at all, and the model said "no duplicates found" —
    true in the vacuous sense, but implying a real check ran against
    existing data when there wasn't any to check. Always called
    unconditionally now (see nudge_agent_node), so this needs to cover the
    empty case itself rather than relying on the caller to skip it."""
    if not snapshots:
        return (
            "Duplicate-month check (already computed): no payslip history saved yet — say so "
            "plainly rather than reporting 'no duplicates found', which would wrongly imply a "
            "check ran against existing history."
        )
    duplicates = detect_duplicate_months(snapshots)
    if not duplicates:
        return (
            f"Duplicate-month check (already computed): {len(snapshots)} payslip snapshot(s) on "
            "file, no duplicate months found."
        )
    detail = ", ".join(f"{month} ({count} copies)" for month, count in duplicates)
    return (
        f"Duplicate-month check (already computed): {len(duplicates)} month(s) have more than one "
        f"saved snapshot — {detail}. Chat can't delete them (no agent can write to storage) — if the "
        "user wants them removed, point them to the \"Remove duplicates\" button in the Payslip "
        "history tab, not offer to do it here."
    )


_CHANGE_FIELDS = (
    ("basic", "Basic"),
    ("hra", "HRA"),
    ("specialAllowance", "Special Allowance"),
    ("bonus", "Bonus"),
    ("pfEmployee", "PF — employee"),
    ("professionalTax", "Professional Tax"),
    ("tds", "TDS"),
)


@dataclass
class MonthChange:
    label: str
    previous: float
    latest: float

    @property
    def delta(self) -> float:
        return self.latest - self.previous


def compute_latest_change(snapshots: list[dict]) -> tuple[str, str, list[MonthChange]] | None:
    """Newest saved month vs the one before it -- what "why did my take-home
    drop this month" actually needs. (compute_trends compares the OLDEST month
    on file with the newest, which says nothing about this month's move.)
    Net pay is first, then each component whose two values are both present.
    None with fewer than two snapshots."""
    ordered = chronological(snapshots)
    if len(ordered) < 2:
        return None
    prev, latest = ordered[-2], ordered[-1]
    rows: list[MonthChange] = []
    if _is_number(prev.get("basic")) and _is_number(latest.get("basic")):
        rows.append(MonthChange("Net pay (take-home)", compute_net_pay(prev), compute_net_pay(latest)))
    for field, label in _CHANGE_FIELDS:
        # A component present in only one month counts as 0 in the other --
        # otherwise a newly added line (e.g. a Special Allowance that appears
        # in June) is silently dropped and the net-pay jump has no visible cause.
        if _is_number(prev.get(field)) or _is_number(latest.get(field)):
            rows.append(MonthChange(label, prev.get(field) if _is_number(prev.get(field)) else 0.0,
                                    latest.get(field) if _is_number(latest.get(field)) else 0.0))
    return str(prev.get("month", "?")), str(latest.get("month", "?")), rows


def format_latest_change_for_prompt(snapshots: list[dict]) -> str | None:
    result = compute_latest_change(snapshots)
    if result is None:
        return None
    prev_month, latest_month, rows = result
    lines = [
        f"Latest month vs previous month ({prev_month} -> {latest_month}), already computed -- quote directly, "
        "this is the comparison to use for 'this month' / 'last month' questions:"
    ]
    for r in rows:
        if r.delta == 0:
            lines.append(f"{r.label}: unchanged at ₹{r.latest:,.0f}")
        else:
            direction = "up" if r.delta > 0 else "down"
            lines.append(
                f"{r.label}: ₹{r.previous:,.0f} -> ₹{r.latest:,.0f} ({direction} ₹{abs(r.delta):,.0f})"
            )
    net = next((r for r in rows if r.label.startswith("Net pay")), None)
    if net is not None and net.delta != 0:
        word = "up" if net.delta > 0 else "down"
        lines.append(
            f"Key net pay figures: ₹{net.previous:,.0f} in {prev_month} to "
            f"₹{net.latest:,.0f} in {latest_month} ({word} ₹{abs(net.delta):,.0f})."
        )
    if net is not None and net.delta > 0:
        lines.append(
            "Take-home did NOT drop -- it rose. Name the component rows above that actually "
            "changed as the cause."
        )
    latest_snap = chronological(snapshots)[-1]
    sa, bonus = latest_snap.get("specialAllowance"), latest_snap.get("bonus")
    if _is_number(sa) and _is_number(bonus) and sa > 0 and sa == bonus:
        lines.append(
            f"Data check: Special Allowance and Bonus are both exactly ₹{sa:,.0f} in {latest_month}, "
            "and both are counted in gross pay. This may be one amount entered under both labels; "
            "tell the user to verify it against their payslip."
        )
    return "\n".join(lines)


def latest_change_table(snapshots: list[dict]) -> dict | None:
    result = compute_latest_change(snapshots)
    if result is None:
        return None
    prev_month, latest_month, rows = result
    return {
        "title": f"Latest month vs previous ({prev_month} to {latest_month})",
        "headers": ["Component", prev_month, latest_month, "Change"],
        "rows": [
            [
                r.label,
                f"₹{r.previous:,.0f}",
                f"₹{r.latest:,.0f}",
                "→ no change" if r.delta == 0 else f"{'↑' if r.delta > 0 else '↓'} ₹{abs(r.delta):,.0f}",
            ]
            for r in rows
        ],
    }


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
