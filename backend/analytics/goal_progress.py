"""
Goal progress math for GoalTracker (V2). `goals` items are plain dicts
shaped like frontend/src/store/goalStore.ts's Goal — decrypted client-side,
same trust tier as transactions (see agents/state.py's `goals` field):
{name, category, targetAmount, targetDate: "YYYY-MM-DD" | None, savedAmount}.

Computed here in Python and handed to agents/goal_agent.py as
already-correct figures — same "compute exactly, hand it over pre-solved"
pattern as tax_calculations.py, payslip_trends.py, and
analytics/spending_trends.py. The one thing this module does NOT compute:
whether a savings rate is actually achievable, or price/return projections
for market-linked goals (stocks, FDs) — there's no live price-lookup source
wired in yet (see this module's module-level TODO note below); progress
here is target-vs-saved math only, with an optional "at your current
savings rate" projection when transaction data is also available.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# TODO: for market-linked goals (stocks, FDs, mutual funds), progress here
# is savings-contribution math only -- it doesn't account for investment
# returns/appreciation between now and target_date. No live price-lookup
# source is wired into this codebase yet; wire one in (and feed a
# return-rate assumption into compute_goal_progress) before claiming this
# module projects anything beyond "money physically saved so far."


@dataclass
class GoalProgress:
    name: str
    category: str
    target_amount: float
    saved_amount: float
    progress_pct: float  # 0-100, capped at 100 even if saved exceeds target
    target_date: str | None
    days_remaining: int | None  # None if no target_date, or target_date already passed
    required_monthly_savings: float | None  # None if no target_date or already met


def compute_goal_progress(goals: list[dict], today: date | None = None) -> list[GoalProgress]:
    today = today or date.today()
    results = []
    for g in goals:
        target = float(g.get("targetAmount") or 0)
        saved = float(g.get("savedAmount") or 0)
        progress_pct = min(100.0, (saved / target * 100) if target > 0 else 0.0)

        days_remaining = None
        required_monthly = None
        target_date_str = g.get("targetDate")
        if target_date_str:
            try:
                target_date = date.fromisoformat(target_date_str)
                delta_days = (target_date - today).days
                if delta_days > 0:
                    days_remaining = delta_days
                    remaining_amount = max(0.0, target - saved)
                    months_remaining = max(delta_days / 30.44, 1 / 30.44)  # avoid div-by-near-zero
                    required_monthly = remaining_amount / months_remaining
            except ValueError:
                pass  # malformed date — treated the same as no target_date, not an error

        results.append(
            GoalProgress(
                name=str(g.get("name") or "Unnamed goal"),
                category=str(g.get("category") or "Other"),
                target_amount=target,
                saved_amount=saved,
                progress_pct=progress_pct,
                target_date=target_date_str,
                days_remaining=days_remaining,
                required_monthly_savings=required_monthly,
            )
        )
    return results


def format_goals_for_prompt(goals: list[dict], average_monthly_savings: float | None, today: date | None = None) -> str:
    progress = compute_goal_progress(goals, today)
    if not progress:
        return "No goals on file yet — nothing to track."

    lines = [f"{len(progress)} goal(s) on file (already computed — quote directly, do not recompute):"]
    for p in progress:
        line = (
            f"  {p.name} ({p.category}): ₹{p.saved_amount:,.0f} of ₹{p.target_amount:,.0f} saved "
            f"({p.progress_pct:.0f}%)"
        )
        if p.target_date:
            if p.days_remaining is not None:
                line += f" — target {p.target_date}, {p.days_remaining} days away"
                if p.required_monthly_savings is not None:
                    line += f", needs ~₹{p.required_monthly_savings:,.0f}/month to reach on time"
            else:
                line += f" — target date {p.target_date} has passed"
        lines.append(line)

    if average_monthly_savings is not None:
        lines.append(
            f"Average net savings per statement period on file (income minus expenses, already "
            f"computed from saved transactions): ₹{average_monthly_savings:,.0f}. Compare this "
            f"directly against a goal's \"needs ~₹X/month\" figure above to say whether the "
            f"current pace is enough — do not estimate the pace yourself from category totals."
        )
    else:
        lines.append(
            "No transaction data on file to estimate an actual savings rate from — only the "
            "goals' own target math above is available; don't guess at a savings rate."
        )
    return "\n".join(lines)


def months_to_target_at_contribution(remaining_amount: float, extra_monthly_contribution: float) -> float | None:
    """What-If Simulator (V2): "if I contributed ₹X more a month, how long
    until I reach this goal" — deliberately independent of any existing
    savings-rate figure (average_monthly_net_savings needs transaction
    data; this doesn't), since the question is specifically about an
    ADDITIONAL contribution on top of however saving is already happening,
    not a replacement for it. None if the contribution wouldn't make any
    progress at all (zero/negative) — dividing by that would be either
    undefined or a negative "months," neither a real answer."""
    if extra_monthly_contribution <= 0:
        return None
    if remaining_amount <= 0:
        return 0.0  # goal already met
    return remaining_amount / extra_monthly_contribution


def goal_progress_table(goals: list[dict], today: date | None = None) -> dict | None:
    progress = compute_goal_progress(goals, today)
    if not progress:
        return None
    return {
        "title": "Goal progress",
        "headers": ["Goal", "Category", "Saved", "Target", "Progress", "Target date"],
        "rows": [
            [
                p.name,
                p.category,
                f"₹{p.saved_amount:,.0f}",
                f"₹{p.target_amount:,.0f}",
                f"{p.progress_pct:.0f}%",
                p.target_date or "—",
            ]
            for p in progress
        ],
    }
