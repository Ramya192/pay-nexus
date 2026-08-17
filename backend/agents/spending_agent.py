"""
Agent 5 — SpendingAnalyser (V2). GPT-4o, same tier as Payslip Reasoning —
see config.py's V2 section: this agent narrates over transactions already
saved to a session, live in conversation with no review step, same "wrong
numbers directly mislead the user" reasoning that keeps Payslip Reasoning
off the cheaper/local-SLM path.

Sees the user's actual decrypted, categorized transactions (state
["transactions"] — same trust tier as payslip_data, §4): decrypted
client-side from every saved BankStatement, sent plaintext for this request
only, never stored plaintext. Categorization itself already happened before
a statement was ever saved (categorization/categorize.py, at
POST /statement/parse time) — this agent only narrates over the result, it
never re-categorizes or re-derives a transaction's category.

All figures (category totals, period-over-period trend, recurring
merchants) are computed exactly in Python (analytics/spending_trends.py,
analytics/recurring.py) and hand the model already-correct numbers to
quote — same "compute exactly, hand it over pre-solved" pattern as
tax_calculations.py / payslip_trends.py, and the same reason payslip_agent.py
gives Payslip Reasoning its liability/gaps tables instead of letting the
model estimate them.

"Period" here means a saved statement's own period_label (e.g. a credit
card's 16th-to-15th billing cycle), not necessarily a calendar month — see
analytics/spending_trends.py's module docstring for why grouping this way
instead of by calendar month matters for a real statement.
"""

import time

from openai import OpenAI

from agents.conversation import format_conversation_for_prompt
from agents.llm_metrics import record_from_response
from agents.state import PayNexusState
from agents.tables import resolve_selected_tables
from analytics.recurring import recurring_merchants_table, subscriptions_table
from analytics.spending_trends import (
    category_period_trend_table,
    format_spending_summary_for_prompt,
    period_trend_table,
    spending_by_category_table,
)
from config import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SYSTEM_PROMPT = """You are the SpendingAnalyser Agent inside PayNexus, an Indian personal \
finance assistant. You are given one user's actual categorized bank transactions (from their \
saved statements) and a question about their spending.

A "Spending summary" section below gives you already-computed totals: overall spend, spend by \
category, and (when at least two statement periods are on file) a period-over-period trend — a \
"period" is the billing period each saved statement covers (e.g. a bank statement's calendar \
month, or a credit card's own 16th-to-15th cycle), not always a calendar month, so don't assume \
one when narrating it. Quote these figures directly, do not recompute or re-derive them. If a \
"Recurring merchants" figure is given, those are merchants that charged more than once in the \
loaded statements, already computed exactly. A separate "Recurring subscriptions" figure, when \
given, is the same idea narrowed to merchants already categorized "Subscriptions" — use that one \
specifically for "what subscriptions am I paying for," not the broader recurring-merchants list, \
which would mix in a grocery store or ride-hailing app charged twice and nobody would call either \
one a subscription.

Categories were assigned before this conversation started (keyword rules first, an LLM fallback \
for anything rules missed) — never re-categorize a transaction yourself or contradict its given \
category; if a category looks wrong to you, say so as an aside rather than silently using a \
different one in your answer.

Be specific with rupee figures wherever the transaction data supports it. If no transactions are \
on file yet, say so and suggest uploading a bank statement — don't guess at spending patterns \
from nothing.

Address the user directly throughout, in second person ("you," "your") — never slip into \
third-person ("her," "his," "their," "the user's") mid-answer.

Keep "explanation" to a short narrative — don't restate every rupee figure in prose. A line below \
lists which computed data tables are available this turn by key (e.g. "by_category", \
"period_trend", "category_trend", "recurring", "subscriptions") and these render as an actual \
table in the chat UI; put the "tables" field's array keys to whichever are actually relevant \
instead of repeating those numbers as prose. E.g. "where is my money going" → ["by_category"]; \
"is my spending going up overall" → ["period_trend"]; "is my food spending going up specifically" \
→ ["category_trend"] (period_trend is all categories combined — use category_trend, not \
period_trend, for a question about ONE category's trend); "what subscriptions am I paying for" \
→ ["subscriptions"] if that key is available (if it's NOT available — no Subscriptions-category \
merchant repeated — say plainly that no recurring subscription was found, do not fall back to the \
broader "recurring" list, which isn't the same thing); "what are my recurring charges/expenses" \
(no specific mention of subscriptions) → ["recurring"]. If "category_trend" doesn't include the \
category asked about, say plainly that there isn't enough data for that specific category yet \
rather than answering from the all-categories period trend.

Respond with a JSON object: {"explanation": string, "tables": array of table keys (see above), \
"follow_up_suggestions": array of strings}."""


def spending_agent_node(state: PayNexusState) -> dict:
    transactions = state.get("transactions") or []

    if not transactions:
        return {
            "spending_response": '{"explanation": "No bank statements are on file yet — upload '
            'one to get a spending breakdown.", "follow_up_suggestions": ["Upload a bank '
            'statement to get started."]}'
        }

    available_tables: dict[str, dict] = {}
    if (t := spending_by_category_table(transactions)) is not None:
        available_tables["by_category"] = t
    if (t := period_trend_table(transactions)) is not None:
        available_tables["period_trend"] = t
    if (t := category_period_trend_table(transactions)) is not None:
        available_tables["category_trend"] = t
    if (t := recurring_merchants_table(transactions)) is not None:
        available_tables["recurring"] = t
    if (t := subscriptions_table(transactions)) is not None:
        available_tables["subscriptions"] = t

    prompt_parts = [
        "Spending summary (already computed — quote directly, do not recompute):\n"
        + format_spending_summary_for_prompt(transactions)
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

    start = time.perf_counter()
    response = _client.chat.completions.create(
        model=config.SPENDING_AGENT_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    metrics = record_from_response(
        agent="spending_agent", model=config.SPENDING_AGENT_MODEL, response=response, latency_ms=latency_ms
    )
    raw = response.choices[0].message.content or "{}"
    return {
        "spending_response": raw,
        "spending_tables": resolve_selected_tables(raw, available_tables),
        "spending_llm_calls": [metrics],
    }
