"""
Agent 3 — Financial Nudge. Hybrid GPT-4o-mini / Ollama phi4-mini (§7).
Reads the compressed cross-session summary produced by
compression/context_compressor.py, a trimmed payslip snapshot — never a
full raw payslip (§4) — and, when available, the user's FinancialProfile
(investments/loans/insurance) and saved payslip history.

80C/80D/24(b) gap figures (tax_calculations.py), month-over-month payslip
trends (payslip_trends.py), and old-vs-new regime tax liability
(tax_slabs.py) are all computed exactly in Python and handed to this agent
pre-solved — not left for the LLM to derive. Only things no module covers
(novel patterns, non-numeric judgment calls) still go through the "show
your arithmetic" prompt instruction below.

The liability figures are the same ones agents/payslip_agent.py computes
(same tax_slabs.py functions, same resolve_effective_payslip fallback) —
found as a real bug in testing: before this agent also got them, a
multi-agent "recommend a tax regime" question could have Payslip agent
correctly recommend whichever regime has the lower real total tax, while
this agent independently recommended the *other* regime from deduction-gap
"remaining room" alone (reasoning that unused deduction capacity favors
the old regime — backwards; unused room is capacity not yet realized, not
evidence the old regime is already winning). Two agents contradicting each
other in the same response is far worse than either agent being cautious,
so this agent's regime opinion must now defer to the real liability
numbers whenever they're available, not form an independent one.
"""

import json

from agents.conversation import format_conversation_for_prompt
from agents.llm import hybrid_complete
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from config import config
from payslip_trends import (
    duplicates_table,
    format_duplicates_for_prompt,
    format_trends_for_prompt,
    resolve_effective_payslip,
    trends_table,
)
from tax_calculations import (
    compute_all_gaps,
    financial_profile_table,
    format_financial_profile_for_prompt,
    format_gaps_for_prompt,
    gaps_table,
)
from tax_slabs import (
    FY_LABEL,
    cheaper_regime_statement,
    compute_new_regime_tax,
    compute_old_regime_tax,
    estimate_annual_gross_income,
    regime_choice_available,
    tax_liability_table,
)

_SYSTEM_PROMPT = """You are the Financial Nudge Agent inside PayNexus. You look for patterns \
across a user's payroll history and declared investments — tax-bracket shifts from overtime or \
bonus, regime-switch opportunities, multi-month trends like rising TDS — and proactively suggest \
one specific, actionable next step with an approximate rupee impact. You are given a compressed \
summary of past sessions and a payslip summary, not raw payslips; keep suggestions grounded in \
what's actually there, and say plainly when there isn't enough information yet rather than \
inventing a pattern.

If a section below is labeled "already computed", those figures (deduction gaps, payslip trends) \
are correct by construction — quote them exactly as given, do not recompute or second-guess them. \
For anything else where you state a remaining limit or savings figure yourself, show the \
arithmetic inline as "A - B = C" before the conclusion — e.g. "₹1,50,000 - ₹45,000 = ₹1,05,000 \
remaining." Never state a computed rupee figure without either quoting a precomputed section or \
showing your own working; this is a smaller model and unchecked mental arithmetic is the most \
likely way it gets a real number wrong in front of a user.

If the user is literally asking what they've entered/declared/saved so far — "what have I \
entered", "tell me my savings", "what did I save", "list my investments" and similar — answer \
that directly first: recite the figures from the "Declared investments/loans/insurance, as \
entered" section one by one (field label and rupee amount), in plain prose. Only after that \
direct answer, optionally add a gap/recommendation as a secondary note. Don't skip straight to \
gap analysis and recommendations when the question was actually about what's on file — a user \
asking "what have I entered" wants their own entered numbers read back, not a suggestion.

If the user asks about duplicate payslips/months — "are there duplicates," "check for duplicates," \
"do I have the same month twice" — answer from the "Duplicate-month check" section only, which is \
already computed exactly (including when there's no payslip history at all — that section says so \
plainly, don't independently claim "no duplicates found" if it says no history exists yet, those \
are different answers); don't guess from the raw snapshot count or confuse this with declared \
investments/insurance, which is a separate topic. You can't delete anything yourself — if the user \
wants duplicates removed, say so and point to the "Remove duplicates" button in the Payslip history \
tab, don't offer to do it here (the "Duplicate-month check" section already gives you the exact \
wording for this).

If a "Tax liability estimate" figure is given below, it's a real computed old-vs-new regime ₹ tax
comparison (exact slab math — not a guess), and a "Regime comparison" line right after it already
states the conclusion (which regime is cheaper, by how much) — pre-computed for exactly this
reason: even when both totals are stated correctly, re-deriving "which is smaller" yourself is a
real, observed way to get it backwards. If the question is a regime recommendation ("should I
switch," "recommend a regime," "which is better") and these are available, YOUR RECOMMENDATION
MUST MATCH THE "Regime comparison" LINE EXACTLY — quote its conclusion, do not compare the two
totals yourself and reason to your own conclusion, even though you technically could. Do not form
an independent opinion from deduction-gap "remaining room" alone either — unused deduction capacity
("you still have ₹53,667 left in 80C") is not evidence the old regime is better; it's the opposite,
capacity not yet used. If no liability figure is available, give a deduction-gap-only nudge as
before, but don't state or imply a regime conclusion you can't back with a real number.

For any other deduction-gap suggestion where you'd otherwise want a "≈ ₹X saved annually" framing:
that requires knowing the marginal tax rate applied to it, which even with the liability figure
above isn't a per-deduction number — NEVER state or estimate a rupee amount of tax saved for an
individual deduction suggestion. For the "impact" field there, state the deduction room itself
instead (already computed, in the gaps section) — e.g. "up to ₹2,00,000 additional deduction
available under 24(b)" — never a "saved" framing.

Section 24(b) specifically is NOT something anyone can just go invest into the way 80C/80D work —
it only applies to interest actually paid on a home loan. If you suggest using remaining 24(b)
room, always frame it conditionally ("if you have a home loan, its interest..." / "if you take out
a home loan...") — never present unused 24(b) room as a generic actionable opportunity the way
unused 80C room is, since a user without a home loan can't "utilize" it at all.

Below the prompt sections you're given, a line lists which computed data tables are available this
turn, each with a short key (e.g. "gaps", "profile", "trends", "duplicates", "liability") — these
render as an actual table in the chat UI, so any numbers already in one of them don't need to be
repeated in your prose. Pick only the table(s) actually relevant to the question — usually one,
rarely more than two — and list their keys in the "tables" field. E.g. "what have I entered" →
["profile"]; a duplicates question → ["duplicates"]; a deduction-gap/savings suggestion → ["gaps"];
a trend question → ["trends"]; a regime recommendation with a liability figure available →
["liability"]. Use [] if no available table fits the question.

Respond with a JSON object with exactly these keys: "title" (a short headline, under 8 words),
"detail" (a SHORT narrative — one or two sentences of interpretation/recommendation; the numbers
themselves belong in the table you selected below, not repeated here), "impact" (a short string —
the deduction room available, per above, for a deduction-gap suggestion; a directly-quoted or
show-your-work rupee figure for anything else; or null if there isn't enough information for a
concrete number yet — never fabricate one to fill the field, and never a "tax saved" estimate),
and "tables" (an array of the table keys you're choosing to show, per above — [] if none fit)."""

_SNAPSHOT_FIELDS = ("month", "basic", "tds", "bonus", "regime")


def nudge_agent_node(state: PayNexusState) -> dict:
    history_summary = state.get("session_history") or []
    payslip_history = state.get("payslip_history") or []
    # Same fallback payslip_agent.py uses (and same helper — shared, not
    # reimplemented) — found as a real bug in testing: without this, this
    # agent's 80C/80D/24(b) gap figures were computed from an empty
    # session-active payslip while payslip_agent's were computed from the
    # most recent saved snapshot, so the same conversation stated two
    # different total-deduction figures depending on which agent answered.
    payslip_data, using_history_fallback = resolve_effective_payslip(state.get("payslip_data") or {}, payslip_history)
    payslip_snapshot = _snapshot_only(payslip_data)
    financial_profile = state.get("financial_profile") or {}

    # Every table this turn *could* show, built once here in Python — never
    # by the LLM (see tax_calculations.py/payslip_trends.py's *_table()
    # builders). The model only picks which of these (by key) are relevant
    # to the question; it never sees or produces the numbers themselves.
    available_tables: dict[str, dict] = {}

    prompt_parts = [
        f"Compressed session history: {json.dumps(history_summary)}",
        f"Current payslip snapshot (summary only): {json.dumps(payslip_snapshot)}",
    ]
    if using_history_fallback:
        prompt_parts.append(
            f"No payslip is active this session — the payslip snapshot and deduction gaps above "
            f"use the most recently saved payslip from history instead (month: "
            f"{payslip_data.get('month', 'unknown')}). Say so plainly if it affects your answer."
        )

    # Unconditional, even with an empty payslip_history — both functions
    # below already produce an honest "nothing on file yet" sentence for
    # the empty case (see their own docstrings), and previously being
    # skipped entirely whenever payslip_history was empty is exactly how
    # this went wrong twice in testing: once, asked to verify duplicates,
    # the agent had nothing computed to answer from and answered about
    # financial profile figures instead (a completely different topic);
    # later, with genuinely zero saved payslips, it had no "Duplicate-month
    # check" section to quote at all and improvised "no duplicates found" —
    # true in the vacuous sense, but implying a real check ran against
    # existing history when there wasn't any. The *_table() builders stay
    # conditional on their own return value (None when there's nothing to
    # show), so no misleading empty table appears either way.
    prompt_parts.append("Payslip trends (already computed):\n" + format_trends_for_prompt(payslip_history))
    prompt_parts.append(format_duplicates_for_prompt(payslip_history))
    if (t := trends_table(payslip_history)) is not None:
        available_tables["trends"] = t
    if (d := duplicates_table(payslip_history)) is not None:
        available_tables["duplicates"] = d

    total_deductions = 0.0
    if financial_profile:
        # Raw entered figures first — a question like "what have I entered"
        # or "tell me my savings" needs this, not just the section-level
        # rollups below (₹85,853 "80C used" alone doesn't say how much was
        # life insurance vs. ELSS vs. home loan principal). Found missing
        # in testing: asked directly, the agent had nothing but the gap
        # totals to answer from and said "no specific savings data available"
        # despite a fully filled-out financial profile.
        profile_block = format_financial_profile_for_prompt(financial_profile)
        if profile_block:
            prompt_parts.append(profile_block)
        if (p := financial_profile_table(financial_profile)) is not None:
            available_tables["profile"] = p

        gaps = compute_all_gaps(financial_profile, payslip_data)
        total_deductions = sum(gap.used for gap in gaps)
        prompt_parts.append(
            "Exact deduction gaps (already computed — quote directly, do not recompute):\n"
            + format_gaps_for_prompt(gaps)
        )
        available_tables["gaps"] = gaps_table(gaps)
    else:
        prompt_parts.append(
            "No financial profile on file — no declared investments/loans/insurance to compute "
            "deduction gaps from. If asked about 80C/80D/24(b), say so rather than guessing."
        )

    # Same tax_slabs.py computation agents/payslip_agent.py uses, same
    # inputs (resolve_effective_payslip's payslip_data, total_deductions) —
    # so the two agents can never independently reach different regime
    # conclusions in the same multi-agent response (see module docstring).
    annual_income, income_note = estimate_annual_gross_income(payslip_data, payslip_history)
    if annual_income > 0 and not regime_choice_available(payslip_data.get("month")):
        # Same historical guard as payslip_agent.py — see
        # tax_slabs.regime_choice_available's docstring.
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
        # The comparison conclusion itself, also pre-computed — see this
        # module's docstring for the real, observed failure that made this
        # necessary: even given both correct totals, the model still
        # inverted the comparison in its own sentence ("old regime total
        # tax at ₹92,304 compared to the new regime's zero... switching to
        # the new regime does not provide any financial benefit" — backwards).
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

    answer, metrics = hybrid_complete(
        _SYSTEM_PROMPT, user_prompt, model=config.NUDGE_AGENT_MODEL, json_mode=True, agent="nudge_agent"
    )
    return {
        "nudge_response": answer,
        "nudge_tables": resolve_selected_tables(answer, available_tables),
        "nudge_llm_calls": [metrics],
    }


def _snapshot_only(payslip_data: dict) -> dict:
    """Only the fields pattern detection actually needs — deliberately not
    the full payslip object, so this agent's input stays a summary rather
    than a raw payslip (§4)."""
    return {k: payslip_data[k] for k in _SNAPSHOT_FIELDS if k in payslip_data}
