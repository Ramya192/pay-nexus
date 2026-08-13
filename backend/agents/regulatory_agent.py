"""
Agent 2 — Regulatory Intelligence. Hybrid GPT-4o-mini / Ollama phi4-mini
(§7), RAG over the pgvector tax-law index built by rag/build_index.py (§5).
Never receives payslip values — only the user's query text and retrieved
document chunks, per the privacy boundary in §4.
"""

from agents.llm import hybrid_complete
from agents.state import PayNexusState
from config import config
from rag.retriever import retrieve_as_context

_SYSTEM_PROMPT = """You are the Regulatory Intelligence Agent inside PayNexus. You translate \
Indian tax-law and payroll regulation changes into plain-language, personal-impact statements. \
You are given a user's question and relevant excerpts from Indian tax source documents (Income \
Tax Act sections, Budget Finance Bills, EPFO circulars, state Professional Tax rules). You do \
NOT have access to the user's actual salary figures — answer in terms of rules, thresholds, and \
approximate rupee ranges where the regulation itself specifies a figure, never the user's own \
numbers. If the retrieved excerpts don't cover the question, say so rather than guessing at tax law."""


def regulatory_agent_node(state: PayNexusState) -> dict:
    query = state["user_query"]
    context = retrieve_as_context(query, k=config.RAG_TOP_K)

    user_prompt = f"Retrieved regulatory context:\n{context}\n\nQuestion: {query}"
    answer = hybrid_complete(_SYSTEM_PROMPT, user_prompt, model=config.REGULATORY_AGENT_MODEL)
    return {"regulatory_response": answer}
