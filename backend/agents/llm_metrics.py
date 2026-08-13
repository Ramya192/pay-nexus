"""
Structured, Pydantic-validated metrics for every LLM call PayNexus makes.

Before this module: nothing tracked tokens or cost at all.
`agents/llm.py`'s `hybrid_complete()` and every direct OpenAI call
(payslip_agent.py, orchestrator.py's intent classifier,
compression/context_compressor.py's Level 2 summary) discarded
`response.usage` entirely, and `PayNexusState.token_usage` was a field
declared in the TypedDict and never once populated or read anywhere in the
codebase — a dead stub, not a working feature.

Every OpenAI chat completion response already carries exact token counts
in `response.usage` — this module captures what the API already tells us
and prices it; it never estimates tokens with a tokenizer library for a
call that has a real `.usage` field to read instead.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

# USD per 1M tokens, (input, output). Dated like tax_slabs.py's FY_LABEL —
# OpenAI's pricing page (platform.openai.com/pricing) is the source of
# truth and changes independently of this codebase; this table needs a
# manual refresh periodically, not a live fetch. Ollama/local models are $0
# marginal cost by definition (already running on the user's own
# hardware) but tokens are still recorded — useful for capacity/headroom
# comparisons even when there's no dollar cost attached.
PRICING_AS_OF = "2026-01 — verify against platform.openai.com/pricing before relying on this for real budgeting"
_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-small": (0.02, 0.0),
    "phi4-mini": (0.0, 0.0),  # local via Ollama — no per-token API cost
}


class LLMCallMetrics(BaseModel):
    """One completed LLM call. `agent` names which PayNexus component made
    the call ("payslip_agent", "orchestrator_classifier",
    "session_summary", ...) — not the model — so results can be aggregated
    by agent and by model independently."""

    agent: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Returns 0.0 for a model not in the pricing table, rather than
    guessing a rate — an unpriced call should read as "unknown," not as
    free, so callers/report code should treat a 0.0 from an unrecognized
    model name as suspect, not as confirmed savings."""
    pricing = _PRICING_USD_PER_1M.get(model)
    if pricing is None:
        return 0.0
    input_rate, output_rate = pricing
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def record_from_response(agent: str, model: str, response, latency_ms: float) -> LLMCallMetrics:
    """Builds metrics straight from an OpenAI ChatCompletion response's own
    `.usage` field — exact token counts the API already computed, never
    estimated client-side."""
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    return LLMCallMetrics(
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=compute_cost_usd(model, input_tokens, output_tokens),
        latency_ms=latency_ms,
    )


def record_manual(agent: str, model: str, input_tokens: int, output_tokens: int, latency_ms: float) -> LLMCallMetrics:
    """For call paths with no `.usage` field to read — e.g. Ollama's
    plain-text wrapper doesn't report token counts at all. Token counts
    passed in here are the caller's best-effort estimate, not exact —
    unlike record_from_response(), which always is."""
    return LLMCallMetrics(
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=compute_cost_usd(model, input_tokens, output_tokens),
        latency_ms=latency_ms,
    )


def summarize(calls: list[LLMCallMetrics]) -> dict:
    """Aggregates a list of calls into the {totals, by_agent, calls} shape
    PayNexusState.token_usage carries through the assembler — the first
    thing that's ever actually populated that field."""
    by_agent: dict[str, dict] = {}
    for c in calls:
        bucket = by_agent.setdefault(
            c.agent, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
        )
        bucket["input_tokens"] += c.input_tokens
        bucket["output_tokens"] += c.output_tokens
        bucket["cost_usd"] += c.cost_usd
        bucket["calls"] += 1

    return {
        "total_input_tokens": sum(c.input_tokens for c in calls),
        "total_output_tokens": sum(c.output_tokens for c in calls),
        "total_cost_usd": round(sum(c.cost_usd for c in calls), 6),
        "by_agent": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in by_agent.items()},
        "calls": [c.model_dump(mode="json") for c in calls],
    }
