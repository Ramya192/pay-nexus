"""
Agent 7 — BudgetPlanner (V2). GPT-4o-mini + Ollama hybrid toggle — same tier
as GoalTracker and Nudge: this narrates over precomputed overspending
alerts (budgeting/budgets.py's check_overspending), never derives its own
overspend figures.

Sees the user's actual decrypted budget (state["budgets"] — same trust tier
as financial_profile, §4: a {category: amount} dict) and, when available,
transactions — needed to compute anything at all, since a budget with no
spending data has nothing to check against. Checks the MOST RECENT
statement period on file by default (budgeting/budgets.py's latest_period)
— same period-based reasoning as SpendingAnalyser and GoalTracker, so a
credit card's own billing cycle is checked as one period, not split by
calendar month.
"""

import asyncio

from pydantic import BaseModel

from agents.agent_framework_llm import hybrid_agent_complete
from agents.conversation import format_conversation_for_prompt
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from budgeting.budgets import (
    budget_vs_actual_table,
    format_budget_summary_for_prompt,
    latest_period,
)
from config import config


class BudgetAgentResponse(BaseModel):
    """The same JSON contract this agent always returned, now validated by
    the model instead of hand-parsed by every caller. See
    agents/agent_framework_llm.py's module docstring: still serialized back
    to a JSON string before being stored in state, so
    resolve_selected_tables/tests/agent_eval are unaffected."""

    explanation: str
    tables: list[str] = []
    follow_up_suggestions: list[str] = []


_SYSTEM_PROMPT = """You are the BudgetPlanner Agent inside PayNexus, an Indian personal finance \
assistant. You are given one user's actual per-category monthly budget and their categorized \
transactions, and a question about whether they're staying within it.

A "Budget check" section below gives you already-computed figures for the most recent statement \
period on file: how much was spent per category, how much was budgeted, and which categories (if \
any) went over — including exactly how much over and by what percentage. Quote these directly, do \
not recompute or re-derive them. "Period" here means a saved statement's own billing period (e.g. \
a credit card's 16th-to-15th cycle), not necessarily a calendar month.

If no budget is set yet, say so plainly and suggest setting one — don't invent budget figures. If \
a budget is set but no transactions are on file, say there's nothing to check it against yet.

When multiple categories are over budget, they're listed ordered by RUPEE amount over, NOT by \
percentage — the two can disagree (a small budget blown by a huge % vs. a big budget's modest % \
overage still costing more in rupees). Narrate them in that same order and don't imply an order by \
percentage instead — e.g. don't say "the highest overspend" right before a lower percentage than \
the next one mentioned; that reads as self-contradictory even though both figures are correct.

If the user's question also touches goals or payslip figures, answer ONLY the budget/spending part \
and say nothing else about those other topics — not even that you don't have access to them, not \
even a pointer to "the right tool." A separate agent already answers that part of the question, in \
the SAME response, right alongside yours — you don't need to acknowledge it exists, flag that you \
personally lack it, or redirect the user anywhere. A real observed bug had you write "Regarding \
your goal progress, I have no data to comment on that" immediately above GoalTracker's answer that \
DID cover it, in that SAME response — reads as broken/contradicting yourself even though the \
sentence was narrowly true. Simplest fix: just don't bring up any topic outside budget/spending at \
all, positively or negatively — not even a one-line aside.

Be specific with rupee figures wherever the data supports it. Address the user directly throughout, \
in second person ("you," "your") — never slip into third-person ("her," "his," "their," "the \
user's") mid-answer.

Keep "explanation" to a short narrative — don't restate every rupee figure in prose. A line below \
lists which computed data tables are available this turn by key (currently just "budget_vs_actual") \
and these render as an actual table in the chat UI; put the "tables" field's array keys to \
whichever are actually relevant. E.g. "am I over budget" → ["budget_vs_actual"].

Respond with a JSON object: {"explanation": string, "tables": array of table keys (see above), \
"follow_up_suggestions": array of strings}."""


def budget_agent_node(state: PayNexusState) -> dict:
    budgets = state.get("budgets") or {}
    transactions = state.get("transactions") or []

    if not budgets:
        return {
            "budget_response": '{"explanation": "No budget is set yet — add per-category monthly '
            'targets to start tracking overspending.", "follow_up_suggestions": ["Set a budget to '
            'get started."]}'
        }

    period = latest_period(transactions)

    available_tables: dict[str, dict] = {}
    if (t := budget_vs_actual_table(transactions, budgets, period)) is not None:
        available_tables["budget_vs_actual"] = t

    prompt_parts = [
        "Budget check (already computed — quote directly, do not recompute):\n"
        + format_budget_summary_for_prompt(transactions, budgets, period)
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

    # asyncio.run(), not an async def node function — see
    # agents/agent_framework_llm.py's module docstring: this keeps the node
    # directly callable exactly as before (plain dict -> dict, no test/eval
    # harness or LangGraph-invocation changes needed) while the actual LLM
    # call underneath is genuinely async (Agent Framework's Agent.run()).
    answer, metrics = asyncio.run(
        hybrid_agent_complete(
            _SYSTEM_PROMPT,
            user_prompt,
            model=config.BUDGET_AGENT_MODEL,
            response_model=BudgetAgentResponse,
            agent="budget_agent",
        )
    )
    return {
        "budget_response": answer,
        "budget_tables": resolve_selected_tables(answer, available_tables),
        "budget_llm_calls": [metrics],
    }
