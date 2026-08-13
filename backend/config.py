"""
PayNexus config module — all feature flags and settings in one place.

See PROJECT_CONTEXT.md §3 and §12 for the rationale behind each flag and the
full .env variable list. Loaded via python-dotenv; nothing here should be
hardcoded secrets — those live in .env (never committed).
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- LLM ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    USE_LOCAL_SLM: bool = os.getenv("USE_LOCAL_SLM", "False") == "True"
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    PAYSLIP_AGENT_MODEL: str = "gpt-4o"           # always cloud — accuracy critical
    REGULATORY_AGENT_MODEL: str = "gpt-4o-mini"   # or phi4-mini via Ollama toggle
    NUDGE_AGENT_MODEL: str = "gpt-4o-mini"        # or phi4-mini via Ollama toggle
    ORCHESTRATOR_MODEL: str = "gpt-4o"

    # --- RAG ---
    # Vectors live in Postgres via pgvector on DATABASE_URL below — no separate
    # vector DB service, no index file to persist to blob storage.
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RAG_TOP_K: int = 5
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    PGVECTOR_COLLECTION: str = "paynexus_tax_docs"

    # --- Cost / context controls ---
    ENABLE_PROMPT_CACHE: bool = os.getenv("ENABLE_PROMPT_CACHE", "True") == "True"
    ENABLE_CONTEXT_COMPRESSION: bool = os.getenv("ENABLE_CONTEXT_COMPRESSION", "True") == "True"
    MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "2000"))

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # --- Auth ---
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

    # --- CORS ---
    # Comma-separated origins, e.g. "http://localhost:5173,https://paynexus.azurestaticapps.net".
    # Defaults to just the Vite dev server so local dev needs no .env change;
    # add the deployed frontend's origin here (env var, not code) once it exists.
    CORS_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    ]


config = Config()
