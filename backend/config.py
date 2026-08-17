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

    # --- V2: SpendingAnalyser ---
    # SPENDING_AGENT_MODEL is gpt-4o (same tier as Payslip agent): it narrates
    # over transactions already saved to a session, live in conversation,
    # with no review step — same "wrong numbers directly mislead the user"
    # reasoning. STATEMENT_PARSE_MODEL/SPENDING_CATEGORIZE_MODEL stay at
    # gpt-4o-mini, same tier and same reasoning as payslip_extraction.py's:
    # both only pre-fill a transaction list the user reviews (and the
    # category can be corrected) before "Save this statement" persists it.
    SPENDING_AGENT_MODEL: str = "gpt-4o"
    STATEMENT_PARSE_MODEL: str = "gpt-4o-mini"
    SPENDING_CATEGORIZE_MODEL: str = "gpt-4o-mini"

    # --- V2: GoalTracker ---
    # gpt-4o-mini + Ollama hybrid toggle, same tier as Nudge/Regulatory: it
    # narrates over precomputed target-vs-saved math (analytics/
    # goal_progress.py), never invents a number, same "softer reasoning
    # over pre-solved figures" reasoning as the rest of that tier.
    GOAL_AGENT_MODEL: str = "gpt-4o-mini"

    # --- V2: BudgetPlanner ---
    # Same tier and reasoning as GoalTracker — narrates over precomputed
    # check_overspending alerts (budgeting/budgets.py), never derives its
    # own overspend figures.
    BUDGET_AGENT_MODEL: str = "gpt-4o-mini"

    # --- V2: What-If Simulator ---
    # WHATIF_AGENT_MODEL is gpt-4o (same tier as Payslip/SpendingAnalyser):
    # a hypothetical that gets acted on is still a real financial decision,
    # same "wrong numbers directly mislead the user" reasoning — no review
    # step softens a scenario answer the way a pre-fill form does.
    # WHATIF_EXTRACTION_MODEL stays gpt-4o-mini, same tier and reasoning as
    # payslip_extraction.py/statement_extraction.py: structured extraction
    # of what the user explicitly typed, not financial reasoning itself.
    WHATIF_AGENT_MODEL: str = "gpt-4o"
    WHATIF_EXTRACTION_MODEL: str = "gpt-4o-mini"

    # --- V2: Account Aggregator (Setu sandbox) ---
    # Sandbox only — see .env.example's setup note and setu_aa_client.py's
    # module docstring for the signup flow and verified endpoint paths.
    # SETU_AA_TOKEN_URL is a separate host from SETU_AA_BASE_URL on purpose —
    # confirmed against Setu's own docs, not a typo: auth is a shared Setu
    # platform service (uat.setu.co), the FIU-specific consent/session APIs
    # live on a different host (fiu-sandbox.setu.co).
    SETU_AA_TOKEN_URL: str = "https://uat.setu.co/api/v2/auth/token"
    SETU_AA_BASE_URL: str = os.getenv("SETU_AA_BASE_URL", "https://fiu-sandbox.setu.co")
    SETU_AA_PRODUCT_INSTANCE_ID: str = os.getenv("SETU_AA_PRODUCT_INSTANCE_ID", "")
    SETU_AA_CLIENT_ID: str = os.getenv("SETU_AA_CLIENT_ID", "")
    SETU_AA_CLIENT_SECRET: str = os.getenv("SETU_AA_CLIENT_SECRET", "")
    SETU_AA_REDIRECT_URL: str = os.getenv("SETU_AA_REDIRECT_URL", "")

    # --- RAG ---
    # Vectors live in Postgres via pgvector on DATABASE_URL below — no separate
    # vector DB service, no index file to persist to blob storage.
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RAG_TOP_K: int = 5
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    PGVECTOR_COLLECTION: str = "paynexus_tax_docs"

    # --- Cost / context controls ---
    # ENABLE_PROMPT_CACHE and MAX_CONTEXT_TOKENS used to live here too —
    # removed during a codebase review: neither was ever actually read by
    # any code (OpenAI's prompt caching is automatic and not something this
    # app toggles; nothing implemented a token-budget cap keyed to a
    # config value). Both looked like live settings a reviewer could flip
    # in .env and see an effect from, but changing either did nothing.
    ENABLE_CONTEXT_COMPRESSION: bool = os.getenv("ENABLE_CONTEXT_COMPRESSION", "True") == "True"

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
