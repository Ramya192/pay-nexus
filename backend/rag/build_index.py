"""
One-time index builder — embeds every chunk in rag_documents/ and writes it
into the pgvector collection on DATABASE_URL.

Run manually whenever rag_documents/ changes (from backend/):
    python -m rag.build_index

Requires the vector extension enabled once per database:
    CREATE EXTENSION IF NOT EXISTS vector;

See PROJECT_CONTEXT.md §5 for the pipeline this implements and §11 for
where this fits (backend/rag/build_index.py).
"""

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from config import config
from rag.loader import load_documents, split_documents


def build_index() -> None:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — copy .env.example to .env and fill it in.")
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set — embeddings require it even with USE_LOCAL_SLM.")

    print("Loading documents from rag_documents/ ...")
    docs = load_documents()
    print(f"Loaded {len(docs)} source document(s).")

    chunks = split_documents(docs)
    print(
        f"Split into {len(chunks)} chunks "
        f"(chunk_size={config.RAG_CHUNK_SIZE}, overlap={config.RAG_CHUNK_OVERLAP})."
    )

    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL, api_key=config.OPENAI_API_KEY)

    print(f"Embedding and writing to pgvector collection '{config.PGVECTOR_COLLECTION}' ...")
    PGVector.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=config.PGVECTOR_COLLECTION,
        connection=config.DATABASE_URL,
        # Full rebuild each run — the doc set is small (§5 lists ~10 sources),
        # so a clean re-embed is simpler than diffing what changed.
        pre_delete_collection=True,
    )
    print("Done. Query it via rag/retriever.py — used by the Regulatory Agent.")


if __name__ == "__main__":
    build_index()
