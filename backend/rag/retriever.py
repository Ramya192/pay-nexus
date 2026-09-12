"""
Similarity-search wrapper over the pgvector collection built by
build_index.py. Consumed by the Regulatory Intelligence Agent (Agent 2) —
see PROJECT_CONTEXT.md §5 for the top-k=5 retrieval this wraps, and §2 for
how the Regulatory Agent injects results into its system prompt.

The store connection is created once at import time and reused — cheap to
import, no per-call reconnect.

Also owns the web-search-fallback cache (cache_web_answer/
is_cached_answer_expired) — see agents/regulatory_agent.py's module
docstring for the fallback this feeds: when RAG genuinely doesn't cover a
question, a live government-source web search answers it once, and this
writes that answer back into the SAME pgvector collection so the next
person asking a similar question (or the same user again) hits the fast
local RAG path instead of re-searching the web every time.
"""

import datetime
import difflib
import logging
import re
from functools import lru_cache

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from config import config

logger = logging.getLogger(__name__)

# Tax/payroll rules change with each Union Budget cycle — a web answer
# that was correct when cached can quietly become wrong later, and once
# something's "found in RAG" it's trusted, not re-verified (that's the
# whole point of the fast path). An unbounded cache would let a stale
# answer sit there indefinitely, silently. 90 days is a deliberate
# middle ground: long enough that a real repeat question doesn't
# re-trigger an expensive web search every time, short enough that it
# can't survive an entire Budget cycle unnoticed. Chosen by Ramya over
# "never expire" and "expire each Budget cycle" — see this session's
# discussion for the tradeoff.
_CACHE_TTL_DAYS = 90

# Real, observed false positive (2026-09-11): "what are the new payslip
# rules from 2026?" (answered: an Income-tax Act section renumbering) and
# "what are the new rules for payslip structure in 2026?" (a genuinely
# different ask — labour-code payslip FORMAT, not tax-section numbering)
# embedded only 0.253 apart — comfortably inside the ~0.24-0.28 range a
# real word-for-word repeat scores against its own cached blob (see
# agents/regulatory_agent.py's original calibration note). There is no
# distance threshold that cleanly separates "the same question again" from
# "a different, topically-adjacent question" — tightening it would reject
# real repeats too, not just this false positive. 0.35 is kept as a loose
# pre-filter (rules out anything not even topically close), but
# is_same_cached_question() below — a lexical check on the actual question
# text, not its embedding — is what actually decides "same question," both
# for serving a cached answer verbatim (regulatory_agent.py) and for
# deciding whether to bother writing a new cache entry at all (see
# cache_web_answer below).
CACHE_MATCH_DISTANCE_THRESHOLD = 0.35


def _normalize_query(text: str) -> list[str]:
    """Lowercased, punctuation-stripped word list — for comparing two
    questions' actual wording, independent of embedding distance."""
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def is_same_cached_question(query: str, cached_original_query: str, *, min_ratio: float = 0.85) -> bool:
    """True if `query` is genuinely the same question as
    `cached_original_query` (a typo, different casing, minor rewording) —
    not just semantically nearby enough to embed close together. See
    CACHE_MATCH_DISTANCE_THRESHOLD's comment for the false positive this
    exists to catch: two substantially different questions rarely share
    this much of their actual wording, even when topically adjacent enough
    to fool a distance-only check."""
    a, b = _normalize_query(query), _normalize_query(cached_original_query)
    return difflib.SequenceMatcher(None, a, b).ratio() >= min_ratio


@lru_cache(maxsize=1)
def _store() -> PGVector:
    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL, api_key=config.OPENAI_API_KEY)
    return PGVector(
        embeddings=embeddings,
        collection_name=config.PGVECTOR_COLLECTION,
        connection=config.DATABASE_URL,
    )


def retrieve(query: str, k: int = config.RAG_TOP_K) -> list[Document]:
    """Return the top-k most relevant tax-document chunks for a query."""
    return _store().similarity_search(query, k=k)


def retrieve_with_scores(query: str, k: int = config.RAG_TOP_K) -> list[tuple[Document, float]]:
    """Same retrieval, but also returns each chunk's distance score — for
    surfacing to the user what was actually retrieved (agents/
    regulatory_agent.py's sources table) rather than the retrieval being
    invisible outside a Python shell. PGVector's default strategy is
    cosine distance: LOWER is more similar (0 = identical), not a 0-1
    similarity score — labelled as such wherever this is displayed, so a
    "0.41" doesn't read as "41% relevant" by mistake."""
    return _store().similarity_search_with_score(query, k=k)


def retrieve_as_context(query: str, k: int = config.RAG_TOP_K) -> str:
    """Retrieve and join chunks into one string, ready for prompt injection.

    Each chunk is prefixed with its source file so the Regulatory Agent can
    ground its answer ("per the Budget 2025-26 Finance Bill highlights...").
    """
    chunks = retrieve(query, k=k)
    return "\n\n---\n\n".join(
        f"[source: {doc.metadata.get('source', 'unknown')}]\n{doc.page_content}" for doc in chunks
    )


def is_cached_answer_expired(doc: Document) -> bool:
    """True if `doc` is a web-search-fallback answer (see cache_web_answer)
    older than _CACHE_TTL_DAYS. Always False for a curated rag_documents/
    source — those have no "cached_at" metadata at all, so they never
    expire by this rule."""
    cached_at = doc.metadata.get("cached_at")
    if not cached_at:
        return False
    age_days = (datetime.date.today() - datetime.date.fromisoformat(cached_at)).days
    return age_days > _CACHE_TTL_DAYS


def cache_web_answer(query: str, answer: str) -> None:
    """Writes a web-search-fallback answer into the same pgvector
    collection RAG retrieval reads from, so a repeat of this question (by
    this user or any other) hits the fast local RAG path next time instead
    of re-searching the web. Tagged with today's date so
    is_cached_answer_expired() can retire it after _CACHE_TTL_DAYS.

    Skips the write entirely if a fresh, genuinely-the-same-question entry
    already exists (see is_same_cached_question) — real, observed gap
    (2026-09-11): before this check existed, the exact same question
    ended up cached 2-4 times over (once per rapid retest, and
    concurrent/near-simultaneous requests for the same question would
    independently race past a since-the-fact fast-path check too — this
    guard is the actual point of insertion, the only place that can
    prevent the write itself rather than just prefer one copy over
    another at read time).

    Note: rebuilding the index from rag_documents/ (build_index.py's
    pre_delete_collection=True) wipes every cached entry along with
    everything else in the collection — accepted, not worked around; the
    next matching question just re-searches and re-caches, no data loss
    beyond one slower turn.
    """
    existing = _store().similarity_search_with_score(query, k=1, filter={"source": "web_search_cache"})
    if existing:
        doc, score = existing[0]
        if (
            score <= CACHE_MATCH_DISTANCE_THRESHOLD
            and not is_cached_answer_expired(doc)
            and is_same_cached_question(query, doc.metadata.get("original_query", ""))
        ):
            logger.info("Skipping cache write — already have a fresh answer for %r.", query)
            return

    doc = Document(
        page_content=f"Question: {query}\n\nAnswer: {answer}",
        metadata={
            "source": "web_search_cache",
            "cached_at": datetime.date.today().isoformat(),
            "original_query": query,
        },
    )
    _store().add_documents([doc])
