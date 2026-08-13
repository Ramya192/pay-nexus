"""
Context-compression cost-savings harness — didn't exist until a user asked
to see, concretely, what Level 1/Level 2 compression (context_compressor.py,
PROJECT_CONTEXT.md §6) actually saves in tokens and dollars, in a test
profile they could point at rather than take on faith. Run manually from
backend/:

    python -m compression.eval

Every number reported comes from a REAL OpenAI API call's response.usage
(agents/llm_metrics.py) against the REAL production code path
(agents/nudge_agent.py's nudge_agent_node) — never estimated with a
tokenizer, never hand-waved. The only synthetic part is the test
conversation/session-history fixture below (_TEST_*): a fabricated but
realistic multi-month usage pattern, deliberately sized large enough for
compression's effect to actually show up — a 2-turn conversation wouldn't
move the number enough to be worth reporting.

Two comparisons, because Level 1 and Level 2 save in different places:

- Level 1 (in-session sliding window): same-turn savings — how much
  smaller this turn's Savings Advisor prompt is with only the last 3
  exchanges vs. the entire conversation so far.
- Level 2 (cross-session summary): compression has an up-front cost (the
  summarization call itself, run once per session) that then pays off on
  every future session that would otherwise carry the full raw history
  forward — reported as a per-turn saving AND a break-even point, since
  "it costs X to compress and saves Y per reuse" is the actual shape of
  the trade-off, not just a single before/after number.
"""

import json

from agents.llm_metrics import LLMCallMetrics, summarize
from agents.nudge_agent import nudge_agent_node
from compression.context_compressor import compress_in_session, compress_session_summary

# --- Test profile — fabricated but realistic, not the real production data ---

_TEST_PAYSLIP = {"month": "2026-03", "basic": 42000, "hra": 16800, "specialAllowance": 18500, "pfEmployee": 5040, "tds": 9800}
_TEST_FINANCIAL_PROFILE = {"lifeInsurancePremium": 35853, "healthInsurancePremium": 80000}

# 15 exchanges — a realistic longer chat session, sized so Level 1's
# sliding window (keeps the last 3) has a visible effect to measure.
_TEST_CONVERSATION = [
    {"query": "why did my take-home drop this month?", "response": "Your TDS increased by ₹1,200 compared to last month, likely due to the bonus you received."},
    {"query": "how much was the bonus taxed?", "response": "Bonuses are taxed at your marginal rate, added to that month's income before TDS is computed."},
    {"query": "can you recommend a tax regime?", "response": "Based on your declared deductions, the old regime currently looks more favorable."},
    {"query": "what's my HRA exemption?", "response": "Based on your rent and basic salary, your HRA exemption works out to approximately ₹15,800/month."},
    {"query": "do you see any concerning trends?", "response": "Your TDS has been rising steadily over the last 3 months — worth reviewing your declared investments."},
    {"query": "can I still invest more for this year?", "response": "You have room remaining under Section 80C — investing there could reduce your taxable income."},
    {"query": "what about health insurance?", "response": "You've used your full Section 80D limit already this year."},
    {"query": "should I increase my PF contribution?", "response": "Increasing voluntary PF contributes to Section 80C, but reduces take-home pay — worth weighing against other options."},
    {"query": "how does the new regime compare for me specifically?", "response": "Given your deduction level, the new regime would likely mean a higher tax bill this year."},
    {"query": "what if I get a raise next year?", "response": "A higher income could shift the regime comparison — worth revisiting once the new figure is known."},
    {"query": "can you explain my payslip components?", "response": "Your payslip breaks down into Basic, HRA, Special Allowance, PF, Professional Tax, and TDS."},
    {"query": "why is professional tax deducted?", "response": "Professional tax is a small state-level deduction, capped annually, separate from income tax."},
    {"query": "is my EPF contribution mandatory?", "response": "Yes, EPF is mandatory up to the wage ceiling, split between employee and employer contributions."},
    {"query": "what's the difference between PF and VPF?", "response": "VPF is a voluntary top-up over the mandatory EPF contribution, still counted under Section 80C."},
    {"query": "can you summarize what we've covered?", "response": "We've covered your take-home drop, regime comparison, HRA exemption, and remaining deduction room."},
]

# 5 prior sessions' worth of raw exchanges — what would need to be carried
# forward every future session if Level 2 never compressed it down.
_TEST_PAST_SESSIONS = [
    [
        {"query": "recommend a tax regime for me", "response": "Given your deductions, the old regime looks better this year."},
        {"query": "why did my bonus get taxed so much?", "response": "Bonuses are added to that month's income and taxed at your marginal rate."},
    ],
    [
        {"query": "any savings suggestions?", "response": "You have ₹40,000 of unused Section 80C room this year."},
        {"query": "what about my HRA?", "response": "Your HRA exemption is approximately ₹15,800/month given your current rent."},
        {"query": "should I switch regimes?", "response": "Not yet — your deductions still favor the old regime."},
    ],
    [
        {"query": "how's my TDS trending?", "response": "Your TDS has risen roughly ₹2,000 over the last two months."},
        {"query": "is that a problem?", "response": "Not necessarily — it may reflect a bonus or a salary revision."},
    ],
    [
        {"query": "can you check my deduction gaps?", "response": "You've used your full 80D limit; 80C still has room remaining."},
        {"query": "what about home loan interest?", "response": "You haven't declared any home loan interest — Section 24(b) is fully unused."},
        {"query": "should I claim that?", "response": "Only if you're actually paying home loan interest — declare it if so."},
    ],
    [
        {"query": "how does my new payslip compare to last quarter?", "response": "Basic and HRA are unchanged; TDS is up due to a one-time bonus."},
        {"query": "will that bonus affect my annual tax?", "response": "It raises this year's taxable income, but doesn't change your regime comparison materially."},
    ],
]


def _input_tokens(calls: list[LLMCallMetrics]) -> int:
    return sum(c.input_tokens for c in calls)


def eval_level1_in_session() -> dict:
    """Same-turn savings: identical question, identical everything else —
    only the conversation history differs (full vs. sliding-window)."""
    base_state = {
        "user_query": "based on everything so far, what should I prioritize?",
        "payslip_data": _TEST_PAYSLIP,
        "payslip_history": [],
        "financial_profile": _TEST_FINANCIAL_PROFILE,
        "session_history": [],
    }

    uncompressed_result = nudge_agent_node({**base_state, "conversation": _TEST_CONVERSATION})
    compressed_conversation = compress_in_session(_TEST_CONVERSATION)
    compressed_result = nudge_agent_node({**base_state, "conversation": compressed_conversation})

    uncompressed_calls = uncompressed_result["nudge_llm_calls"]
    compressed_calls = compressed_result["nudge_llm_calls"]

    before_tokens = _input_tokens(uncompressed_calls)
    after_tokens = _input_tokens(compressed_calls)
    before_summary = summarize(uncompressed_calls)
    after_summary = summarize(compressed_calls)

    return {
        "exchanges_before": len(_TEST_CONVERSATION),
        "exchanges_after": len(compressed_conversation),
        "input_tokens_before": before_tokens,
        "input_tokens_after": after_tokens,
        "input_tokens_saved": before_tokens - after_tokens,
        "input_tokens_saved_pct": round((1 - after_tokens / before_tokens) * 100, 1) if before_tokens else 0.0,
        "cost_usd_before": before_summary["total_cost_usd"],
        "cost_usd_after": after_summary["total_cost_usd"],
        "cost_usd_saved_per_turn": round(before_summary["total_cost_usd"] - after_summary["total_cost_usd"], 6),
    }


def eval_level2_cross_session() -> dict:
    """Up-front cost (real summarization calls) vs. the per-turn saving
    that cost buys on every future session that reuses the summary instead
    of the raw history."""
    compression_calls: list[LLMCallMetrics] = []
    compressed_summaries: list[dict] = []
    for session in _TEST_PAST_SESSIONS:
        summary, metrics = compress_session_summary(session, _TEST_PAYSLIP)
        compressed_summaries.append(summary)
        if metrics:
            compression_calls.append(metrics)

    raw_history_as_session_history = [
        {"session": i, "exchanges": session} for i, session in enumerate(_TEST_PAST_SESSIONS)
    ]

    base_state = {
        "user_query": "can you recommend a tax regime based on my history?",
        "payslip_data": _TEST_PAYSLIP,
        "payslip_history": [],
        "financial_profile": _TEST_FINANCIAL_PROFILE,
        "conversation": [],
    }

    without_compression = nudge_agent_node({**base_state, "session_history": raw_history_as_session_history})
    with_compression = nudge_agent_node({**base_state, "session_history": compressed_summaries})

    before_tokens = _input_tokens(without_compression["nudge_llm_calls"])
    after_tokens = _input_tokens(with_compression["nudge_llm_calls"])
    before_summary = summarize(without_compression["nudge_llm_calls"])
    after_summary = summarize(with_compression["nudge_llm_calls"])
    compression_cost = summarize(compression_calls)["total_cost_usd"]
    per_turn_saving = before_summary["total_cost_usd"] - after_summary["total_cost_usd"]

    return {
        "sessions_compressed": len(_TEST_PAST_SESSIONS),
        "raw_exchanges_total": sum(len(s) for s in _TEST_PAST_SESSIONS),
        "input_tokens_before": before_tokens,
        "input_tokens_after": after_tokens,
        "input_tokens_saved": before_tokens - after_tokens,
        "input_tokens_saved_pct": round((1 - after_tokens / before_tokens) * 100, 1) if before_tokens else 0.0,
        "cost_usd_before_per_turn": before_summary["total_cost_usd"],
        "cost_usd_after_per_turn": after_summary["total_cost_usd"],
        "cost_usd_saved_per_turn": round(per_turn_saving, 6),
        "compression_cost_usd_one_time": round(compression_cost, 6),
        "break_even_after_turns": (
            round(compression_cost / per_turn_saving, 1) if per_turn_saving > 0 else float("inf")
        ),
    }


def eval_level2_scaling() -> dict:
    """A single longer, more typical session (the same 15-exchange
    conversation Level 1 tests with) compressed on its own — shows that
    Level 2's saving scales with how much a session actually covers, not a
    fixed amount: a summary stays capped near ~100 tokens regardless of
    how long the session was, while the raw alternative keeps growing.
    _TEST_PAST_SESSIONS above deliberately uses short 2-3 exchange
    sessions instead (a conservative case) — this shows the other end."""
    summary, metrics = compress_session_summary(_TEST_CONVERSATION, _TEST_PAYSLIP)
    raw_chars = len(json.dumps(_TEST_CONVERSATION))
    compressed_chars = len(json.dumps(summary))
    return {
        "exchanges_in_session": len(_TEST_CONVERSATION),
        "raw_chars": raw_chars,
        "compressed_chars": compressed_chars,
        "size_reduction_pct": round((1 - compressed_chars / raw_chars) * 100, 1),
        "compression_cost_usd": metrics.cost_usd if metrics else 0.0,
    }


def print_report(level1: dict, level2: dict, level2_scaling: dict) -> None:
    print(f"\n{'=' * 90}")
    print("CONTEXT COMPRESSION — cost/token savings, test profile")
    print(f"{'=' * 90}")

    print("\n--- Level 1: in-session sliding window ---")
    print(f"Conversation: {level1['exchanges_before']} exchanges -> kept {level1['exchanges_after']} (sliding window)")
    print(f"Input tokens: {level1['input_tokens_before']:,} -> {level1['input_tokens_after']:,}  "
          f"(saved {level1['input_tokens_saved']:,}, {level1['input_tokens_saved_pct']}%)")
    print(f"Cost per turn: ${level1['cost_usd_before']:.6f} -> ${level1['cost_usd_after']:.6f}  "
          f"(saves ${level1['cost_usd_saved_per_turn']:.6f} every turn this applies to)")

    print("\n--- Level 2: cross-session summary ---")
    print(f"Compressed {level2['sessions_compressed']} past sessions ({level2['raw_exchanges_total']} raw exchanges) "
          f"for ${level2['compression_cost_usd_one_time']:.6f} total (one-time, real summarization calls)")
    print(f"Input tokens per future turn: {level2['input_tokens_before']:,} (raw) -> "
          f"{level2['input_tokens_after']:,} (compressed)  "
          f"(saved {level2['input_tokens_saved']:,}, {level2['input_tokens_saved_pct']}%)")
    print(f"Cost per future turn: ${level2['cost_usd_before_per_turn']:.6f} -> ${level2['cost_usd_after_per_turn']:.6f}  "
          f"(saves ${level2['cost_usd_saved_per_turn']:.6f}/turn)")
    if level2["break_even_after_turns"] != float("inf"):
        print(f"Break-even: the one-time compression cost pays for itself after "
              f"~{level2['break_even_after_turns']} future turns reusing this summary")

    print("\n--- Level 2, scaling: one longer (15-exchange) session compressed on its own ---")
    print(f"Raw session size: {level2_scaling['raw_chars']:,} chars -> compressed: "
          f"{level2_scaling['compressed_chars']:,} chars  "
          f"({level2_scaling['size_reduction_pct']}% smaller, for ${level2_scaling['compression_cost_usd']:.6f})")
    print("The short 2-3 exchange sessions above are the conservative case — a summary stays")
    print("~capped regardless of session length, so savings grow with how much a session covers.")
    print(f"\n{'=' * 90}\n")


if __name__ == "__main__":
    level1 = eval_level1_in_session()
    level2 = eval_level2_cross_session()
    level2_scaling = eval_level2_scaling()
    print_report(level1, level2, level2_scaling)
    with open("compression_eval_report.json", "w", encoding="utf-8") as f:
        json.dump(
            {"level1_in_session": level1, "level2_cross_session": level2, "level2_scaling": level2_scaling},
            f,
            indent=2,
        )
    print("Full report saved to compression_eval_report.json")
