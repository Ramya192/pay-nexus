# PayNexus

> "Your pay, explained. Your finances, guided."

A multi-agent agentic AI system for salaried employees in India — not a chatbot, a coordinated team
of seven specialized reasoning agents behind an orchestrator, covering payslips, tax regulation,
spending, budgeting, and savings goals in one place.

**V1** (payslip + tax regulation only, 3 agents) is live: [nice-desert-0837ea310.7.azurestaticapps.net](https://nice-desert-0837ea310.7.azurestaticapps.net)
· `paynexus-api.azurewebsites.net` (backend API).
**V2** (`v2-dev`) adds bank statements, budgeting, savings goals, and scenario planning — built,
tested, and live-verified end to end. Deployed to its own, separate Azure resources (own App
Service, own Static Web App, own database) rather than merged to `main`, so it never touches V1's
production traffic: [ambitious-pebble-083cdaf10.7.azurestaticapps.net](https://ambitious-pebble-083cdaf10.7.azurestaticapps.net)
· `paynexus-api-v2.azurewebsites.net` (backend API).
**V2.1** (this worktree, `foundry-v3`) is an agent-layer-only migration of V2's orchestrator from
LangGraph to Microsoft's **Agent Framework**, running against **Azure AI Foundry** (the
`paynexus-foundry` project) instead of calling OpenAI directly — the FastAPI app, auth, and
encrypted CRUD are untouched. Not deployed anywhere yet (agent-layer scope only); see
[Agent Framework migration](#agent-framework-migration-v21) below.

## Architecture

Two things drive most of the design decisions below: **every number a user sees traces to a Python
function, never an LLM's arithmetic** (tax slabs, deduction gaps, trends, overspending, goal
progress — computed once, quoted by whichever agent needs them), and **the server never sees
plaintext financial data** — payslip, financial-profile, bank-statement, goal, and budget rows are
all AES-256-GCM ciphertext end to end, encrypted/decrypted only in the browser.

```mermaid
graph LR
    User["Browser<br/>(React)"] <-->|ciphertext only| Backend
    Backend["FastAPI +<br/>Agent Framework Orchestrator"] --> Agents["7 Reasoning Agents"]
    Agents --> Foundry["Azure AI Foundry<br/>(paynexus-foundry)"]
    Backend <--> DB[("PostgreSQL<br/>+ pgvector")]
```

The Orchestrator (`agents/orchestrator_v2.py` — Microsoft Agent Framework's `ConcurrentBuilder`, as
of the V2.1 migration below) classifies each question and fans it out — concurrently — to whichever
of the seven agents actually apply; a payslip question hits one agent, "which regime should I pick
and how much would I save, and am I still on budget" might hit four. Requests that try to add/edit/
delete saved data through chat (not a question, an instruction) are caught by a dedicated no-LLM
capability-gap node instead of being silently misrouted or hallucinated as done.

| Agent | Model (Foundry deployment) | Job |
|---|---|---|
| Payslip Reasoning | gpt-4o | Explains a specific payslip's numbers — accuracy over cost, since a wrong tax figure directly misleads someone |
| Regulatory Intelligence | Hybrid (gpt-4.1-mini / local Ollama) | Rule/threshold questions, grounded in `rag_documents/` via pgvector retrieval — never sees the user's actual salary |
| Savings Advisor (Nudge) | Hybrid | Cross-session pattern recognition — deduction headroom, trends, regime timing — using compressed session history |
| SpendingAnalyser | gpt-4o | Bank-statement transactions: category breakdowns, recurring merchants, the subscriptions-specific filter |
| BudgetPlanner | Hybrid | Actual spend vs. saved per-category budget targets — period-prorated so a statement longer than a month doesn't falsely read as overspending |
| GoalTracker | Hybrid | Savings-goal progress and whether the current pace hits a target date |
| Foresight (What-If) | gpt-4o | Explicit hypotheticals — "what if I switched regime / cut my budget by ₹1,000 / saved ₹500 more toward a goal" |

A user never has to ask to be warned, either — client-side, no-LLM proactive alerts (ITR deadline,
regime-declaration window, deduction headroom, stale payslip/statement, over-budget category,
approaching goal deadline) surface unprompted as dismissible banners, dismissal scoped per-day per
alert via `localStorage`.

## Deployment

| Resource | What | Where |
|---|---|---|
| `paynexus-api` | V1 backend, Docker container | Azure App Service (Basic B1, `indiasouthcentral`) |
| `paynexus-api-v2` | V2 backend, Docker container — **same App Service Plan as V1** (shared B1 compute, no extra plan cost) | Azure App Service (Basic B1, `indiasouthcentral`) |
| `paynexus-web` | V1 frontend | Azure Static Web Apps (Free tier) |
| `paynexus-web-v2` | V2 frontend | Azure Static Web Apps (Free tier) |
| `paynexus-db-ramya` | PostgreSQL 16 + `pgvector`, separate `paynexus` (V1) / `paynexus_v2` (V2) databases on the same server | Azure Database for PostgreSQL Flexible Server (Burstable B1MS) |
| `ramya192/paynexus-backend` | Backend container image — `:latest`/`:<sha>` tags for V1, `:v2-latest`/`:v2-<sha>` for V2, same repo | Docker Hub (free tier) |

CI/CD: two independent workflows, so V1's and V2's *builds* never cross-trigger each other —
`.github/workflows/deploy.yml` (pushes to `main` → `paynexus-api`/`paynexus-web`) and
`.github/workflows/deploy-v2.yml` (pushes to `v2-dev` → `paynexus-api-v2`/`paynexus-web-v2`). Each
backend job builds+pushes its own image tag to Docker Hub; each App Service has its own Continuous
Deployment webhook, both registered on the same `ramya192/paynexus-backend` Docker Hub repo since
Docker Hub's classic webhooks aren't tag-scoped — a push to either branch pings *both* webhooks, but
each App Service's CD webhook only ever re-pulls the specific tag it's configured for, so the
"wrong" trigger just costs one harmless redundant restart on the other app, never a wrong deploy.
Both webhooks need "SCM Basic Auth Publishing Credentials" enabled (Settings → Configuration) to
even retrieve their URL from Deployment Center — found disabled on both apps (silently breaking
auto-deploy, V1 probably for a while) and fixed 2026-08-17, re-verified against a real push after.
This is also why V2 has its *own* separate database (`paynexus_v2`) rather than sharing V1's live
one — V2's still-evolving feature set writing into the same store V1's real users are on would be a
real data-integrity risk, not just a deploy-pipeline one. Real ongoing cost: **~$34/month** (Postgres
+ one shared App Service Plan; Static Web Apps and Docker Hub are free, and a second App Service on
the *same* Basic B1 plan doesn't add plan cost, just shares its compute), currently running against
a $200 Azure free-trial credit with a hard spending limit (no card can be charged).

**Account Aggregator (AA) integration** — automatic bank-statement fetch via Setu/FinVu — was
built and tested against both providers' real API contracts, then removed entirely rather than
shipped unusable: both require FIU registration with RBI/SEBI/IRDAI (Setu additionally gates its
KYC step on a GSTIN), a structural requirement for registered financial institutions that doesn't
have a self-serve path for an individual developer. Bank statements are uploaded manually (CSV or
PDF, parsed client-side/server-side with no AA dependency) instead — a known, defensible scope
limitation, not a bug.

**Password recovery** — there is no "forgot password" flow, and this is by design, not an
oversight. The AES-256-GCM key that encrypts every payslip, financial-profile, transaction, goal,
and budget row is derived *directly* from the user's password (`deriveEncryptionKey`, PBKDF2 +
the server-issued salt) — there is no separate data-encryption-key wrapped by the password, so
there is no secret on the server side that could ever reissue access to already-encrypted data.
Resetting a password without knowing the old one would either (a) permanently orphan every row
encrypted under the old key, since a new password derives a completely different key, or (b)
require the server to hold something capable of recovering the old key, which would mean the
server *can* decrypt user data after all — directly contradicting the privacy guarantee this
system is built around (§4: the server never sees plaintext financial data). This is the same
trade-off real zero-knowledge systems make (e.g. a password manager whose vault is genuinely
unrecoverable without its master password or a separately-issued recovery code) — not a gap that
was missed, a property that was chosen. A real fix would mean introducing a proper key-encryption-
key layer plus a one-time recovery code issued (and shown exactly once) at registration, which is
real, scoped, future work, not something to bolt on without the recovery-code mechanism it
actually depends on.

## Agent Framework migration (V2.1)

V2's orchestrator (LangGraph `StateGraph`) was replaced with Microsoft's **Agent Framework**,
running against **Azure AI Foundry** — deliberately scoped to the agent layer only: the FastAPI
app, auth, and encrypted CRUD are unchanged, and this is genuinely wired into the app (not a
standalone spike) — `api/routes/chat.py`'s live `/chat` endpoint runs on it, verified against a
real running server, not just unit tests.

**Two architecture calls made deliberately, given no deadline pressure, favoring the stronger
engineering story over the lower-risk default:**
- **Orchestration**: `agent_framework_orchestrations.ConcurrentBuilder`, with each agent wrapped in
  a custom `Executor` rather than a bare `Agent` — `ConcurrentBuilder`'s default dispatcher
  broadcasts one shared input to every participant, which would break the privacy boundary that
  keeps e.g. Regulatory Intelligence from ever seeing financial data; each custom executor ignores
  the broadcast and builds its own narrow, state-scoped prompt instead. `ConcurrentBuilder` also
  turned out to require at least 2 participants (a real library constraint, not documented up
  front) — the common case of exactly one selected agent short-circuits around it entirely rather
  than padding a real turn with a fake extra participant.
- **Runtime client**: `FoundryChatClient` against a real Azure AI Foundry project, not the simpler
  `OpenAIChatClient` + plain API key path (confirmed to work with zero Azure dependency, and would
  have been the safer default). This meant standing up a genuine Foundry **Agent Service** capability
  host — Storage + Cosmos DB (serverless) + AI Search (Free tier), all on the cheapest viable SKUs —
  since the Responses API `FoundryChatClient` calls needs somewhere to persist conversation state.

**Real engineering, not just wiring two SDKs together** — three examples: (1) a completely
empty-body `403` from the Foundry gateway that survived every documented RBAC fix (both account-
and project-scope roles, correctly assigned) turned out to be the Agent Service capability host
never having been provisioned at all — diagnosed by isolating a plain-account call (worked) from
the project-scoped one (didn't), not by guessing; (2) under the test suite's rapid real-LLM traffic,
Foundry's shared "GlobalStandard" capacity tier occasionally returned a schema-valid but contentless
completion — reproduced 0/8 times in isolation, confirmed as a load characteristic (not a prompt
bug) by tripling deployment capacity and watching it persist, then mitigated with a content-aware
retry heuristic (checks for an actual ₹ figure, not just response length, after an earlier version
of the check missed a longer-but-still-evasive answer); (3) a state-partial dict smuggled through
`ConcurrentBuilder`'s message-passing as JSON text silently lost its `LLMCallMetrics` objects'
Pydantic typing on the way back out — caught only once a test was strengthened to actually exercise
the real concurrent path instead of a short-circuit that happened to skip the bug entirely.

Every agent's JSON contract is now a Pydantic model instead of a hand-parsed dict (`response.value`
returns an already-validated instance, not raw text needing `json.loads` + `try/except`), and the
intent classifier lost its manual JSON parsing the same way.

## Stack

| Area | Choice | Why |
|---|---|---|
| Orchestration | Microsoft Agent Framework — `ConcurrentBuilder` (V2.1; V2 used LangGraph `StateGraph`) | Typed executors, structured-output classification, real concurrent fan-out |
| Frontend | React 19 + TypeScript + Vite | Current stable, fast dev loop |
| Styling | Tailwind v4, CSS-first via `@theme` | No separate config file, current major version |
| Frontend state | Zustand | One small store per concern (auth, chat, goals, budget, statements, alerts UI, …) |
| Encryption | Client-side AES-256-GCM (PBKDF2-derived key) | Server never sees plaintext financial data |
| Vector store | pgvector on the same Postgres instance | One database instead of a separate vector service |
| LLM provider | Azure AI Foundry (gpt-4o / gpt-4.1-mini via Agent Framework's `FoundryChatClient`; V2 called OpenAI directly), local Ollama fallback for hybrid agents | Genuine Foundry Agent Service integration — see migration section above |
| Statement ingestion | CSV parsed directly (no LLM); PDF text extracted client-side (pdfjs-dist) and structured via GPT-4o | The PDF itself never reaches the server, only extracted text does |

## Testing

- **`backend/tests/`** — 276 pytest tests, zero setup (`cd backend && pytest`) — unit tests covering
  every concrete bug this build found across V1, V2, and the V2.1 Agent Framework migration (tax
  slab math, deduction gaps, trends, compression, table dedup, budget period-proration,
  duplicate-transaction-ID disambiguation, Ollama's markdown-fence JSON issue,
  `ConcurrentBuilder` fan-out/merge wiring), plus `@pytest.mark.integration` tests that hit the real
  Foundry/OpenAI APIs.
- **`backend/rag/eval.py`** — retrieval hit-rate@k, MRR, and generation keyword-coverage against a
  hand-verified ground-truth set. Current: 94% hit-rate, 0.853 MRR, 100% keyword coverage.
- **`backend/agent_eval/eval.py`** — the same keyword-coverage approach for narrated agent answers,
  plus forbidden-phrase checks for this build's recurring failure mode (a confidently *wrong*
  conclusion stated despite correct numbers in the same prompt).
- **`backend/compression/eval.py`** — real before/after token-cost measurement for context
  compression (Level 1 in-session sliding window, Level 2 cross-session summarization).
- **`.claude/skills/run-paynexus/`** — the agent-facing runbook: direct Python invocation, `curl`
  recipes, and Playwright drivers (`driver.mjs` for V1's flow, `v2_flows_driver.mjs` +
  `v2_flows_driver_part2.mjs` for V2's — registration through every CRUD flow, proactive alerts,
  the subscriptions filter, capability-gap responses, and cross-session memory, verified against
  the real network request, not LLM wording).

## Layout

```
paynexus-v2/
├── backend/
│   ├── agents/          Agent Framework orchestrator (orchestrator_v2.py) + 7 reasoning agents
│   ├── agent_eval/       answer-quality eval harness
│   ├── analytics/        spending trends, recurring-merchant/subscriptions detection
│   ├── budgeting/        budget vs. actual-spend checks
│   ├── categorization/   rule-based transaction categorization (+ LLM fallback)
│   ├── ingestion/        CSV statement parsing
│   ├── rag/              retriever, index builder, eval harness
│   ├── compression/      context compression + its eval harness
│   ├── security/         auth, password hashing
│   ├── db/                SQLAlchemy models, session handling
│   ├── tests/             265 pytest tests
│   ├── alembic/          migrations — alembic upgrade head before first run
│   ├── Dockerfile         real, tested container for App Service
│   └── ...                FastAPI app, statement/payslip extraction, tax computation modules
├── frontend/              React 19 + TypeScript + Tailwind v4 (Vite)
│   └── src/components/    Auth, Dashboard (tabs), Chat, ChatWidget, Alerts, GoalTracker,
│                          BudgetPlanner, StatementUploader, PayslipUploader, FinancialProfile
├── rag_documents/         Indian tax-law source docs embedded into pgvector
├── .claude/skills/run-paynexus/   agent-facing runbook — direct invocation, curl, Playwright
└── .github/workflows/     CI/CD to Azure (Docker Hub + Static Web Apps) — watches `main` only
```

## Quick start

Needs `backend/.env` filled in (copy `backend/.env.example`) — `OPENAI_API_KEY` (still used by
extraction/categorization helpers outside the 7 orchestrator agents), `FOUNDRY_PROJECT_ENDPOINT`
(the Azure AI Foundry project the 7 agents actually call), and a `DATABASE_URL` pointing at a
Postgres with the `vector` extension enabled (`CREATE EXTENSION IF NOT EXISTS vector;`). Foundry
auth is via `DefaultAzureCredential` — run `az login` once locally before starting the backend;
there's no separate Foundry API key to set.

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
