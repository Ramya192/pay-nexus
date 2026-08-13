"""
Similarity-search wrapper over the pgvector collection built by
build_index.py. Consumed by the Regulatory Intelligence Agent (Agent 2) —
see PROJECT_CONTEXT.md §5 for the top-k=5 retrieval this wraps, and §2 for
how the Regulatory Agent injects results into its system prompt.

The store connection is created once at import time and reused — cheap to
import, no per-call reconnect.
"""

from functools import lru_cache

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from config import config


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
