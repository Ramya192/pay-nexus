"""
Agent answer-quality evaluation harness — the gap flagged in this build's
code review ("no task-success or answer-correctness eval set for the
Payslip or Nudge agents, unlike RAG"). Run manually from backend/ whenever
an agent prompt changes:

    python -m agent_eval.eval

Same philosophy as rag/eval.py, extended one step further:

- **Keyword coverage** — does the agent's real narration (the actual
  production node, agents/payslip_agent.py / agents/nudge_agent.py, not a
  reimplementation) quote the exact, already-computed figures it was
  given? Deliberately NOT an LLM-graded score, same reasoning as
  rag/eval.py: "does ₹21,840 appear" is a cheap, deterministic, exactly-
  reproducible proxy for "was this grounded in the real number."
- **Forbidden phrases** — this project's highest-recurrence bug wasn't a
  missing fact, it was a confidently WRONG conclusion stated despite the
  right numbers sitting in the same prompt (the regime-recommendation
  inversion, which recurred even after the numbers were synced between
  agents; the taxable-income/zero-tax conflation). Keyword coverage alone
  can't catch that — an answer can quote every right number and still draw
  the wrong conclusion from them. Every case that's ever actually broken
  this way gets an explicit forbidden-phrase check here, not just a
  hoped-for absence.

This intentionally covers a DIFFERENT two agents than rag/eval.py (which
already evaluates the Regulatory Agent) — together they're the answer-
quality eval for all three reasoning agents, not overlapping ground.

Costs a handful of real OpenAI calls per run (one per case) — same
trade-off rag/eval.py and compression/eval.py already made: a real,
repeatable measurement is worth the cents, run manually rather than on
every commit.
"""

import json
import re
import time
from dataclasses import asdict, dataclass

from agent_eval.eval_dataset import EVAL_CASES, EvalCase
from agents.nudge_agent import nudge_agent_node
from agents.payslip_agent import payslip_agent_node

_NARRATION_FIELD = {"payslip_agent": "explanation", "nudge_agent": "detail"}
_AGENT_NODE = {"payslip_agent": payslip_agent_node, "nudge_agent": nudge_agent_node}


@dataclass
class CaseResult:
    label: str
    agent: str
    question: str
    answer: str
    expected_keywords: list[str]
    keywords_found: list[str]
    keyword_coverage: float  # keywords_found / expected_keywords, 0.0-1.0
    forbidden_phrases: list[str]
    forbidden_found: list[str]  # non-empty means the agent stated a known-wrong claim
    passed: bool  # full keyword coverage AND zero forbidden phrases found


def _normalize(text: str) -> str:
    """Case-insensitive, comma-insensitive — "21,840" and "Rs 21840" should
    both match "21,840" as a keyword without this eval being sensitive to
    formatting the model doesn't guarantee consistently."""
    return re.sub(r"[,\s]", "", text.lower())


def _extract_narration(raw: str, field_name: str) -> str:
    """Agents 1 and 3 both return structured JSON — pulls the prose field
    out of it, same fallback agents/orchestrator.py's _format_agent_response/
    _parse_nudge use: if it doesn't parse as that shape, evaluate the raw
    text as-is rather than crash the harness on one malformed response."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(parsed, dict) and field_name in parsed:
        return str(parsed[field_name])
    return raw


def run_case(case: EvalCase) -> CaseResult:
    node = _AGENT_NODE[case.agent]
    response_key = "payslip_response" if case.agent == "payslip_agent" else "nudge_response"

    full_state = {"user_query": case.question, **case.state}
    result = node(full_state)
    raw = result.get(response_key, "")
    answer = _extract_narration(raw, _NARRATION_FIELD[case.agent])
    normalized_answer = _normalize(answer)

    # Each keyword spec may be "|"-joined alternatives, same convention as
    # rag/eval_dataset.py — found if ANY alternative is a substring.
    found = [
        kw for kw in case.expected_keywords
        if any(_normalize(alt) in normalized_answer for alt in kw.split("|"))
    ]
    coverage = len(found) / len(case.expected_keywords) if case.expected_keywords else 1.0

    forbidden_found = [p for p in case.forbidden_phrases if _normalize(p) in normalized_answer]

    return CaseResult(
        label=case.label,
        agent=case.agent,
        question=case.question,
        answer=answer,
        expected_keywords=case.expected_keywords,
        keywords_found=found,
        keyword_coverage=coverage,
        forbidden_phrases=case.forbidden_phrases,
        forbidden_found=forbidden_found,
        passed=coverage == 1.0 and not forbidden_found,
    )


def run_eval(cases: list[EvalCase] = EVAL_CASES) -> list[CaseResult]:
    return [run_case(c) for c in cases]


def print_report(results: list[CaseResult]) -> None:
    pass_rate = sum(r.passed for r in results) / len(results)
    avg_coverage = sum(r.keyword_coverage for r in results) / len(results)
    any_forbidden = sum(1 for r in results if r.forbidden_found)

    print(f"\n{'='*100}")
    print(f"Agent answer-quality eval — {len(results)} cases (payslip_agent / nudge_agent)")
    print(f"{'='*100}")
    for r in results:
        status = "OK  " if r.passed else "FAIL"
        print(f"\n[{status}] {r.label} ({r.agent})")
        print(f"       question:  {r.question}")
        print(f"       keywords:  {len(r.keywords_found)}/{len(r.expected_keywords)} found — missing {sorted(set(r.expected_keywords) - set(r.keywords_found))}")
        if r.forbidden_phrases:
            print(f"       forbidden: {'NONE STATED (good)' if not r.forbidden_found else f'STATED: {r.forbidden_found}'}")
        print(f"       answer:    {r.answer[:200]}{'...' if len(r.answer) > 200 else ''}")

    print(f"\n{'='*100}")
    print(f"Pass rate (full coverage + zero forbidden phrases): {pass_rate:.0%}")
    print(f"Average keyword coverage:                           {avg_coverage:.0%}")
    print(f"Cases with a forbidden phrase actually stated:       {any_forbidden}/{len(results)}")
    print(f"{'='*100}\n")


def save_report(results: list[CaseResult], path: str) -> None:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pass_rate": sum(r.passed for r in results) / len(results),
        "avg_keyword_coverage": sum(r.keyword_coverage for r in results) / len(results),
        "cases": [asdict(r) for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Full report saved to {path}")


if __name__ == "__main__":
    results = run_eval()
    print_report(results)
    save_report(results, "agent_eval_report.json")
