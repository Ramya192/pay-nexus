"""
Agent 8 — Monthly Digest. Cloud-only gpt-4o (same tier as Payslip/
SpendingAnalyser/Foresight — no Ollama toggle), since this synthesizes
across every domain and deserves accuracy over cost.

Built as the deliberate alternative to generic document/statement-level
summarization, which was explicitly rejected (see
paynexus-v2-pending-items.md's roadmap item 3f) for conflicting with this
app's core principle that every number traces to a Python function, never
an LLM's arithmetic — an LLM summarizing a raw bank statement risks
paraphrasing or rounding real figures. This agent never sees a raw
statement; it only synthesizes ALREADY-COMPUTED structured outputs from
the other four domains (payslip trends, spending, budget, goals) into one
flowing "how did this period go" narrative. The numbers still come from
Python (payslip_trends.py, analytics/spending_trends.py, budgeting/
budgets.py, analytics/goal_progress.py) — this agent only weaves them
together; it's a synthesis layer, not a second source of truth for any
figure.

Deliberately selected ALONE by the intent classifier, never combined with
other agents (see orchestrator.py's _INTENT_SYSTEM_PROMPT) — a digest
already covers what payslip/spending/budget/goal each answer individually,
so combining it with them would just repeat the same figures twice in one
response.
"""

import asyncio

from pydantic import BaseModel

from agents.agent_framework_llm import agent_complete
from agents.conversation import format_conversation_for_prompt
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from analytics.goal_progress import format_goals_for_prompt, goal_progress_table
from analytics.spending_trends import (
    average_monthly_net_savings,
    format_spending_summary_for_prompt,
    spending_by_category_table,
)
from budgeting.budgets import budget_vs_actual_table, format_budget_summary_for_prompt, latest_period
from config import config
from payslip_trends import format_trends_for_prompt, trends_table

_SYSTEM_PROMPT = """You are PayNexus's Monthly Digest — you write ONE short, flowing recap of how \
the user's finances went, synthesizing payslip trends, spending, budget, and savings-goal progress \
into a single narrative. You are NOT a fifth independent source of numbers: every figure below is \
already computed exactly by Python — quote it directly, never recompute or re-derive anything, and \
never state a number that isn't given to you below.

Write ONE cohesive recap, not four separate labeled sections stapled together — a real paragraph \
(or two, if there's a lot to cover) that flows from one topic to the next, the way a person would \
actually summarize their own month out loud. Do not use section headers like "Payslip:" or \
"Spending:" — that's what a lazy concatenation looks like, and defeats the entire point of this \
agent existing instead of just running all four agents separately.

If a section below says there's no data for that area yet (e.g. "no expense transactions on file \
yet", "no goals on file yet"), simply don't mention that area at all — never say "no data was \
available for X" or "I don't have information about Y." A recap that only covers what's actually \
there reads as complete; one that lists its own gaps reads as an apology. Only write about what you \
were actually given.

Below the sections, a line lists which computed data tables are available this turn, each with a \
short key — these render as an actual table in the chat UI. Pick only the ones genuinely worth \
highlighting (rarely more than two — this is a recap, not a data dump) and list their keys in the \
"tables" field; [] is a completely valid answer if the narrative alone covers it well.

Respond with a JSON object with exactly these keys: "explanation" (the recap itself, 2-4 sentences \
unless there's genuinely a lot of ground to cover) and "tables" (an array of the table keys you're \
choosing to show, per above)."""


class DigestAgentResponse(BaseModel):
    explanation: str
    tables: list[str] = []


def digest_agent_node(state: PayNexusState) -> dict:
    payslip_history = state.get("payslip_history") or []
    transactions = state.get("transactions") or []
    goals = state.get("goals") or []
    budgets = state.get("budgets") or {}

    available_tables: dict[str, dict] = {}
    prompt_parts = [
        "Payslip trends (already computed):\n" + format_trends_for_prompt(payslip_history),
        "Spending summary (already computed):\n" + format_spending_summary_for_prompt(transactions),
    ]
    if (t := trends_table(payslip_history)) is not None:
        available_tables["trends"] = t
    if (t := spending_by_category_table(transactions)) is not None:
        available_tables["spending_by_category"] = t

    if budgets:
        period = latest_period(transactions)
        prompt_parts.append(
            "Budget check (already computed):\n" + format_budget_summary_for_prompt(transactions, budgets, period)
        )
        if (t := budget_vs_actual_table(transactions, budgets, period)) is not None:
            available_tables["budget_vs_actual"] = t

    avg_savings = average_monthly_net_savings(transactions)
    prompt_parts.append("Goals (already computed):\n" + format_goals_for_prompt(goals, avg_savings))
    if (t := goal_progress_table(goals)) is not None:
        available_tables["goal_progress"] = t

    conversation_block = format_conversation_for_prompt(state.get("conversation") or [])
    if conversation_block:
        prompt_parts.append(conversation_block)

    prompt_parts.append(
        f"Available data tables this turn (pick relevant keys for your \"tables\" field): "
        f"{list(available_tables.keys())}"
    )
    prompt_parts.append(f"Question: {state['user_query']}")
    user_prompt = "\n\n".join(prompt_parts)

    answer, metrics = asyncio.run(
        agent_complete(
            _SYSTEM_PROMPT,
            user_prompt,
            model=config.DIGEST_AGENT_MODEL,
            response_model=DigestAgentResponse,
            agent="digest_agent",
        )
    )
    return {
        "digest_response": answer,
        "digest_tables": resolve_selected_tables(answer, available_tables),
        "digest_llm_calls": [metrics],
    }
