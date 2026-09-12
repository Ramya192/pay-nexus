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

    # --- Azure AI Foundry ---
    # paynexus-foundry account, paynexus-v21 project. Foundry only has two
    # model deployments provisioned so far — "gpt-4o" and "gpt-4.1-mini" —
    # not one deployment per *_AGENT_MODEL name above. FOUNDRY_DEPLOYMENT_MAP
    # is an interim mapping from this file's existing OpenAI model names to
    # the Foundry deployment that actually serves that tier; a real
    # per-agent deployment-name scheme is future work, not done here.
    FOUNDRY_PROJECT_ENDPOINT: str = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
    # Real, observed root cause (2026-09-11): nothing wrapped runner.run()
    # against Foundry's GlobalStandard (shared, best-effort) tier in a
    # timeout, so a slow/throttled call under load just hung the request
    # indefinitely — no error, no fallback, no user-visible feedback beyond
    # a spinner. See agent_framework_llm._run_with_timeout().
    #
    # 40s was the original value here — wrong, found the same day by the new
    # automation suite (paynexus-v2.1-test-suite): 17 of 19 failures in a
    # single run clustered at 43,000-46,000ms, just past that ceiling. A
    # normal, successful single-agent completion against this app's real
    # prompts (long system prompt, GPT-4o, a full JSON schema, sometimes a
    # retry-on-suspicious-response) routinely takes 43-46s — not a hang,
    # just this app's actual steady-state latency. 90s keeps a healthy >2x
    # margin over that observed real maximum while still catching a genuine
    # hang well inside it (vs. the indefinite hang this whole mechanism
    # replaced) — recalibrate again from real data, not from guessing, if
    # this ever starts firing on real requests again.
    FOUNDRY_CALL_TIMEOUT_SECONDS: int = int(os.getenv("FOUNDRY_CALL_TIMEOUT_SECONDS", "90"))
    # regulatory_agent's RAG-miss web-search fallback does a real Bing
    # round trip plus tool-call reasoning on top of the base completion —
    # genuinely slower than a plain structured completion, so it gets its
    # own, longer ceiling rather than sharing the value above. Also
    # recalibrated 2026-09-12 from real automation-suite data: an observed
    # successful run took 67s against the original 60s ceiling.
    FOUNDRY_WEB_SEARCH_TIMEOUT_SECONDS: int = int(os.getenv("FOUNDRY_WEB_SEARCH_TIMEOUT_SECONDS", "120"))
    FOUNDRY_DEPLOYMENT_MAP: dict[str, str] = {
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4.1-mini",
    }

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
