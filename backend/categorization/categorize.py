"""Three-tier transaction categorization: rules.py's keyword match runs
first (free, deterministic, checked against every transaction), then a
confidence-gated logistic regression pass (ml_classifier.py), and only what
both tiers miss falls back to a single batched gpt-4o-mini call rather than
one LLM call per unmatched row.

**2026-09-13 update to this module's own earlier decision**: this docstring
used to explain why a third, learning-based tier was deliberately NOT
ported from expense-simplifier — a freshly-created model has nothing to
learn from, and PayNexus has no pattern for persisting a model per user.
That reasoning still holds for a *server-persisted* model. What changed:
ml_classifier.py doesn't persist anything — the client sends its own
already-decrypted historical (description, category) pairs alongside each
request (it already holds them, to render the UI), the model trains
in-memory for that one call, and is discarded when the call returns. Same
"plaintext in, plaintext out, nothing persisted" trust boundary this module
already used for parsing/categorizing — just with historical data added to
what's already transiently visible per-request, not a new category of
exposure. See ml_classifier.py's own docstring for the full reasoning.
"""

from __future__ import annotations

import json

from openai import OpenAI

from categorization.categories import CATEGORIES
from categorization.ml_classifier import predict_categories
from categorization.rules import apply_rules
from config import config
from models import Transaction

_client = OpenAI(api_key=config.OPENAI_API_KEY)

_SYSTEM_PROMPT = f"""Categorize each bank transaction description into exactly one of these \
categories: {", ".join(c for c in CATEGORIES if c != "Uncategorized")}.

Respond with a JSON object: {{"categories": [string, ...]}} — exactly one category per row, in \
the same order the rows were given. Use "Uncategorized" only if truly nothing fits — never \
force a bad match into one of the other categories just to avoid it."""


def categorize_transactions(
    transactions: list[Transaction],
    historical_labels: list[tuple[str, str]] | None = None,
) -> list[Transaction]:
    """Mutates and returns `transactions` — sets category/category_source on
    each. Rules run against every row; what rules miss goes to the ML tier
    (skipped automatically if `historical_labels` is too small or absent —
    see ml_classifier.py's thresholds); whatever's left after both costs an
    LLM call, batched into one request rather than one per row.

    `historical_labels`: the client's own already-decrypted (description,
    category) pairs from previously-saved statements, sent fresh with this
    request — never persisted server-side, see this module's own docstring.
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

    if historical_labels:
        # Only train on labels that are themselves in the closed category
        # set -- historical_labels comes from the client, and old saved
        # data could in principle carry a category from before CATEGORIES
        # changed. Filtering here (rather than trusting predict_categories'
        # output afterward) keeps the model from ever learning to predict
        # something invalid in the first place.
        valid_historical_labels = [
            (desc, cat) for desc, cat in historical_labels if cat in CATEGORIES
        ]
        ml_predictions = predict_categories(
            [transactions[i].description for i in unmatched_indices], valid_historical_labels
        )
        still_unmatched = []
        for (category, _confidence), i in zip(ml_predictions, unmatched_indices):
            if category is not None and category in CATEGORIES:
                transactions[i].category = category
                transactions[i].category_source = "ml"
            else:
                still_unmatched.append(i)
        unmatched_indices = still_unmatched

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
