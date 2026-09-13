"""
Turns a hypothetical question typed in chat ("what if I moved ₹50k more
into ELSS and cut my food budget by ₹1,000") into a structured scenario
override — backs agents/whatif_agent.py. Same role and trust tier as
payslip_extraction.py/statement_extraction.py: a one-shot utility call, not
a fifth/sixth/seventh agent in the §2 sense (no LangGraph node of its own,
called FROM whatif_agent.py's node).

The critical discipline this shares with the other two extractors: never
infer a value the user didn't state. This one matters even more than
those two — an invented number here doesn't just mis-fill a form the user
reviews before using, it silently becomes the "before/after" a real
financial decision gets narrated against. Every field is nullable/false by
default for exactly that reason; whatif_agent.py only simulates whatever
came back non-null, and says plainly when nothing did rather than guessing
what was meant.

Migrated to Agent Framework/Foundry (2026-09-12) — the one loose end left
over from the original 7-agent migration (see agents/whatif_agent.py's
WhatIfAgentResponse docstring, which used to flag this as deliberately
left on its old direct-OpenAI path). Found a real, concrete reason to
close it while doing so, not just for consistency: this call's cost was
NEVER tracked anywhere — agents/whatif_agent.py only ever captured its own
final-narration call's LLMCallMetrics into scenario_llm_calls, so every
extraction call (a real, billed request) was invisible in token_usage,
including — worse — in the "question wasn't specific enough" early-return
path, where extraction is the ONLY call that turn makes. Routing through
agent_complete() (same as payslip_agent/spending_agent/whatif_agent's own
narration call) means this now returns real metrics the caller can
include, and runs against the already-provisioned Foundry deployment
instead of a separate direct OpenAI client/key.
"""

import json

from pydantic import BaseModel

from agents.agent_framework_llm import agent_complete
from agents.llm_metrics import LLMCallMetrics
from budgeting.budgets import DEFAULT_MONTHLY_BUDGETS
from config import config

_BUDGET_CATEGORIES = tuple(DEFAULT_MONTHLY_BUDGETS.keys())

_SYSTEM_PROMPT = f"""Extract a hypothetical financial scenario from a user's "what if" question, \
for a PayNexus feature that computes exact before/after numbers for it. Indian personal finance \
context — rupee amounts, Section 80C/80D/24(b) deductions, old vs. new tax regime.

Respond with a JSON object using exactly these keys:
- "regime_switch": true only if the user is explicitly asking about switching tax regime (old<->new) — false otherwise.
- "additional_80c": number or null — extra rupees the user hypothetically wants to add to Section 80C investments (ELSS, life insurance, home loan principal). Only from an explicit amount stated or clearly implied (e.g. "max out my 80C" implies the exact remaining room, but you don't know that room — return null for implied-without-a-number cases like that, the agent computes it from real data instead).
- "additional_80d": number or null — same, for Section 80D (health insurance).
- "additional_24b": number or null — same, for Section 24(b) (home loan interest).
- "budget_category": one of {list(_BUDGET_CATEGORIES)}, or null — which budget category the question is about, matched on meaning (e.g. "food," "eating out," "dining" all mean "Food & Dining"). Null if no budget category is mentioned.
- "budget_delta": number or null — signed rupee change to that category's spending: NEGATIVE to cut/reduce spending, POSITIVE to raise it. Only set alongside a non-null budget_category.
- "goal_name": string or null — which saved goal (from the list given below) the question is about, matched on meaning even if the user's wording doesn't exactly match the saved name (e.g. "my trip" matching a saved goal named "Goa Trip"). Null if no goal is mentioned, or if none of the given names plausibly match.
- "goal_extra_monthly": number or null — extra rupees per month the user hypothetically wants to contribute toward that goal. Only set alongside a non-null goal_name.

Extract ONLY what the user explicitly stated or unambiguously implied with a real number. Never \
invent, estimate, or default a rupee figure the user didn't give — leave the field null instead. \
A scenario with fewer fields filled in but all of them real is far better than one that looks \
complete but guessed at a number."""


class _ExtractedScenario(BaseModel):
    """Structured-output shape for the Foundry call — see agent_complete()'s
    ChatOptions(response_format=...). budget_category/goal_name stay plain
    `str | None` here rather than a Literal/Enum: the real category set is
    validated against _BUDGET_CATEGORIES below, and the real goal-name set
    is caller-supplied and different per user, so neither can be a static
    type. No "explanation"/"detail" narrative field exists on this model at
    all (it's a pure data-extraction shape) — agent_complete() is called
    with check_for_generic_response=False for exactly the same reason
    orchestrator_v2.IntentClassification is: a correct, complete answer
    here is often ALL-null fields with zero rupee figures (a genuinely
    vague question), which the narrative-figure heuristic would otherwise
    misflag as a suspiciously evasive completion on every such call."""

    regime_switch: bool = False
    additional_80c: float | None = None
    additional_80d: float | None = None
    additional_24b: float | None = None
    budget_category: str | None = None
    budget_delta: float | None = None
    goal_name: str | None = None
    goal_extra_monthly: float | None = None


async def extract_scenario(user_query: str, conversation: list[dict], goal_names: list[str]) -> tuple[dict, LLMCallMetrics]:
    """Returns (scenario, metrics) — metrics is always a real LLMCallMetrics
    now (never absent), including on the all-null/"nothing to simulate"
    result, since that's still one real, billed extraction call."""
    goal_context = f"The user's saved goal names are: {goal_names}." if goal_names else "The user has no saved goals."
    conversation_context = ""
    if conversation:
        recent = conversation[-3:]  # last few exchanges — enough to resolve a short follow-up, not the whole history
        conversation_context = "Recent conversation:\n" + "\n".join(
            f"Q: {c.get('query', '')}\nA: {c.get('response', '')}" for c in recent
        )

    user_prompt = "\n\n".join(part for part in (goal_context, conversation_context, f"Question: {user_query}") if part)

    raw, metrics = await agent_complete(
        _SYSTEM_PROMPT,
        user_prompt,
        model=config.WHATIF_EXTRACTION_MODEL,
        response_model=_ExtractedScenario,
        agent="whatif_extraction",
        check_for_generic_response=False,
    )
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    scenario = {
        "regime_switch": bool(parsed.get("regime_switch") is True),
        "additional_80c": _num_or_none(parsed.get("additional_80c")),
        "additional_80d": _num_or_none(parsed.get("additional_80d")),
        "additional_24b": _num_or_none(parsed.get("additional_24b")),
        "budget_category": parsed.get("budget_category") if parsed.get("budget_category") in _BUDGET_CATEGORIES else None,
        "budget_delta": _num_or_none(parsed.get("budget_delta")),
        "goal_name": parsed.get("goal_name") if parsed.get("goal_name") in goal_names else None,
        "goal_extra_monthly": _num_or_none(parsed.get("goal_extra_monthly")),
    }
    return scenario, metrics


def _num_or_none(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def has_any_signal(scenario: dict) -> bool:
    """True if extraction found at least one concrete hypothetical to
    simulate — whatif_agent.py's cue for "nothing specific enough" vs.
    actually running a scenario."""
    return bool(
        scenario.get("regime_switch")
        or scenario.get("additional_80c")
        or scenario.get("additional_80d")
        or scenario.get("additional_24b")
        or (scenario.get("budget_category") and scenario.get("budget_delta"))
        or (scenario.get("goal_name") and scenario.get("goal_extra_monthly"))
    )
