"""
RAG evaluation harness — the piece that didn't exist before a user asked
"are we implementing evaluation metrics for RAG?" Run manually from
backend/ whenever the corpus or retrieval settings change:

    python -m rag.eval

Two kinds of metric, deliberately kept separate because they test
different failure modes:

- **Retrieval metrics** (hit-rate@k, MRR) — fully deterministic, computed
  from retrieved chunk metadata alone, no LLM involved. Answers "did the
  right document even make it into the context the model saw."
- **Generation metric** (keyword/fact coverage) — runs the real
  agents/regulatory_agent.py node (the actual production code path, not a
  reimplementation) and checks whether known facts appear in its answer.
  Deliberately NOT an LLM-graded "faithfulness score": that would trade a
  cheap, deterministic, exactly-reproducible check for an expensive,
  somewhat-subjective one, for a corpus this small and factual where "does
  the number ₹75,000 appear" is a perfectly good proxy for "was this
  grounded correctly." Revisit if the corpus grows into content where
  yes/no facts aren't enough to judge quality.

This harness is what caught a real bug on first run, not after: asked "what
is the standard deduction under the new tax regime," the retrieval missed
the chunk with the current ₹75,000 figure and the model answered with a
stale ₹50,000 from its own pretrained knowledge instead of the corpus. See
rag/eval_dataset.py's first case and README.md's RAG section for the
follow-up.
"""

import json
import re
import time
from dataclasses import asdict, dataclass

from agents.regulatory_agent import regulatory_agent_node
from config import config
from rag.eval_dataset import EVAL_CASES, EvalCase
from rag.retriever import retrieve_with_scores


@dataclass
class CaseResult:
    question: str
    expected_source: str
    retrieved_sources: list[str]
    hit: bool  # expected_source appeared anywhere in top-k
    rank: int | None  # 1-indexed position of first chunk from expected_source, None if not retrieved
    answer: str
    expected_keywords: list[str]
    keywords_found: list[str]
    keyword_coverage: float  # keywords_found / expected_keywords, 0.0-1.0


def _normalize(text: str) -> str:
    """Case-insensitive, comma-insensitive — "75,000" and "Rs 75000" should
    both match "75,000" as a keyword without this eval being sensitive to
    formatting the source docs/model don't guarantee consistently."""
    return re.sub(r"[,\s]", "", text.lower())


def run_case(case: EvalCase, k: int = config.RAG_TOP_K) -> CaseResult:
    retrieved = retrieve_with_scores(case.question, k=k)
    retrieved_sources = [doc.metadata.get("source", "unknown") for doc, _ in retrieved]

    rank = next((i + 1 for i, s in enumerate(retrieved_sources) if s == case.expected_source), None)
    hit = rank is not None

    node_result = regulatory_agent_node({"user_query": case.question})
    answer = node_result.get("regulatory_response", "")
    normalized_answer = _normalize(answer)

    # Each keyword spec may be "|"-joined alternatives (see eval_dataset.py)
    # — found if ANY alternative is a substring of the answer.
    found = [
        kw for kw in case.expected_keywords
        if any(_normalize(alt) in normalized_answer for alt in kw.split("|"))
    ]
    coverage = len(found) / len(case.expected_keywords) if case.expected_keywords else 1.0

    return CaseResult(
        question=case.question,
        expected_source=case.expected_source,
        retrieved_sources=retrieved_sources,
        hit=hit,
        rank=rank,
        answer=answer,
        expected_keywords=case.expected_keywords,
        keywords_found=found,
        keyword_coverage=coverage,
    )


def run_eval(cases: list[EvalCase] = EVAL_CASES) -> list[CaseResult]:
    return [run_case(c) for c in cases]


def print_report(results: list[CaseResult]) -> None:
    hit_rate = sum(r.hit for r in results) / len(results)
    mrr = sum((1 / r.rank) if r.rank else 0.0 for r in results) / len(results)
    avg_coverage = sum(r.keyword_coverage for r in results) / len(results)

    print(f"\n{'='*100}")
    print(f"RAG eval — {len(results)} cases, top-k={config.RAG_TOP_K}")
    print(f"{'='*100}")
    for r in results:
        status = "OK  " if r.hit and r.keyword_coverage == 1.0 else "FAIL"
        print(f"\n[{status}] {r.question}")
        print(f"       retrieval: {'hit' if r.hit else 'MISS'} (rank {r.rank}) — expected {r.expected_source!r}")
        print(f"                  got: {r.retrieved_sources}")
        print(f"       keywords:  {len(r.keywords_found)}/{len(r.expected_keywords)} found — missing {sorted(set(r.expected_keywords) - set(r.keywords_found))}")
        print(f"       answer:    {r.answer[:200]}{'...' if len(r.answer) > 200 else ''}")

    print(f"\n{'='*100}")
    print(f"Retrieval hit-rate@{config.RAG_TOP_K}: {hit_rate:.0%}")
    print(f"Retrieval MRR:            {mrr:.3f}")
    print(f"Answer keyword coverage:  {avg_coverage:.0%}")
    print(f"{'='*100}\n")


def save_report(results: list[CaseResult], path: str) -> None:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "top_k": config.RAG_TOP_K,
        "hit_rate": sum(r.hit for r in results) / len(results),
        "mrr": sum((1 / r.rank) if r.rank else 0.0 for r in results) / len(results),
        "avg_keyword_coverage": sum(r.keyword_coverage for r in results) / len(results),
        "cases": [asdict(r) for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Full report saved to {path}")


if __name__ == "__main__":
    results = run_eval()
    print_report(results)
    save_report(results, "rag_eval_report.json")
