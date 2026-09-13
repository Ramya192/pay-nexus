"""
Agent 2 — Regulatory Intelligence. Hybrid GPT-4o-mini / Ollama phi4-mini
(§7), RAG over the pgvector tax-law index built by rag/build_index.py (§5).
Never receives payslip values — only the user's query text and retrieved
document chunks, per the privacy boundary in §4.

The retrieved chunks also get returned as a table (regulatory_tables) for
the frontend to render — unconditionally, not LLM-selected like the other
agents' tables (agents/tables.py), since retrieval happens on every
regulatory question and what it actually pulled in is exactly what a user
testing this needs to see. Before this, the retrieved chunks only ever
existed inside the LLM's prompt — invisible outside a Python shell, so
there was no way to tell from the chat UI whether an answer was actually
grounded in a good retrieval or a weak one.

Also returns regulatory_llm_calls — the exact token/cost metrics for this
node's single LLM call (agents/llm_metrics.py), merged into
PayNexusState.token_usage by the assembler.
"""

from agents.llm import hybrid_complete
from agents.state import PayNexusState
from config import config
from rag.retriever import retrieve_with_scores

_SYSTEM_PROMPT = """You are the Regulatory Intelligence Agent inside PayNexus. You translate \
Indian tax-law and payroll regulation changes into plain-language, personal-impact statements. \
You are given a user's question and relevant excerpts from Indian tax source documents (Income \
Tax Act sections, Budget Finance Bills, EPFO circulars, state Professional Tax rules). You do \
NOT have access to the user's actual salary figures — answer in terms of rules, thresholds, and \
approximate rupee ranges where the regulation itself specifies a figure, never the user's own numbers.

Two different situations get two different responses — telling them apart matters:
1. A SPECIFIC FIGURE OR RULE the retrieved excerpts don't cover (a deduction limit, a threshold, a \
   rate) — these change by Budget/year, so say plainly that it's not in what's retrieved rather than \
   guessing at a number from general knowledge, even if one seems familiar.
2. A BASIC, STABLE CONCEPT the excerpts don't happen to define in so many words, but that you \
   otherwise know confidently and isn't Budget-dependent (e.g. "what is taxable income," "what is a \
   deduction," "what does TDS mean") — answer it directly from general knowledge. Use whatever's \
   relevant in the retrieved excerpts to ground and support the answer if there's anything useful \
   there, but don't withhold or hedge a correct, complete answer just because the exact term wasn't \
   verbatim in what was retrieved. Do NOT end an otherwise-good answer with a disclaimer like "consult \
   the Income Tax Act for a precise definition" — that undercuts an answer you already gave; if you're \
   confident enough to state the definition, don't also imply you aren't.

Retrieved excerpts can come from documents of different vintages, and older ones can state a figure \
that's since changed — e.g. an FAQ page captured at one assessment year next to a more recent Union \
Budget's highlights. If two retrieved excerpts give DIFFERENT figures for the same rule, they are \
not equally current: prefer whichever excerpt cites the more recent year/Budget/Finance Act \
explicitly, and say so plainly ("as of Budget 2025-26, this is now ₹X — an older FAQ page states ₹Y, \
which has been superseded") rather than silently picking one or blending them. Never state the \
older figure as if it were still current. If you can't tell which excerpt is more recent, say the \
figures conflict and you're not certain which is current, rather than picking one and presenting it \
as confident fact."""

_EXCERPT_PREVIEW_CHARS = 220


def regulatory_agent_node(state: PayNexusState) -> dict:
    query = state["user_query"]
    results = retrieve_with_scores(query, k=config.RAG_TOP_K)

    context = "\n\n---\n\n".join(
        f"[source: {doc.metadata.get('source', 'unknown')}]\n{doc.page_content}" for doc, _ in results
    )
    user_prompt = f"Retrieved regulatory context:\n{context}\n\nQuestion: {query}"
    answer, metrics = hybrid_complete(
        _SYSTEM_PROMPT, user_prompt, model=config.REGULATORY_AGENT_MODEL, agent="regulatory_agent"
    )

    return {
        "regulatory_response": answer,
        "regulatory_tables": [_sources_table(results)],
        "regulatory_llm_calls": [metrics],
    }


def _sources_table(results: list[tuple]) -> dict:
    rows = [
        [
            doc.metadata.get("source", "unknown"),
            f"{score:.3f}",
            doc.page_content[:_EXCERPT_PREVIEW_CHARS]
            + ("…" if len(doc.page_content) > _EXCERPT_PREVIEW_CHARS else ""),
        ]
        for doc, score in results
    ]
    return {
        "title": f"Retrieved sources (top-{len(results)}, distance — lower means more similar)",
        "headers": ["Source document", "Distance", "Retrieved excerpt"],
        "rows": rows,
    }
