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

Also returns regulatory_llm_calls — the exact token/cost metrics for every
real LLM call this node makes (agents/llm_metrics.py), merged into
PayNexusState.token_usage by the assembler. Usually one call; two when the
web-search fallback below fires.

**Live web-search fallback for a genuine RAG miss** (added after a real
live-testing gap: "what are the new payslip rules launched in 2026?" — a
real, current question — got "the retrieved excerpts do not mention any
specific new rules..." and stopped there, leaving the user to go Google it
themselves). The RAG-grounded call's own system prompt already tells the
model to say plainly when a specific figure/rule isn't in what was
retrieved (situation 1 below) rather than guess — this fallback acts on
that same signal instead of just displaying it: when the model reports a
miss, a second call searches the live web, restricted to a curated list of
Indian government domains (_GOVT_DOMAINS), via Foundry's built-in GA web
search tool (Microsoft-managed Bing — no separate search API/account
needed; see agent_framework_llm.web_search_complete_text). Confirmed via
direct testing against the exact question above: found the real answer
(the Income-tax Act 2025 transition, TDS sections renumbered 192->392),
cited from pib.gov.in/incometax.gov.in, in ~17s.
"""

import asyncio

from agents.agent_framework_llm import hybrid_agent_complete_text, web_search_complete_text
from agents.state import PayNexusState
from config import config
from rag.retriever import (
    cache_web_answer,
    is_cached_answer_expired,
    is_same_cached_question,
    retrieve_with_scores,
)
from rag.retriever import CACHE_MATCH_DISTANCE_THRESHOLD as _CACHE_HIT_DISTANCE_THRESHOLD

# Verbatim string the RAG-grounded call is instructed to return when
# situation 1 (see _SYSTEM_PROMPT) applies — detected via prefix match
# below to trigger the web-search fallback. Deliberately a full sentence,
# not a short token: agent_framework_llm.hybrid_agent_complete_text's own
# retry-on-suspiciously-short-completion heuristic fires under 60 chars,
# and a short sentinel would falsely trip that retry every single time
# this correctly fires, wasting a real LLM call before ever reaching the
# check below.
_WEB_SEARCH_SENTINEL = "NEEDS_WEB_SEARCH: this isn't covered by PayNexus's local regulatory knowledge base."

# Curated to this agent's actual documented scope (Income Tax Act, Union
# Budget, EPFO circulars, professional tax, wage/payslip rules under the
# labour codes) rather than a broad "any .gov.in" allowance — narrower is
# both more accurate for a domain-specific fallback and keeps the web
# search tool's own scope intentional, not accidental. gpt-4o is the only
# deployed model confirmed to support this tool's domain-filter parameter
# (see web_search_complete_text).
#
# labour.gov.in added after a real gap found via live testing: "what
# changed in payslip rules in 2026" is actually a Code on Wages (labour
# ministry) question — the 50% wage-base rule and the standardized Form V
# payslip format both come from labour.gov.in/the Code on Wages Rules,
# 2026, not from anything the Income Tax Department publishes. The
# original list was too tax-department-centric for a genuinely
# payslip-format question, not just tax-figure questions.
_GOVT_DOMAINS = [
    "incometax.gov.in",
    "pib.gov.in",
    "egazette.gov.in",
    "indiabudget.gov.in",
    "epfindia.gov.in",
    "labour.gov.in",
]

# Verbatim string the web-search call is instructed to return when it can't
# find a clear, confident, government-sourced answer — mirrors
# _WEB_SEARCH_SENTINEL's pattern one level down. Added 2026-09-12 after a
# real, observed cache-poisoning risk: before this existed, cache_web_answer
# unconditionally wrote WHATEVER this call returned into the same pgvector
# collection RAG reads from — including a confidently-worded "no such rule
# exists" answer on a genuine search miss (the exact live bug this session
# investigated: a domain-restricted Bing search failed to surface the real,
# notified Code on Wages (Central) Rules, 2026, and the model's honest
# "I couldn't find it" got phrased confidently enough to read as a real
# negative finding). Caching THAT would have been strictly worse than the
# original bug — a wrong answer, once served from the fast local-RAG path,
# looks exactly as authoritative as a correct curated document, and would
# keep being served for the full 90-day TTL instead of getting a chance to
# self-correct on a later, better-luck web search. Detecting the miss via
# an explicit sentinel (checked in regulatory_agent_node below) rather than
# pattern-matching hedge words like "no"/"does not" in the answer text: a
# real, correct answer legitimately contains those words too (e.g. "there
# is no cap on X"), so a keyword heuristic would have its own false-positive
# problem; asking the model to signal unambiguously is the same trick
# _WEB_SEARCH_SENTINEL already relies on one level up.
_WEB_SEARCH_MISS_SENTINEL = "NO_CLEAR_ANSWER_FOUND"

_WEB_SEARCH_SYSTEM_PROMPT = """You are the Regulatory Intelligence Agent inside PayNexus. The user asked a \
question about Indian tax law or payroll regulation that PayNexus's own local knowledge base doesn't cover. \
Use web search — restricted to official Indian government sources — to find a current, accurate answer. You \
do NOT have access to the user's actual salary figures — answer in terms of rules, thresholds, and rupee \
amounts the regulation itself specifies, never the user's own numbers. Cite what you find with inline links \
so the source is checkable.

If even this government-source web search doesn't turn up a clear, confident, directly-on-point answer — \
including cases where you find only tangential/adjacent material, or sources that disagree, or nothing at \
all — your ENTIRE response must be exactly this fixed string, verbatim, and nothing else: \
"NO_CLEAR_ANSWER_FOUND". Do not soften it into a hedged partial answer or an explanation of what you did \
find instead — a caller-side check depends on this being exact so an uncertain result never gets mistaken \
for (and permanently cached as) a confirmed one. Only omit it when you're actually confident the answer is \
correct and directly responsive to what was asked."""

_SYSTEM_PROMPT = """You are the Regulatory Intelligence Agent inside PayNexus. You translate \
Indian tax-law and payroll regulation changes into plain-language, personal-impact statements. \
You are given a user's question and relevant excerpts from Indian tax source documents (Income \
Tax Act sections, Budget Finance Bills, EPFO circulars, state Professional Tax rules). You do \
NOT have access to the user's actual salary figures — answer in terms of rules, thresholds, and \
approximate rupee ranges where the regulation itself specifies a figure, never the user's own numbers.

Two different situations get two different responses — telling them apart matters:
1. A SPECIFIC FIGURE OR RULE the retrieved excerpts don't cover (a deduction limit, a threshold, a \
   rate), OR the question asks about something specific (e.g. "what are the new payslip rules from \
   2026") and the excerpts only contain ADJACENT or TANGENTIALLY related information — not a direct \
   answer to what was actually asked. Piecing together loosely-related excerpts into a hedged partial \
   answer ("this suggests...", "no detailed X is mentioned directly, but...") is exactly the pattern \
   to avoid here — if you're not confident the excerpts, taken together, actually and directly answer \
   the question AS ASKED, treat it as this situation, not situation 2 below, even if some genuinely \
   relevant-sounding content came back. These figures/rules change by Budget/year, so don't guess from \
   general knowledge either, even if a number seems familiar. Instead, your ENTIRE response must be \
   exactly this fixed sentence, verbatim, and nothing else — no partial answer, no explanation of \
   what's missing, no hedged synthesis of what little was retrieved: \
   "NEEDS_WEB_SEARCH: this isn't covered by PayNexus's local regulatory knowledge base." A separate \
   step searches further from there; don't do that work yourself here.
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


def _cached_answer_if_strong_match(query: str, results: list[tuple]) -> str | None:
    """If the single best retrieved result is a fresh (non-expired)
    web_search_cache entry that's genuinely the same question as `query` —
    within _CACHE_HIT_DISTANCE_THRESHOLD AND lexically the same question
    per is_same_cached_question() — extract and return its stored answer
    directly, no LLM call at all.

    This bypasses the RAG-grounded call's own "is this excerpt a direct,
    confident answer" judgment entirely, on purpose: live testing found
    that judgment doesn't reliably recognize the agent's OWN previously
    cached answer as sufficiently direct, since a web-search answer is
    often itself phrased as a hedgy "here's what I found" search summary,
    not a crisp rule statement — feeding it back as retrieved context hit
    the exact same strictness bar it was written to enforce, silently
    re-triggering ANOTHER live web search every time the "same" question
    came back around instead of ever settling into the fast cached path.
    A closest-distance short-circuit sidesteps that recursive-uncertainty
    problem rather than trying to prompt around it further.

    Real, observed false positive this guards against (2026-09-11):
    distance ALONE isn't enough — "what are the new payslip rules from
    2026?" and "what are the new rules for payslip structure in 2026?"
    (a genuinely different question) embedded only 0.253 apart, inside the
    range a real repeat scores. The lexical check in
    is_same_cached_question() is what actually catches that; see its
    docstring and rag/retriever.py's CACHE_MATCH_DISTANCE_THRESHOLD
    comment for the full story."""
    if not results:
        return None
    doc, score = results[0]
    if (
        doc.metadata.get("source") != "web_search_cache"
        or score > _CACHE_HIT_DISTANCE_THRESHOLD
        or not is_same_cached_question(query, doc.metadata.get("original_query", ""))
    ):
        return None
    _, _, cached_answer = doc.page_content.partition("\n\nAnswer: ")
    return cached_answer or None


def regulatory_agent_node(state: PayNexusState) -> dict:
    query = state["user_query"]
    raw_results = retrieve_with_scores(query, k=config.RAG_TOP_K)
    # A cached web-search answer (see cache_web_answer) past its TTL is
    # excluded entirely, not just flagged — an expired entry that's still
    # fed into the prompt would get treated as a trustworthy local hit,
    # exactly the silent-staleness risk the TTL exists to prevent.
    results = [(doc, score) for doc, score in raw_results if not is_cached_answer_expired(doc)]

    cached_answer = _cached_answer_if_strong_match(query, results)
    if cached_answer is not None:
        return {
            "regulatory_response": cached_answer,
            "regulatory_tables": [_sources_table(results)],
        }

    context = "\n\n---\n\n".join(
        f"[source: {doc.metadata.get('source', 'unknown')}]\n{doc.page_content}" for doc, _ in results
    )
    user_prompt = f"Retrieved regulatory context:\n{context}\n\nQuestion: {query}"
    answer, metrics = asyncio.run(
        hybrid_agent_complete_text(
            _SYSTEM_PROMPT, user_prompt, model=config.REGULATORY_AGENT_MODEL, agent="regulatory_agent"
        )
    )
    llm_calls = [metrics]

    # RAG genuinely doesn't cover this — search the live web instead of
    # leaving the user to go look it up themselves (see module docstring).
    # Prefix match, not exact equality: tolerates the model wrapping the
    # sentinel in stray whitespace/quoting without silently missing a real
    # miss.
    if answer.strip().startswith(_WEB_SEARCH_SENTINEL):
        web_answer, web_metrics = asyncio.run(
            web_search_complete_text(
                _WEB_SEARCH_SYSTEM_PROMPT, query, agent="regulatory_agent", allowed_domains=_GOVT_DOMAINS
            )
        )
        llm_calls.append(web_metrics)
        if web_answer.strip().startswith(_WEB_SEARCH_MISS_SENTINEL):
            # A genuine miss, not just an unhedged answer we're choosing not
            # to trust — see _WEB_SEARCH_MISS_SENTINEL's comment for why
            # this must NOT be cached: caching an uncertain "couldn't find
            # it" as if it were a confirmed fact would poison the fast local
            # RAG path for every future asker of a similar question, for the
            # full 90-day TTL, which is strictly worse than just re-trying
            # the web search next time. Told to the user plainly instead —
            # most likely explanation for a genuine miss on an official
            # .gov.in-restricted search is that the question is about a
            # rule change recent enough that it isn't well-indexed there
            # yet, which is worth saying rather than implying the search
            # was exhaustive.
            answer = (
                "I searched PayNexus's local knowledge base and live official Indian government sources "
                "for this, but couldn't find a clear, confident answer to cite. This sometimes happens for "
                "very recently notified rules that government sites haven't fully indexed yet. If you have "
                "a source or date for what you're asking about, share it and I'll factor it in directly."
            )
        else:
            # Cache the RAW answer, not the "🌐 found via live web search"
            # framing below — that framing is true for THIS turn only; once
            # this is served back out of RAG next time, it genuinely IS in
            # the local knowledge base, and saying otherwise would be wrong
            # on replay.
            cache_web_answer(query, web_answer)
            answer = (
                "🌐 Not in PayNexus's local knowledge base — found via a live web search "
                "of Indian government sources instead:\n\n" + web_answer
            )

    return {
        "regulatory_response": answer,
        "regulatory_tables": [_sources_table(results)],
        "regulatory_llm_calls": llm_calls,
    }


def _source_label(doc) -> str:
    """A cached web-search answer (see cache_web_answer) gets its cache
    date shown alongside the source name — "web_search_cache" alone
    wouldn't tell a user whether they're looking at something cached
    yesterday or 89 days ago, right at the edge of _CACHE_TTL_DAYS."""
    source = doc.metadata.get("source", "unknown")
    cached_at = doc.metadata.get("cached_at")
    return f"{source} (cached {cached_at})" if cached_at else source


def _sources_table(results: list[tuple]) -> dict:
    rows = [
        [
            _source_label(doc),
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
