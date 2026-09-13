"""Two-tier transaction categorization: rules.py's keyword match runs first
(free, deterministic, checked against every transaction), and anything it
can't match falls back to a single batched gpt-4o-mini call rather than one
LLM call per unmatched row.

Adapted from expense-simplifier's rules-first design, but that project also
had a third tier — an online-learning SGDClassifier (categorization/
classifier.py) that improves from live corrections. Deliberately not
ported for the V2 MVP: it needs per-user persisted model state to be worth
anything (a freshly-created model has nothing to learn from, so it would be
strictly worse than the LLM fallback at cold start), and PayNexus has no
existing pattern for persisting a model object per user. Flagged as a
fast-follow once users have enough corrected history to bootstrap it from.
"""

from __future__ import annotations

import json

from openai import OpenAI

from categorization.categories import CATEGORIES
from categorization.rules import apply_rules
from config import config
from models import Transaction

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SYSTEM_PROMPT = f"""Categorize each bank transaction description into exactly one of these \
categories: {", ".join(c for c in CATEGORIES if c != "Uncategorized")}.

Respond with a JSON object: {{"categories": [string, ...]}} — exactly one category per row, in \
the same order the rows were given. Use "Uncategorized" only if truly nothing fits — never \
force a bad match into one of the other categories just to avoid it."""


def categorize_transactions(transactions: list[Transaction]) -> list[Transaction]:
    """Mutates and returns `transactions` — sets category/category_source on
    each. Rules run against every row; only rows rules miss cost an LLM
    call, and those all go in one batched request rather than one per row.
    """
    unmatched_indices = []
    for i, t in enumerate(transactions):
        rule_category = apply_rules(t.description)
        if rule_category is None:
            unmatched_indices.append(i)
        else:
            t.category = rule_category
            t.category_source = "rule"

    if not unmatched_indices:
        return transactions

    user_prompt = "\n".join(f"{row_num}. {transactions[i].description}" for row_num, i in enumerate(unmatched_indices, start=1))
    response = _client.chat.completions.create(
        model=config.SPENDING_CATEGORIZE_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    categories = parsed.get("categories") if isinstance(parsed, dict) else None
    if not isinstance(categories, list):
        categories = []

    for row_num, i in enumerate(unmatched_indices):
        category = categories[row_num] if row_num < len(categories) else None
        if isinstance(category, str) and category in CATEGORIES:
            transactions[i].category = category
            transactions[i].category_source = "llm"
        else:
            transactions[i].category = "Uncategorized"
            transactions[i].category_source = None

    return transactions
