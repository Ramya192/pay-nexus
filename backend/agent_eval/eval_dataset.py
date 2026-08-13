"""
Ground-truth cases for agent_eval/eval.py — the Payslip Agent / Savings
Advisor answer-quality counterpart to rag/eval_dataset.py (which already
covers the Regulatory Agent). Every `expected_keywords`/`forbidden_phrases`
value here was hand-verified against the real tax_calculations.py /
tax_slabs.py / payslip_trends.py output for that exact fixture (see
README.md's "Agent answer-quality eval" section for the verification
transcript), not guessed — a failure here means the agent's narration is
actually wrong, not that the ground truth is.

`forbidden_phrases` exists because this project's highest-recurrence bug
wasn't a missing fact, it was an agent stating the WRONG conclusion despite
having the right numbers in front of it (the regime-recommendation
inversion, twice; the taxable-income/tax conflation) — rag/eval.py's
plain keyword-coverage check only catches missing facts, not confidently
wrong ones, so this dataset checks both.
"""

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    label: str  # short id for the report, not shown to the agent
    agent: str  # "payslip_agent" | "nudge_agent" — which node to run
    question: str
    state: dict  # merged into the base PayNexusState fields this case needs
    expected_keywords: list[str]  # facts that MUST appear (comma/case-insensitive substring match)
    forbidden_phrases: list[str] = field(default_factory=list)  # claims that must NOT appear


EVAL_CASES: list[EvalCase] = [
    # Regime-recommendation consistency — the bug that recurred twice this
    # build even after the underlying numbers were synced between agents,
    # because the LLM inverted the CONCLUSION in its own prose. Same
    # fixture run through both agents so a regression in either shows up.
    EvalCase(
        label="payslip_agent-regime-recommendation",
        agent="payslip_agent",
        question="Which tax regime should I choose, old or new, and why?",
        state={
            "payslip_data": {"month": "2026-03", "basic": 70_000, "hra": 28_000, "specialAllowance": 10_000},
            "financial_profile": {"elssMutualFunds": 150_000, "homeLoanInterestPaid": 50_000},
        },
        expected_keywords=["21,840", "109,512"],  # new regime's exact tax, and the exact savings vs. old
        forbidden_phrases=["old regime is cheaper", "recommend the old regime"],
    ),
    EvalCase(
        label="nudge_agent-regime-recommendation",
        agent="nudge_agent",
        question="Which tax regime should I choose, old or new, and why?",
        state={
            "payslip_data": {"month": "2026-03", "basic": 70_000, "hra": 28_000, "specialAllowance": 10_000},
            "financial_profile": {"elssMutualFunds": 150_000, "homeLoanInterestPaid": 50_000},
        },
        expected_keywords=["21,840", "109,512"],
        forbidden_phrases=["old regime is cheaper", "recommend the old regime"],
    ),
    # Taxable income vs. tax payable conflation — ₹10,77,600 gross puts new-
    # regime taxable income at ₹10,02,600 but total tax at ₹0 (below the
    # ₹12L 87A rebate threshold). The reported bug called the TAXABLE
    # INCOME zero because only the tax was.
    EvalCase(
        label="payslip_agent-taxable-income-not-zero",
        agent="payslip_agent",
        question="What is my taxable income under the new regime?",
        state={"payslip_data": {"month": "2026-03", "basic": 65_000, "hra": 24_800, "specialAllowance": 0}},
        expected_keywords=["1,002,600"],
        forbidden_phrases=["zero taxable income", "no taxable income"],
    ),
    # Exact 80C used/remaining — no PF, so this is a plain sum the agent
    # should quote directly (tax_calculations.compute_80c), not recompute.
    EvalCase(
        label="payslip_agent-80c-used",
        agent="payslip_agent",
        question="How much of my 80C limit have I used so far?",
        state={
            "payslip_data": {"month": "2026-03", "basic": 60_000, "hra": 24_000},
            "financial_profile": {"elssMutualFunds": 50_000, "lifeInsurancePremium": 20_000},
        },
        expected_keywords=["70,000"],
    ),
    EvalCase(
        label="nudge_agent-80c-headroom",
        agent="nudge_agent",
        question="How much 80C room do I have left this year?",
        state={
            "payslip_data": {"month": "2026-03", "basic": 60_000, "hra": 24_000},
            "financial_profile": {"elssMutualFunds": 100_000},
        },
        expected_keywords=["50,000"],
    ),
    # Duplicate-month detection (payslip_trends.detect_duplicate_months) —
    # a real reported bug had this agent answer about unrelated investment
    # data instead of the duplicate check when asked directly.
    EvalCase(
        label="nudge_agent-duplicate-detection",
        agent="nudge_agent",
        question="Are there any duplicate payslips in my saved history?",
        state={
            "payslip_history": [
                {"month": "2026-01", "basic": 50_000},
                {"month": "2026-01", "basic": 50_000},
            ]
        },
        expected_keywords=["2026-01"],
        forbidden_phrases=["no duplicate months found", "no duplicates"],
    ),
    # Month-over-month trend (payslip_trends.compute_trends) — both
    # endpoints should be quoted directly, not re-derived.
    EvalCase(
        label="nudge_agent-basic-salary-trend",
        agent="nudge_agent",
        question="How has my basic salary changed over the months I've saved?",
        state={
            "payslip_history": [
                {"month": "2026-01", "basic": 50_000},
                {"month": "2026-02", "basic": 55_000},
            ]
        },
        expected_keywords=["50,000", "55,000"],
    ),
    # No payslip attached at all — the one fully deterministic, non-LLM
    # early return in payslip_agent_node (see agents/payslip_agent.py).
    # Included as a harness sanity check: if this ever fails, the harness
    # itself (not the LLM) broke.
    EvalCase(
        label="payslip_agent-no-payslip-attached",
        agent="payslip_agent",
        question="What's my gross salary?",
        state={},
        expected_keywords=["No payslip"],
    ),
]
