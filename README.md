# PayNexus

> "Your pay, explained. Your finances, guided."

A multi-agent agentic AI system that helps salaried employees in India understand their payslip, tax
regime, and financial decisions — not a chatbot, a coordinated team of three specialized reasoning agents
behind a LangGraph orchestrator.

**Live**: [nice-desert-0837ea310.7.azurestaticapps.net](https://nice-desert-0837ea310.7.azurestaticapps.net)
(frontend) · `paynexus-api.azurewebsites.net` (backend API)

Two local-only reference docs, not tracked in this repo (see `.gitignore`): `PROJECT_CONTEXT.md` (the
original spec) and `CHANGELOG.md` (dated history of every bug found, feature built, and review pass run
this build).

## Architecture

Two things drive most of the design decisions below: **every number a user sees traces to a Python
function, never an LLM's arithmetic** (tax slabs, deduction gaps, trends — computed once, quoted by
whichever agent needs them), and **the server never sees plaintext financial data** — payslip and
financial-profile rows are AES-256-GCM ciphertext end to end, encrypted/decrypted only in the browser.

```mermaid
graph TB
    subgraph Client["Browser — React 19 + TypeScript + Vite"]
        UI["Chat UI, tabs, alerts"]
        Crypto["AES-256-GCM encrypt/decrypt<br/>(PBKDF2-derived key, never sent)"]
    end

    subgraph Backend["FastAPI — Azure App Service (container)"]
        API["Routes: auth / chat / payslip / financial-profile"]
        Orch["LangGraph Orchestrator<br/>intent classification → fan-out"]
        A1["Payslip Reasoning Agent<br/>GPT-4o"]
        A2["Regulatory Intelligence Agent<br/>hybrid GPT-4o-mini / local Ollama"]
        A3["Savings Advisor (Nudge) Agent<br/>hybrid, session-aware"]
        Math["tax_slabs.py / tax_calculations.py /<br/>payslip_trends.py — exact computation"]
        Assembler["Assembler<br/>merges responses, dedups tables"]
    end

    PG[("Azure PostgreSQL<br/>+ pgvector")]
    RAGDocs["rag_documents/<br/>10 Indian tax-law sources"]
    OpenAI["OpenAI API"]

    UI <-->|ciphertext only| API
    Crypto -.-> UI
    API --> Orch
    Orch --> A1 & A2 & A3
    A1 & A3 --> Math
    Math --> PG
    A2 -->|similarity search| PG
    RAGDocs -.->|embedded once| PG
    A1 & A2 & A3 -->|LLM calls, metered| OpenAI
    A1 & A2 & A3 --> Assembler
    Assembler --> API
```

**The three agents:**

| Agent | Model | Job |
|---|---|---|
| Payslip Reasoning | GPT-4o | Explains a specific payslip's numbers — accuracy over cost, since a wrong tax figure directly misleads someone |
| Regulatory Intelligence | Hybrid (GPT-4o-mini / local Ollama) | Answers rule/threshold questions, grounded in `rag_documents/` via pgvector retrieval — never sees the user's actual salary |
| Savings Advisor (Nudge) | Hybrid | Cross-session pattern recognition — deduction headroom, trends, regime timing — using compressed session history |

An Orchestrator (LangGraph `StateGraph`) classifies intent and fans out to whichever agents a question
actually needs; an Assembler merges their responses, dedups any table two agents independently selected,
and aggregates real token/cost metrics (`agents/llm_metrics.py`, from OpenAI's own `response.usage`).

## Deployment

| Resource | What | Where |
|---|---|---|
| `paynexus-api` | FastAPI backend, Docker container | Azure App Service (Basic B1, `indiasouthcentral`) |
| `paynexus-web` | React frontend | Azure Static Web Apps (Free tier) |
| `paynexus-db-ramya` | PostgreSQL 16 + `pgvector` | Azure Database for PostgreSQL Flexible Server (Burstable B1MS) |
| `ramya192/paynexus-backend` | Backend container image | Docker Hub (free tier) |

CI/CD: `.github/workflows/deploy.yml` — pushes to `main` build+push the backend image to Docker Hub (Azure's
Continuous Deployment webhook then re-pulls it automatically) and build+deploy the frontend to Static Web
Apps. Real ongoing cost: **~$34/month** (Postgres + App Service; Static Web Apps and Docker Hub are free),
currently running against a $200 Azure free-trial credit with a hard spending limit (no card can be
charged). Full story of getting here — including a native-Python App Service deploy that failed on an Oryx
build quirk and the pivot to a container instead — is in `CHANGELOG.md`'s "Phase 6" entry.

## Stack decisions since the original spec

`PROJECT_CONTEXT.md` is the original spec; these are updates layered on top of it:

| Area | Original doc | Now | Why |
|---|---|---|---|
| React | 18 | **19** | Current stable |
| Styling | Tailwind v3 + config file | **Tailwind v4** — CSS-first via `@theme` in `src/index.css` | Simpler setup, current major version |
| Frontend state | Context + `useReducer` | **Zustand** | Less boilerplate for chat/session state |
| Vector store | FAISS index on Azure Blob | **pgvector** on the existing Postgres | One fewer service to build/persist/sync |
| LLM provider | OpenAI GPT-4o / GPT-4o-mini | **Unchanged** | Kept deliberately (existing paid plan); Microsoft Foundry evaluated and not adopted — see `CHANGELOG.md` |

Everything else (LangGraph orchestration, the three-agent split, client-side AES-256-GCM, context
compression, the Ollama hybrid-inference toggle) stands as written in `PROJECT_CONTEXT.md`.

## Testing

- **`backend/tests/`** — 106 pytest tests, zero setup (`cd backend && pytest`). 97 pure unit tests covering
  every concrete bug this build found (tax slab math, deduction gaps, trends, compression, table dedup,
  Ollama's markdown-fence JSON issue); 4 `@pytest.mark.integration` tests that hit the real OpenAI API.
- **`backend/rag/eval.py`** — retrieval hit-rate@k, MRR, and generation keyword-coverage against a
  hand-verified ground-truth set. Current: 94% hit-rate, 0.853 MRR, 100% keyword coverage.
- **`backend/agent_eval/eval.py`** — the same keyword-coverage approach for the Payslip/Nudge agents'
  actual narrated answers, plus forbidden-phrase checks for this build's recurring failure mode (a
  confidently *wrong* conclusion stated despite correct numbers in the same prompt).
- **`backend/compression/eval.py`** — real before/after token-cost measurement for context compression.
- **`.claude/skills/run-paynexus/`** — the agent-facing runbook: direct Python invocation, `curl` recipes,
  and a Playwright driver (`driver.mjs`) that can target either localhost or the real deployed URLs.

## Layout

```
paynexus/
├── backend/
│   ├── agents/        LangGraph orchestrator + 3 reasoning agents
│   ├── agent_eval/     answer-quality eval for Payslip/Nudge agents
│   ├── rag/            retriever, index builder, eval harness
│   ├── compression/    context compression + its eval harness
│   ├── tests/           106 pytest tests
│   ├── alembic/        migrations — alembic upgrade head before first run
│   ├── Dockerfile       real, tested container for App Service
│   └── ...              FastAPI app, DB models, security, tax computation modules
├── frontend/            React 19 + TypeScript + Tailwind v4 (Vite)
├── rag_documents/       10/10 Indian tax-law source docs embedded into pgvector
├── .claude/skills/run-paynexus/   agent-facing runbook — direct invocation, curl, Playwright
└── .github/workflows/    CI/CD to Azure (Docker Hub + Static Web Apps)

CHANGELOG.md and PROJECT_CONTEXT.md exist locally but aren't pushed (see .gitignore) — local-only
reference docs, not part of the tracked repo tree above.
```

## Quick start

Needs `backend/.env` filled in (copy `backend/.env.example`) — `OPENAI_API_KEY` and a `DATABASE_URL`
pointing at a Postgres with the `vector` extension enabled (`CREATE EXTENSION IF NOT EXISTS vector;`).

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head        # schema setup — required once, before first run
python -m rag.build_index   # only needed once, or after editing rag_documents/
uvicorn api.main:app        # no --reload — see .claude/skills/run-paynexus/SKILL.md Gotchas

# frontend
cd frontend
npm install
npm run dev
```

See `.claude/skills/run-paynexus/SKILL.md` for the full agent-facing runbook — direct Python invocation,
`curl` recipes, and the Playwright driver — with every command actually re-run to confirm it works as
written.
