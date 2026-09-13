"""
Agent 1 — Payslip Reasoning. Always GPT-4o, never the local-SLM path — see
PROJECT_CONTEXT.md §2 and §14 ("tax calculation errors directly mislead
users, accuracy over cost"). Sees the user's actual decrypted payslip
values; the only agent that does (§4).

When a FinancialProfile is on file, its old-regime deduction total (80C +
80D + 24(b), computed exactly in tax_calculations.py) is handed to this
agent as grounding for regime comparison, rather than left for the model
to estimate from nothing.

Falls back to the most recently saved payslip_history snapshot when no
payslip is active this session (nothing set via "Use this payslip") —
previously this agent only ever looked at payslip_data and said "no
payslip attached" even with months of saved history sitting right there,
which is exactly backwards for a question like "recommend a tax regime."
The fallback itself lives in payslip_trends.resolve_effective_payslip,
shared with agents/nudge_agent.py — both agents need to agree on which
payslip is "current" for a session, since it feeds tax_calculations.py's
80C PF annualization; a mismatch there previously showed up as two
different total-deduction figures for the same question depending on
which agent answered.

When payslip_history has more than one month on file, this agent also gets
the same exact basic/TDS/HRA trend figures payslip_trends.py computes for
the Savings Advisor — reused, not recomputed — so a regime question can
reason across real month-over-month numbers ("has this grown enough to
change the answer") rather than only ever looking at one month in
isolation.

Also computes an actual old-vs-new regime tax liability estimate
(tax_slabs.py — real slab rates, cess, the 87A rebate, marginal relief) —
this used to be explicitly out of scope ("say a precise figure isn't
available here" was the instruction), until a user asked "how much tax do
I have to pay" and the honest-but-unhelpful answer prompted actually
building the calculator rather than continuing to defer. Two caveats
travel with every result rather than staying implicit: which Union Budget
the slab rates are from (they change yearly, and nothing here checks for a
newer one), and whether the annual income feeding it is a real multi-month
sum or a single month extrapolated x12 — tax_slabs.estimate_annual_gross_income
says which, and the prompt requires disclosing it.
"""

import json
import time

from openai import OpenAI

from agents.conversation import format_conversation_for_prompt
from agents.llm_metrics import record_from_response
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from config import config
from payslip_trends import format_trends_for_prompt, resolve_effective_payslip, trends_table
from tax_calculations import compute_all_gaps, gaps_table
from tax_slabs import (
    FY_LABEL,
    cheaper_regime_statement,
    compute_new_regime_tax,
    compute_old_regime_tax,
    estimate_annual_gross_income,
    regime_choice_available,
    tax_liability_table,
)

_client = OpenAI(api_key=config.OPENAI_API_KEY)

# Matches ManualEntryForm.tsx's field labels — used to build a table
# straight from the payslip dict itself, same "compute exactly in Python,
# hand it over pre-solved" reasoning as tax_calculations.py's tables: this
# doesn't need the LLM's own (previously collected, silently discarded by
# the frontend) "component_breakdown" guess when the source values are
# already sitting right here, structured, with nothing to compute.
_COMPONENT_LABELS = {
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


def _components_table(payslip_data: dict) -> dict | None:
    rows = [
        [label, f"₹{payslip_data[key]:,.0f}"]
        for key, label in _COMPONENT_LABELS.items()
        if isinstance(payslip_data.get(key), (int, float)) and not isinstance(payslip_data.get(key), bool)
    ]
    if not rows:
        return None
    month = payslip_data.get("month", "")
    return {"title": f"Payslip components{f' — {month}' if month else ''}", "headers": ["Component", "Amount"], "rows": rows}

_SYSTEM_PROMPT = """You are the Payslip Reasoning Agent inside PayNexus, an Indian payslip \
literacy assistant. You are given one user's actual decrypted payslip components and a \
question about them. Reason step by step over:
- Basic, HRA, Special Allowance, PF (employee + employer), Professional Tax, TDS, Bonus, Reimbursements
- HRA exemption: the least of (actual rent paid minus 10% of basic), (50% of basic in a metro \
  city / 40% elsewhere), (HRA actually received)
- Old vs. new tax regime comparison for this specific salary structure
- Bonus tax impact, Form 16 Part A/B reconciliation, month-on-month pay change

If a "Declared old-regime deductions" figure is given below, it's already computed exactly \
(80C + 80D + 24(b), capped correctly) — use that number directly for regime comparison rather \
than estimating your own. If it isn't given, say the comparison would be more precise with \
declared investments/loans/insurance on file, rather than guessing a deduction total.

If the payslip data below is labeled as coming from saved history rather than the active \
session, say so plainly at the start of your answer (e.g. "Based on your most recently saved \
payslip, July 2026...") — don't present historical data as if it were confirmed for the current \
month.

If a "Payslip trends" section is given (multiple saved months), those basic/TDS/HRA figures are \
already computed exactly — quote them directly, do not recompute. Use them to answer questions \
about how the regime picture has changed over time (e.g. "your basic rose X to Y, so the case for \
maximizing 80C deductions is stronger now than in April").

If a "Tax liability estimate" figure is given below, it's a real computed old-vs-new regime ₹ tax \
figure (exact slab math, cess, the 87A rebate, marginal relief — not a guess) — use it directly \
when asked "how much tax do I owe," "what will I pay," or a regime comparison that wants an \
actual number, not just directional reasoning. A "Regime comparison" line is given right after it \
with the conclusion already worked out (which regime is cheaper, and by how much) — state THAT \
conclusion, do not compare the two totals yourself and derive your own; even correct totals can \
still get the comparison backwards if you re-derive it, which is exactly why this line exists. \
Two things to always disclose when you use the liability figures, in plain language, not buried: \
(1) which financial year's slab rates it's based on — stated in the table's own title, tax rates \
change with every Union Budget and this may not reflect the very latest one; (2) how the annual \
income feeding it was estimated — given in the prompt as the "Income estimation" note; if it says \
"rough estimate," say so, don't present the resulting tax figure as more certain than the income \
estimate underneath it. If no such figure is given (e.g. no \
payslip at all), say a computation needs at least one payslip on file rather than guessing one.

The liability table has several distinct rows — do not conflate them when narrating, especially \
"Taxable income" and "Total tax payable," which are different figures and can move in OPPOSITE \
directions from each other (e.g. the new regime's taxable income can be HIGHER than the old \
regime's — fewer deductions — while its total TAX is still lower, because of a lower rate \
structure and the 87A rebate). Saying a regime results in "zero taxable income" when what's \
actually zero is the tax payable is a real, wrong statement, not a rounding choice — double-check \
which row of the table you're citing before writing the sentence.

Be specific with rupee figures wherever the payslip data supports it. If a figure can't be \
computed from what's given, say what additional input is needed rather than guessing.

Address the user directly throughout, in second person ("you," "your") — never slip into \
third-person ("her," "his," "their," "the user's") mid-answer.

Keep "explanation" to a short narrative — don't restate every rupee figure in prose. A line below \
lists which computed data tables are available this turn by key (e.g. "components", "gaps", \
"trends", "liability") and these render as an actual table in the chat UI; put the "tables" \
field's array keys to whichever are actually relevant (usually one, sometimes two) instead of \
repeating those numbers as prose. E.g. "why did my take-home drop" → ["components"]; "how much \
tax do I owe" or "recommend a regime" with a real number wanted → ["liability"] (add ["gaps"] too \
if the deduction breakdown itself is also relevant, plus ["trends"] if multiple months matter).

Respond with a JSON object: {"explanation": string, "tables": array of table keys (see above), \
"follow_up_suggestions": array of strings}."""


def payslip_agent_node(state: PayNexusState) -> dict:
    payslip_history = state.get("payslip_history") or []
    payslip_data, using_history_fallback = resolve_effective_payslip(state.get("payslip_data") or {}, payslip_history)

    if not payslip_data:
        return {
            "payslip_response": json.dumps(
                {
                    "explanation": "No payslip is attached to this session yet — upload or "
                    "enter one (or save some payslip history) to get a component breakdown.",
                    "follow_up_suggestions": ["Upload a payslip to get started."],
                }
            )
        }

    available_tables: dict[str, dict] = {}
    if (c := _components_table(payslip_data)) is not None:
        available_tables["components"] = c

    prompt_parts = []
    if using_history_fallback:
        prompt_parts.append(
            f"No payslip is active this session — using the most recently saved payslip from "
            f"history instead (month: {payslip_data.get('month', 'unknown')})."
        )
    prompt_parts.append(f"Payslip data (JSON): {json.dumps(payslip_data)}")

    if len(payslip_history) > 1:
        prompt_parts.append("Payslip trends (already computed):\n" + format_trends_for_prompt(payslip_history))
        if (t := trends_table(payslip_history)) is not None:
            available_tables["trends"] = t

    financial_profile = state.get("financial_profile") or {}
    total_deductions = 0.0
    if financial_profile:
        gaps = compute_all_gaps(financial_profile, payslip_data)
        total_deductions = sum(gap.used for gap in gaps)
        prompt_parts.append(f"Declared old-regime deductions (80C + 80D + 24(b), pre-computed): ₹{total_deductions:,}")
        available_tables["gaps"] = gaps_table(gaps)

    # Real old-vs-new regime tax liability — see tax_slabs.py for the slab
    # math and the two caveats (FY basis, income-estimation method) the
    # prompt is required to disclose whenever it uses this.
    annual_income, income_note = estimate_annual_gross_income(payslip_data, payslip_history)
    if annual_income > 0 and not regime_choice_available(payslip_data.get("month")):
        # The new regime didn't exist yet for this payslip's period (see
        # tax_slabs.regime_choice_available) — a real gap found: this
        # codebase would otherwise silently run today's slabs against an
        # old payslip and present a "new regime is cheaper" choice that
        # was never actually available at the time.
        prompt_parts.append(
            f"This payslip is from {payslip_data.get('month')} — the new tax regime didn't exist "
            "yet then (it was introduced in Union Budget 2020, effective FY2020-21/April 2020 "
            "onward). Only the old regime was available for that period. If asked which regime "
            "to choose or to compare regimes, say so plainly — there was no choice to make at "
            "the time — rather than presenting a new-vs-old comparison."
        )
    elif annual_income > 0:
        old_result = compute_old_regime_tax(annual_income, total_deductions)
        new_result = compute_new_regime_tax(annual_income)
        # The actual totals, not just the method note — without this the
        # model has no computed number in its own context to reason from
        # (only a bare "liability" key name), and in testing it responded
        # "no tax liability estimate was provided" despite the table
        # existing, because from its side, nothing proved a number existed.
        prompt_parts.append(
            f"Tax liability estimate (already computed, {FY_LABEL} — quote directly, do not "
            f"recompute). Old regime: gross ₹{old_result.gross_income:,.0f}, taxable income "
            f"₹{old_result.taxable_income:,.0f}, total tax ≈ ₹{old_result.total_tax:,.0f}. New "
            f"regime: gross ₹{new_result.gross_income:,.0f}, taxable income "
            f"₹{new_result.taxable_income:,.0f}, total tax ≈ ₹{new_result.total_tax:,.0f}. These "
            f"are three DIFFERENT figures per regime (gross income, taxable income after "
            f"deductions, and final tax) — keep them distinct; don't call one of them by another's "
            f"name. Income estimation method: {income_note}"
        )
        # The comparison conclusion itself, also pre-computed — not left
        # for the model to derive from the two totals above. Necessary
        # after a real, observed failure: even given both correct totals,
        # the model still inverted the comparison in its own sentence.
        prompt_parts.append(f"Regime comparison (already computed — state this conclusion, do not reverse it): {cheaper_regime_statement(old_result, new_result)}")
        available_tables["liability"] = tax_liability_table(old_result, new_result, income_note)

    conversation_block = format_conversation_for_prompt(state.get("conversation") or [])
    if conversation_block:
        prompt_parts.append(conversation_block)

    prompt_parts.append(
        f"Available data tables this turn (pick relevant keys for your \"tables\" field): "
        f"{list(available_tables.keys())}"
    )
    prompt_parts.append(f"Question: {state['user_query']}")
    user_prompt = "\n\n".join(prompt_parts)

    start = time.perf_counter()
    response = _client.chat.completions.create(
        model=config.PAYSLIP_AGENT_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    metrics = record_from_response(
        agent="payslip_agent", model=config.PAYSLIP_AGENT_MODEL, response=response, latency_ms=latency_ms
    )
    raw = response.choices[0].message.content or "{}"
    return {
        "payslip_response": raw,
        "payslip_tables": resolve_selected_tables(raw, available_tables),
        "payslip_llm_calls": [metrics],
    }
