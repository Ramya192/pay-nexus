"""
Shared by agents/payslip_agent.py and agents/nudge_agent.py: both build a
dict of {key: table} for whichever computed tables (tax_calculations.py's
gaps_table/financial_profile_table, payslip_trends.py's trends_table/
duplicates_table, payslip_agent's own _components_table) are available this
turn, ask the LLM to pick relevant keys via a "tables" field in its JSON
response, then call resolve_selected_tables() here to map those keys back
to the real precomputed dicts. The LLM only ever sees/produces table KEYS
(a topic-relevance choice, not a numeric one) — never the numbers
themselves, which stay entirely Python-computed end to end.
"""

import json


def resolve_selected_tables(raw_answer: str, available_tables: dict[str, dict]) -> list[dict]:
    """A bad/missing "tables" key just means no tables render — never a
    crash — and an unknown key is silently dropped rather than trusted."""
    try:
        parsed = json.loads(raw_answer)
        keys = parsed.get("tables") if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        keys = None
    if not isinstance(keys, list):
        return []
    return [available_tables[k] for k in keys if isinstance(k, str) and k in available_tables]
