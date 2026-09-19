"""
Agent 8 — Foresight (V2), a.k.a. the What-If Simulator internally (module/
node names below stay `whatif_agent`/`whatif` — the display label the user
sees is "Foresight Agent", set in agents/orchestrator.py's assembler_node,
same "friendly display name, unchanged internal identifier" split as the
Nudge Agent's "Savings Advisor" label). GPT-4o, same tier as Payslip
Reasoning and SpendingAnalyser: a hypothetical that gets acted on is still a
real financial decision, and there's no review step here to soften a wrong
number the way a pre-fill form does.

Extends the one guarantee every other agent already gives real data —
Python computes the exact number, the LLM only narrates it, never invents
one — to hypothetical scenarios. `whatif_extraction.py` (a one-shot
utility call, not a node of its own) turns the user's plain-language "what
if" into a structured override; this node then computes BASELINE vs.
SCENARIO using the exact same functions every other agent already trusts
(tax_slabs.py, tax_calculations.py, budgeting/budgets.py,
analytics/goal_progress.py) — never re-derived, never estimated — and only
narrates the comparison. If extraction found nothing concrete to simulate,
this says so plainly rather than guessing what was meant.

Four independent domains, any combination of which can be active in one
question ("what if I switch regime AND cut my food budget"): tax/regime,
budget, goal, payslip (added 2026-09-15 — a hypothetical change to a
payslip component itself, e.g. "what would my net pay be if I contributed
2% more to PF," distinct from the tax domain's additional_80c/80d/24b,
which model EXTERNAL investments/insurance rather than a payroll deduction
that also changes net pay). Each domain's helper below returns
(prompt_text, table) or None — None either because that domain wasn't
asked about, or because it was asked about but there's no data to compute
against (still handled with
an honest, plain sentence, not a None-shaped silence).
"""

import asyncio
import json

from pydantic import BaseModel

from agents.agent_framework_llm import agent_complete
from agents.conversation import format_conversation_for_prompt
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from analytics.goal_progress import (
    compute_goal_progress,
    months_to_target_at_contribution,
)
from budgeting.budgets import latest_period, simulate_category_adjustment
from config import config
from payslip_math import GROSS_PAY_FIELDS, apply_field_change, compute_gross_pay, compute_net_pay, field_label
from payslip_trends import resolve_effective_payslip
from tax_calculations import compute_all_gaps
from tax_slabs import (
    FY_LABEL,
    cheaper_regime_statement,
    compute_new_regime_tax,
    compute_old_regime_tax,
    estimate_annual_gross_income,
    regime_choice_available,
)
from whatif_extraction import extract_scenario, has_any_signal


class WhatIfAgentResponse(BaseModel):
    """See agents/agent_framework_llm.py's module docstring. Covers this
    node's own final narration call — whatif_extraction.py's separate
    one-shot extract_scenario() call now also goes through agent_complete()
    (migrated 2026-09-12, see that module's own docstring), just with its
    own response model (_ExtractedScenario), since it's a different call
    with a different shape, not this one."""

    explanation: str
    tables: list[str] = []
    follow_up_suggestions: list[str] = []

_SYSTEM_PROMPT = """You are the Foresight Agent inside PayNexus, an Indian personal finance \
assistant — you explore hypothetical "what if" scenarios. You are given one or more computed \
BASELINE-vs-SCENARIO comparisons for a \
hypothetical the user asked about (switching tax regime, adding to a deduction section, cutting \
or raising a budget category, contributing more to a savings goal, changing a payslip component \
like PF/basic/HRA) and a question about it.

Every figure below is already computed exactly — quote baseline and scenario figures directly, \
state the delta between them, and never recompute, re-derive, or estimate either number yourself. \
If a section says data is missing (no payslip, no budget, no transactions, no goal by that name), \
say so plainly rather than guessing what the answer would be.

This is a hypothetical, not the user's real saved state — be clear in your answer that you're \
describing what WOULD happen, not what already has. Never claim a scenario was actually saved or \
applied; nothing here changes anything on file.

Address the user directly throughout, in second person ("you," "your") — never slip into \
third-person ("her," "his," "their," "the user's") mid-answer.

Keep "explanation" to a short narrative — don't restate every rupee figure in prose. A line below \
lists which computed data tables are available this turn by key (e.g. "tax_scenario", \
"budget_scenario", "goal_scenario", "payslip_scenario") and these render as an actual table in the \
chat UI; put the "tables" field's array keys to whichever are actually relevant to what was asked. \
A "payslip_scenario" table's Net Pay row is the answer whenever the question asks what net pay/ \
take-home WOULD BE under a hypothetical payslip change — quote that computed figure directly, \
never estimate what a component change "should" do to net pay yourself.

Respond with a JSON object: {"explanation": string, "tables": array of table keys (see above), \
"follow_up_suggestions": array of strings}."""


def whatif_agent_node(state: PayNexusState) -> dict:
    goals = state.get("goals") or []
    goal_names = [g["name"] for g in goals if isinstance(g.get("name"), str)]
    conversation = state.get("conversation") or []

    scenario, extraction_metrics = asyncio.run(extract_scenario(state["user_query"], conversation, goal_names))

    if not has_any_signal(scenario):
        # extraction_metrics is included even here — this IS the only real
        # (billed) call this turn makes; leaving it out (the old behavior)
        # made a genuine extraction cost invisible in token_usage. See
        # whatif_extraction.py's module docstring for the full story.
        return {
            "scenario_response": json.dumps(
                {
                    "explanation": "That question wasn't specific enough to simulate — give a "
                    "concrete number, e.g. \"what if I added ₹50,000 to my ELSS\" or \"what if I "
                    "cut my Food & Dining budget by ₹1,000.\"",
                    "follow_up_suggestions": [],
                }
            ),
            "scenario_llm_calls": [extraction_metrics],
        }

    payslip_history = state.get("payslip_history") or []
    payslip_data, _ = resolve_effective_payslip(state.get("payslip_data") or {}, payslip_history)

    prompt_parts: list[str] = []
    available_tables: dict[str, dict] = {}

    for domain_result, key in (
        (_simulate_tax_scenario(scenario, payslip_data, payslip_history, state.get("financial_profile") or {}), "tax_scenario"),
        (_simulate_budget_scenario(scenario, state.get("transactions") or [], state.get("budgets") or {}), "budget_scenario"),
        (_simulate_goal_scenario(scenario, goals), "goal_scenario"),
        (_simulate_payslip_scenario(scenario, payslip_data, payslip_history, state.get("financial_profile") or {}), "payslip_scenario"),
    ):
        if domain_result is None:
            continue
        text, table = domain_result
        prompt_parts.append(text)
        if table is not None:
            available_tables[key] = table

    conversation_block = format_conversation_for_prompt(conversation)
    if conversation_block:
        prompt_parts.append(conversation_block)

    prompt_parts.append(
        f"Available data tables this turn (pick relevant keys for your \"tables\" field): "
        f"{list(available_tables.keys())}"
    )
    prompt_parts.append(f"Question: {state['user_query']}")
    user_prompt = "\n\n".join(prompt_parts)

    raw, metrics = asyncio.run(
        agent_complete(
            _SYSTEM_PROMPT,
            user_prompt,
            model=config.WHATIF_AGENT_MODEL,
            response_model=WhatIfAgentResponse,
            agent="whatif_agent",
        )
    )
    return {
        "scenario_response": raw,
        "scenario_tables": resolve_selected_tables(raw, available_tables),
        "scenario_llm_calls": [extraction_metrics, metrics],
    }


def _simulate_tax_scenario(
    scenario: dict, payslip_data: dict, payslip_history: list[dict], financial_profile: dict
) -> tuple[str, dict | None] | None:
    delta = (scenario["additional_80c"] or 0) + (scenario["additional_80d"] or 0) + (scenario["additional_24b"] or 0)
    if not scenario["regime_switch"] and not delta:
        return None
    if not payslip_data:
        return "No payslip is on file — a tax regime/deduction scenario needs one to compute against.", None

    annual_income, income_note = estimate_annual_gross_income(payslip_data, payslip_history)
    if annual_income <= 0:
        return "No usable payslip figures on file to estimate annual income from.", None

    if scenario["regime_switch"] and not regime_choice_available(payslip_data.get("month")):
        # Same historical guard as payslip_agent.py/nudge_agent.py — see
        # tax_slabs.regime_choice_available's docstring. Only blocks the
        # regime-switch half of a scenario; a pure deduction what-if
        # (80C/80D/24b) still applies within the old regime, which did
        # exist, so isn't gated by this.
        return (
            f"This payslip is from {payslip_data.get('month')} — the new tax regime didn't exist "
            "yet then (it was introduced in Union Budget 2020, effective FY2020-21/April 2020 "
            "onward). There was no regime to switch to at the time, so that part isn't something "
            "to simulate for this payslip's period."
        ), None

    gaps = compute_all_gaps(financial_profile, payslip_data) if financial_profile else []
    baseline_deductions = sum(g.used for g in gaps)
    scenario_deductions = baseline_deductions + delta

    baseline_old = compute_old_regime_tax(annual_income, baseline_deductions)
    scenario_old = compute_old_regime_tax(annual_income, scenario_deductions) if delta else baseline_old
    new_result = compute_new_regime_tax(annual_income)

    lines = [
        f"Tax scenario (already computed, {FY_LABEL}, income basis: {income_note}):",
        (
            f"  Baseline — old regime: deductions ₹{baseline_deductions:,.0f}, total tax ₹{baseline_old.total_tax:,.0f}. "
            f"New regime: total tax ₹{new_result.total_tax:,.0f}."
        ),
    ]
    if delta:
        savings = baseline_old.total_tax - scenario_old.total_tax
        lines.append(
            f"  Scenario — an additional ₹{delta:,.0f} in deductions: old-regime deductions become "
            f"₹{scenario_deductions:,.0f}, total tax ₹{scenario_old.total_tax:,.0f} "
            f"(₹{savings:,.0f} {'less' if savings >= 0 else 'more'} than baseline old-regime tax)."
        )
    if scenario["regime_switch"]:
        lines.append(f"  Regime comparison at baseline deductions (already computed — state this conclusion, do not reverse it): {cheaper_regime_statement(baseline_old, new_result)}")

    table = {
        "title": "What-if: tax scenario",
        "headers": ["", "Baseline (Old Regime)", "Scenario (Old Regime)", "New Regime"],
        "rows": [
            ["Deductions", f"₹{baseline_deductions:,.0f}", f"₹{scenario_deductions:,.0f}", "—"],
            ["Total tax", f"₹{baseline_old.total_tax:,.0f}", f"₹{scenario_old.total_tax:,.0f}", f"₹{new_result.total_tax:,.0f}"],
        ],
    }
    return "\n".join(lines), table


def _simulate_budget_scenario(scenario: dict, transactions: list[dict], budgets: dict) -> tuple[str, dict | None] | None:
    category = scenario["budget_category"]
    delta = scenario["budget_delta"]
    if not category or not delta:
        return None
    if not budgets:
        return "No budget is set yet — nothing to compare a spending change against.", None

    period = latest_period(transactions)
    if not period:
        return "No transactions on file yet — nothing to compare a spending change against.", None

    result = simulate_category_adjustment(transactions, budgets, period, category, delta)
    if result is None:
        return f'"{category}" isn\'t in your budget — nothing to simulate.', None

    direction = "cutting" if delta < 0 else "raising"
    baseline_status = f"OVER by ₹{result['actual_over_by']:,.0f}" if result["actual_over_by"] else "within budget"
    scenario_status = f"OVER by ₹{result['scenario_over_by']:,.0f}" if result["scenario_over_by"] else "within budget"
    lines = [
        f"Budget scenario for {category}, period {period} (already computed):",
        f"  Baseline: ₹{result['actual_spent']:,.0f} spent vs ₹{result['budget']:,.0f} budgeted ({baseline_status}).",
        f"  Scenario ({direction} by ₹{abs(delta):,.0f}): ₹{result['scenario_spent']:,.0f} spent ({scenario_status}).",
    ]
    table = {
        "title": f"What-if: {category} budget",
        "headers": ["", "Spent", "Budget", "Status"],
        "rows": [
            ["Baseline", f"₹{result['actual_spent']:,.0f}", f"₹{result['budget']:,.0f}", "Over" if result["actual_over_by"] else "OK"],
            ["Scenario", f"₹{result['scenario_spent']:,.0f}", f"₹{result['budget']:,.0f}", "Over" if result["scenario_over_by"] else "OK"],
        ],
    }
    return "\n".join(lines), table


def _simulate_goal_scenario(scenario: dict, goals: list[dict]) -> tuple[str, dict | None] | None:
    goal_name = scenario["goal_name"]
    extra = scenario["goal_extra_monthly"]
    if not goal_name or not extra:
        return None

    goal = next((g for g in goals if g.get("name") == goal_name), None)
    if goal is None:
        return f'No saved goal named "{goal_name}" found.', None

    progress = compute_goal_progress([goal])[0]
    remaining = max(0.0, progress.target_amount - progress.saved_amount)
    months = months_to_target_at_contribution(remaining, extra)

    lines = [
        (
            f'Goal scenario for "{goal_name}" (already computed): ₹{remaining:,.0f} remaining to reach '
            f"₹{progress.target_amount:,.0f} (₹{progress.saved_amount:,.0f} already saved)."
        )
    ]
    if months == 0:
        lines.append("Already fully funded — no additional contribution needed.")
    elif months is not None:
        lines.append(f"At an extra ₹{extra:,.0f}/month on top of whatever's already being saved, this goal would be reached in about {months:.1f} months.")

    table = {
        "title": f"What-if: {goal_name}",
        "headers": ["", "Value"],
        "rows": [
            ["Remaining amount", f"₹{remaining:,.0f}"],
            ["Extra monthly contribution", f"₹{extra:,.0f}"],
            ["Months to reach goal", f"{months:.1f}" if months is not None else "—"],
        ],
    }
    return "\n".join(lines), table


def _simulate_payslip_scenario(
    scenario: dict, payslip_data: dict, payslip_history: list[dict], financial_profile: dict
) -> tuple[str, dict | None] | None:
    """The domain that answers "what would my net pay be if I changed X on
    my payslip" — added 2026-09-15, see payslip_math.py's module docstring
    for the real gap this closes. Distinct from _simulate_tax_scenario's
    additional_80c/80d/24b: those model EXTERNAL investments/insurance a
    user adds on top of their existing salary (never touching net pay);
    this models an actual change to a payslip component — always affects
    net pay, and for PF specifically also affects the old-regime 80C pool.
    """
    field = scenario["payslip_field"]
    if not field:
        return None
    if not payslip_data:
        return "No payslip is on file — a payslip scenario needs one to compute against.", None

    change = apply_field_change(
        payslip_data,
        field,
        new_value=scenario["payslip_new_value"],
        delta_amount=scenario["payslip_delta_amount"],
        delta_percent_of_basic=scenario["payslip_delta_percent_of_basic"],
    )
    if change is None:
        return f"\"{field}\" isn't a payslip component this can simulate a change to.", None

    baseline_net = compute_net_pay(payslip_data)
    scenario_net = compute_net_pay(change.scenario_payslip)
    net_delta = scenario_net - baseline_net
    direction = "more" if net_delta > 0 else "less" if net_delta < 0 else "the same as"

    lines = [
        f"Payslip scenario — {field_label(field)}: ₹{change.baseline_value:,.0f} → ₹{change.scenario_value:,.0f}.",
        f"Net pay (already computed): ₹{baseline_net:,.0f} (baseline) → ₹{scenario_net:,.0f} (scenario) — "
        f"₹{abs(net_delta):,.0f} {direction} per month.",
    ]
    table_rows = [
        [field_label(field), f"₹{change.baseline_value:,.0f}", f"₹{change.scenario_value:,.0f}"],
        ["Net pay (computed)", f"₹{baseline_net:,.0f}", f"₹{scenario_net:,.0f}"],
    ]

    # A change to a field that feeds annual gross income (basic/HRA/special
    # allowance/bonus) or the old-regime 80C pool (PF) also moves old-
    # regime tax liability — a real second effect, not just net pay. The
    # old regime itself always applies regardless of payslip period (unlike
    # a regime-SWITCH scenario, which regime_choice_available() gates
    # elsewhere) — this only ever computes old-regime tax, never a switch.
    if field in GROSS_PAY_FIELDS or field == "pfEmployee":
        annual_income, income_note = estimate_annual_gross_income(payslip_data, payslip_history)
        if annual_income > 0:
            # This monthly change, applied for a full 12 months on top of
            # whatever the existing annual estimate already is — the same
            # kind of explicit, stated assumption estimate_annual_gross_
            # income() itself already makes for a single month extrapolated
            # x12, not a new precision claim this scenario invents.
            monthly_gross_delta = compute_gross_pay(change.scenario_payslip) - compute_gross_pay(payslip_data)
            scenario_annual_income = annual_income + monthly_gross_delta * 12

            gaps = compute_all_gaps(financial_profile, payslip_data) if financial_profile else []
            baseline_deductions = sum(g.used for g in gaps)
            scenario_gaps = compute_all_gaps(financial_profile, change.scenario_payslip) if financial_profile else []
            scenario_deductions = sum(g.used for g in scenario_gaps)

            baseline_old = compute_old_regime_tax(annual_income, baseline_deductions)
            scenario_old = compute_old_regime_tax(scenario_annual_income, scenario_deductions)
            tax_delta = scenario_old.total_tax - baseline_old.total_tax
            tax_direction = "more" if tax_delta > 0 else "less" if tax_delta < 0 else "the same as"
            assumption_note = " (assuming this change applies for the full year)" if monthly_gross_delta else ""

            lines.append(
                f"Old-regime tax liability ({FY_LABEL}, income basis: {income_note}{assumption_note}): "
                f"₹{baseline_old.total_tax:,.0f} → ₹{scenario_old.total_tax:,.0f} — "
                f"₹{abs(tax_delta):,.0f} {tax_direction} per year."
            )
            table_rows.append(
                ["Old-regime tax (computed)", f"₹{baseline_old.total_tax:,.0f}", f"₹{scenario_old.total_tax:,.0f}"]
            )

    table = {
        "title": f"What-if: payslip — {field_label(field)}",
        "headers": ["", "Baseline", "Scenario"],
        "rows": table_rows,
    }
    return "\n".join(lines), table
