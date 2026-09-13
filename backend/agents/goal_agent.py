"""
Agent 6 — GoalTracker (V2). GPT-4o-mini + Ollama hybrid toggle (config.py's
GOAL_AGENT_MODEL) — same tier as the Nudge and Regulatory agents: this
narrates over precomputed target-vs-saved math (analytics/goal_progress.py),
never derives its own numbers, so a smaller/local model is fine here the
same way it's fine for Nudge's deduction-gap narration.

Sees the user's actual decrypted goals (state["goals"] — same trust tier as
transactions, §4) and, when available, transactions — used only to derive
an actual average savings rate (analytics/spending_trends.py's
average_monthly_net_savings) to compare against what each goal's target
date requires. Goals work fine with no transaction data at all; the
savings-rate comparison is an enhancement, not a requirement.

Not yet built, called out explicitly rather than silently skipped: live
market price lookups for market-linked goals (a stock or FD-backed goal's
actual projected growth, not just a flat savings target) — there's no
instrument-type field on a goal yet and no price-lookup source wired in.
Every goal is treated as a flat cash target for now.
"""

from agents.conversation import format_conversation_for_prompt
from agents.llm import hybrid_complete
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from analytics.goal_progress import format_goals_for_prompt, goal_progress_table
from analytics.spending_trends import average_monthly_net_savings
from config import config

_SYSTEM_PROMPT = """You are the GoalTracker Agent inside PayNexus, an Indian personal finance \
assistant. You are given one user's actual savings goals (Trip, Home Loan, Education, Emergency \
Fund, Retirement, or a custom "Other" goal) and a question about their progress.

A "Goals" section below gives you already-computed figures per goal: amount saved, target amount, \
progress percentage, and — when a target date is set — days remaining and the monthly savings \
pace required to reach it on time. Quote these directly, do not recompute or re-derive them. If an \
average monthly net savings figure is also given (computed from the user's saved bank transactions, \
income minus expenses), compare it directly against a goal's required pace to say whether the \
current rate is enough — do not estimate a savings rate yourself from anything else.

Every goal here is treated as a flat cash target — there is no live stock/FD price tracking yet, so \
never claim a specific investment return or project market growth; if asked about a market-linked \
goal's real growth, say that live price tracking isn't available yet rather than estimating one.

Be specific with rupee figures wherever the goal data supports it. If no goals are on file yet, say \
so and suggest adding one — don't invent a goal or a progress figure from nothing.

If the user's question also touches spending, budget, or payslip figures, answer ONLY the goal \
part and say nothing else about those other topics — not even that you don't have access to them, \
not even a pointer to "the right tool." A separate agent already answers that part of the question, \
in the SAME response, right alongside yours — you don't need to acknowledge it exists, flag that \
you personally lack it, or redirect the user anywhere. Simplest fix: just don't bring up any topic \
outside goals at all, positively or negatively.

Address the user directly throughout, in second person ("you," "your") — never slip into \
third-person ("her," "his," "their," "the user's") mid-answer.

Keep "explanation" to a short narrative — don't restate every rupee figure in prose. A line below \
lists which computed data tables are available this turn by key (currently just "progress") and \
these render as an actual table in the chat UI; put the "tables" field's array keys to whichever \
are actually relevant. E.g. "how am I doing on my goals" → ["progress"].

Respond with a JSON object: {"explanation": string, "tables": array of table keys (see above), \
"follow_up_suggestions": array of strings}."""


def goal_agent_node(state: PayNexusState) -> dict:
    goals = state.get("goals") or []

    if not goals:
        return {
            "goal_response": '{"explanation": "No savings goals are on file yet — add one (a '
            'trip, a home loan down payment, anything) to start tracking progress toward it.", '
            '"follow_up_suggestions": ["Add a goal to get started."]}'
        }

    transactions = state.get("transactions") or []
    savings_rate = average_monthly_net_savings(transactions) if transactions else None

    available_tables: dict[str, dict] = {}
    if (t := goal_progress_table(goals)) is not None:
        available_tables["progress"] = t

    prompt_parts = [
        "Goals (already computed — quote directly, do not recompute):\n"
        + format_goals_for_prompt(goals, savings_rate)
    ]

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
        _SYSTEM_PROMPT, user_prompt, model=config.GOAL_AGENT_MODEL, json_mode=True, agent="goal_agent"
    )
    return {
        "goal_response": answer,
        "goal_tables": resolve_selected_tables(answer, available_tables),
        "goal_llm_calls": [metrics],
    }
