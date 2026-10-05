# PayNexus

> "Your pay, explained. Your finances, guided."

A multi-agent agentic AI system for salaried employees in India — not a chatbot, a coordinated team
of eight specialized reasoning agents behind an orchestrator, covering payslips, tax regulation,
spending, budgeting, savings goals, what-if planning, and a monthly recap in one place.

**V1** (payslip + tax regulation only, 3 agents) is live: [nice-desert-0837ea310.7.azurestaticapps.net](https://nice-desert-0837ea310.7.azurestaticapps.net)
· `paynexus-api.azurewebsites.net` (backend API, currently stopped to consolidate hosting cost).
**V2** added bank statements, budgeting, savings goals, and scenario planning — built, tested, and
live-verified end to end. Deployed to its own, separate Azure resources (own App Service, own
Static Web App, own database) rather than merged to `main`, so it never touches V1's production
traffic: [ambitious-pebble-083cdaf10.7.azurestaticapps.net](https://ambitious-pebble-083cdaf10.7.azurestaticapps.net)
· `paynexus-api-v2.azurewebsites.net` (backend API).
**V2.1** (this worktree, `foundry-v2`) is an agent-layer-only migration of V2's orchestrator from
LangGraph to Microsoft's **Agent Framework**, running against **Azure AI Foundry** (the
`paynexus-foundry` project) instead of calling OpenAI directly — the FastAPI app, auth, and
encrypted CRUD are untouched. **`foundry-v2` is the sole active branch and what the V2 Azure
resources above actually run.** See [Agent Framework migration](#agent-framework-migration-v21)
below for the full story.

## The story so far: V1 → V2 → V2.1

**V1** shipped first, and stayed small on purpose: 3 agents (Payslip, Regulatory, Nudge), LangGraph
orchestrator, OpenAI called directly. It's still live, on `main`, untouched by everything below.

**V2** started as a genuine question: could this same architecture carry a much bigger scope —
bank statements, budgeting, savings goals, scenario planning — without redesigning the
orchestration layer? It could. Built as its own branch (`v2-dev`) and its own Azure resources
(never merged to `main`, so V1's production traffic was never at risk while V2 was still
"still-evolving"), V2 grew to 7 agents on the exact same LangGraph `StateGraph` + direct-OpenAI
design V1 used, plus a client-side proactive-alerts layer V1 never had. It shipped, was
live-verified end to end, and ran in production for weeks.

**V2.1** started as a deliberate, portfolio-motivated question of its own, with no deadline
pressure: could V2's *same 7 agents* run on Microsoft's Agent Framework against Azure AI Foundry
instead — a stronger interview story than "yet another LangGraph app," and closer to what
enterprise Azure shops actually reach for? Scoped tightly to the agent layer only (FastAPI, auth,
and encrypted CRUD untouched) so the answer could be proven without re-risking everything V2 had
already gotten right. It could — genuinely wired into the live `/chat` endpoint, not a spike — and
then kept growing past pure parity: a live orchestration deadlock found and fixed against the real
running server, a self-updating RAG web-search fallback, capacity-aware context compression, and
every V2 feature request that came in afterward (manual cash entry, credit-card billing-cycle
tracking) landed here instead of on `v2-dev`. From 2026-09-19 it also grew an eighth agent (Monthly
Digest), a logistic-regression categorization tier, live goal valuation, spending-trend projection
with charts, and a hardened CI/IaC pipeline — see [Beyond the original scope](#beyond-the-original-scope-v21)
below.

Once V2.1 had genuinely caught up feature-for-feature and then kept going, `v2-dev` became pure
overhead — two branches to keep in sync for one product. It was deleted from GitHub on
2026-09-13, and this branch (then still named `foundry-v3`, a name that made sense when a
`v2-dev` existed to disambiguate from) was renamed to `foundry-v2` the same day: PayNexus V2's
one and only branch now, full stop.

## Architecture

Two things drive most of the design decisions below: **every number a user sees traces to a Python
function, never an LLM's arithmetic** (tax slabs, deduction gaps, trends, overspending, goal
progress — computed once, quoted by whichever agent needs them), and **the server never sees
plaintext financial data** — payslip, financial-profile, bank-statement, goal, and budget rows are
all AES-256-GCM ciphertext end to end, encrypted/decrypted only in the browser.

```mermaid
graph LR
    User["Browser<br/>(React)"] <-->|ciphertext only| Backend
    Backend["FastAPI +<br/>Agent Framework Orchestrator"] --> Agents["8 Reasoning Agents"]
    Agents --> Foundry["Azure AI Foundry<br/>(paynexus-foundry)"]
    Backend <--> DB[("PostgreSQL<br/>+ pgvector")]
```

The Orchestrator (`agents/orchestrator_v2.py` — an Agent Framework structured-output intent
classifier plus plain `asyncio.gather` for the fan-out, as of the V2.1 migration below) classifies
each question and fans it out — concurrently — to whichever
of the eight agents actually apply; a payslip question hits one agent, "which regime should I pick
and how much would I save, and am I still on budget" might hit four. An explicit whole-picture
request ("how did I do this month?") is routed to the Monthly Digest agent *alone*, since it already
synthesizes what the individual agents would each say. Requests that try to add/edit/
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
| Foresight (What-If) | gpt-4o | Explicit hypotheticals — "what if I switched regime / cut my budget by ₹1,000 / saved ₹500 more toward a goal / contributed 2% more to PF" |
| Monthly Digest | gpt-4o | One flowing recap across payslip trends, spending, budget, and goals. Never sees a raw statement — it only weaves together figures Python already computed, so it adds no new source of numbers |

A user never has to ask to be warned, either — client-side, no-LLM proactive alerts (ITR deadline,
regime-declaration window, deduction headroom, stale payslip/statement, over-budget category,
approaching goal deadline) surface unprompted as dismissible banners, dismissal scoped per-day per
alert via `localStorage`.

## Deployment

| Resource | What | Where |
|---|---|---|
| `paynexus-api` | V1 backend, Docker container | Azure App Service (Basic B1, `indiasouthcentral`) |
| `paynexus-api-v2` | V2 backend, Docker container — **same App Service Plan as V1** (shared compute, no extra plan cost) | Azure App Service (Free F1, `indiasouthcentral`) |
| `paynexus-web` | V1 frontend | Azure Static Web Apps (Free tier) |
| `paynexus-web-v2` | V2 frontend | Azure Static Web Apps (Free tier) |
| `paynexus-db-ramya` | PostgreSQL 16 + `pgvector`, separate `paynexus` (V1) / `paynexus_v2` (V2) databases on the same server | Azure Database for PostgreSQL Flexible Server (Burstable B1MS) |
| `ramya192/paynexus-backend` | Backend container image — `:latest`/`:<sha>` tags for V1, `:v2-latest`/`:v2-<sha>` for V2, same repo | Docker Hub (free tier) |

**Infrastructure as Code**: `infra/v2-core.bicep` describes the App Service Plan, `paynexus-api-v2`,
`paynexus-web-v2`, and (added 2026-09-14) an Application Insights resource + its Log Analytics
workspace declaratively — the pieces above that were originally provisioned by hand via one-off
`az` CLI commands. Deliberately scoped to just those (not the shared Postgres server or the
Foundry capability-host stack — see the file's own header comment for why those specifically stay
manual). Validate without deploying anything: `az bicep build --file infra/v2-core.bicep`. Never
applied automatically by CI — a real deploy is a deliberate `az deployment group create`, run by a
human, not triggered by a push; this file has genuinely been used for one such real deploy
(2026-09-20 — see the Observability section below for what it turned up). If a deploy ever does go
wrong, `infra/ROLLBACK.md` has the actual steps — a backend Docker re-tag/re-push, or a frontend
Static Web Apps re-deploy — not just a note that rollback is "possible."

CI/CD: two independent workflows, so V1's and V2's *builds* never cross-trigger each other —
`.github/workflows/deploy.yml` (pushes to `main` → `paynexus-api`/`paynexus-web`) and
`.github/workflows/deploy-v2.yml` (pushes to `foundry-v2` → `paynexus-api-v2`/`paynexus-web-v2`,
retargeted from the now-retired `v2-dev` on 2026-09-13, then renamed from `foundry-v3` the same
day). Each
backend job builds+pushes its own image tag to Docker Hub; each App Service has its own Continuous
Deployment webhook, both registered on the same `ramya192/paynexus-backend` Docker Hub repo since
Docker Hub's classic webhooks aren't tag-scoped — a push to either branch pings *both* webhooks, but
each App Service's CD webhook only ever re-pulls the specific tag it's configured for, so the
"wrong" trigger just costs one harmless redundant restart on the other app, never a wrong deploy.
Both webhooks need "SCM Basic Auth Publishing Credentials" enabled (Settings → Configuration) to
even retrieve their URL from Deployment Center — found disabled on both apps (silently breaking
auto-deploy, V1 probably for a while) and fixed 2026-08-17, re-verified against a real push after.
Every push runs `pytest`+coverage and (as of 2026-09-19) the frontend's own `npm test` — both
genuinely **blocking**, the same role `pytest` has always had; a broken test on either side stops
the deploy. Alongside those, `pip-audit` (dependency CVEs), `bandit` (this repo's own code), and
(once the image is built) `Trivy` (the actual container's OS-level CVEs) all run too, but
non-blocking, posting to the run summary rather than gating the deploy; see the Observability
section below for why non-blocking is a deliberate choice there, not a missing gate.
This is also why V2 has its *own* separate database (`paynexus_v2`) rather than sharing V1's live
one — V2's still-evolving feature set writing into the same store V1's real users are on would be a
real data-integrity risk, not just a deploy-pipeline one. Real ongoing cost: **~$34/month** (Postgres
+ one shared App Service Plan; Static Web Apps and Docker Hub are free, and a second App Service on
the *same* Basic B1 plan doesn't add plan cost, just shares its compute), currently running against
a $200 Azure free-trial credit with a hard spending limit (no card can be charged).

**Account Aggregator (AA) integration — roadmap, not shipped.** Automatic bank-statement fetch
through an Account Aggregator (Setu) is built and verified against Setu's *sandbox* (consent
creation and approval, data fetch, transaction mapping) on the separate `aa-sandbox-integration`
branch of the `paynexus-v2.1-aa-integration` folder. It is not merged and not part of what's
deployed. Two things stand between that and production: Setu's sandbox data-retrieval endpoint
intermittently hangs after a fetch has completed (raised with Setu support), and going live
requires registration as a financial-information user with the regulators, which has no
self-serve path for an individual developer. Until then, statements are uploaded manually (CSV or
PDF) — a known scope limit, not a bug.

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
- **Orchestration**: first built on `agent_framework_orchestrations.ConcurrentBuilder`, with each
  agent wrapped in a custom `Executor` (its default dispatcher broadcasts one shared input to every
  participant, which would break the privacy boundary that keeps e.g. Regulatory Intelligence from
  ever seeing financial data). It also required at least 2 participants, so single-agent turns had
  to short-circuit around it. **That version was replaced on 2026-09-11**: with 2 real agents it
  deadlocked completely inside the live uvicorn server (both `agent_active` events, then nothing for
  90+ seconds) yet ran fine in an isolated script — an interaction with the already-running event
  loop. The shipped design keeps Agent Framework for what it does well — `FoundryChatClient` calls
  and Pydantic structured output, including the intent classifier — and runs the selected agents with
  plain `asyncio.gather` over `asyncio.to_thread`. Same real concurrency, one code path for one agent
  or several, no JSON round-trip between agents, and `agent-framework-orchestrations` is no longer a
  dependency.
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
of the check missed a longer-but-still-evasive answer); (3) the `ConcurrentBuilder` deadlock
described above — found by reproducing it against the real running server, not by unit tests, and
resolved by dropping the library's workflow engine rather than working around it. (An earlier bug on
that path — state-partial dicts passed through its message-passing as JSON text silently lost their
`LLMCallMetrics` typing — disappeared with the same change, since `asyncio.gather` returns real
Python objects.)

Every agent's JSON contract is now a Pydantic model instead of a hand-parsed dict (`response.value`
returns an already-validated instance, not raw text needing `json.loads` + `try/except`), and the
intent classifier lost its manual JSON parsing the same way.

**A fourth example, found answering a real user question (2026-09-15):** "what would my net pay be
if I contributed 2% more to PF?" turned out to have no real answer — nothing anywhere in this
codebase actually computed a net pay figure. The Payslip Reasoning agent handed the LLM raw payslip
components and let it narrate/derive take-home in its own words, exactly the "LLM invents a number"
failure mode every other money calculation here (`tax_calculations.py`, `tax_slabs.py`,
`payslip_trends.py`) was specifically built to avoid — it had just never been noticed for net pay
itself. Fixed with a new `payslip_math.py` module (`compute_net_pay`, `compute_gross_pay`) used in
two places at once: the *existing* Payslip Reasoning agent's regular narration (a real, always-on
correctness fix — "why did my take-home drop" now cites an exact computed ₹ figure, including a new
net-pay trend across saved months, not just individual basic/HRA/TDS trends) and a new fourth
domain in the What-If Simulator (`payslip_field`/`payslip_delta_percent_of_basic` — the LLM extracts
the raw percentage the user stated, Python does the actual rupee arithmetic against real basic
salary, never the model). Live-verified against the real Foundry backend, not just unit tests: a
2% PF increase on a ₹70,000 basic correctly computed a ₹1,400/month net pay drop and the resulting
old-regime tax change, matched by hand against the slab math independently.

## Beyond the original scope (V2.1)

Added after V2.1 reached parity with V2, all under the same rule as everything else here: the number
comes from Python, the model only narrates it.

- **ML categorization tier.** Transactions are categorized by keyword rules first, then a
  confidence-gated TF-IDF + `LogisticRegression` tier, then the LLM as the last fallback
  (`categorization/ml_classifier.py`). Nothing is persisted: bank data is ciphertext at rest, so the
  frontend sends a sample of the user's own already-decrypted history with each request, the model is
  fit and used inside that one call, and it is discarded on return. It skips itself below 20 labeled
  examples or fewer than 2 categories, and defers to the LLM below 0.6 predicted probability.
- **Spending-trend projection + charts.** `analytics/trend_projection.py` fits a least-squares line
  (`scikit-learn`) once there are at least 3 periods of history — with fewer, a line fits perfectly
  and means nothing, so it returns nothing instead. Rendered as real charts in the UI (`recharts`).
- **Live goal valuation.** A savings goal can be linked to a fixed deposit (compound-interest math,
  quarterly compounding, no network call) or a mutual fund (real daily NAV via `mfapi.in`, which
  republishes AMFI data). Individual stocks were deliberately left out — FDs and mutual funds cover the
  real case. A failed price lookup leaves that one goal's live value blank rather than breaking the tab.
- **Monthly Digest agent** (the eighth agent above) and **payslip what-if math** (`payslip_math.py`,
  described in the migration section).

**Deliberately not built:** voice input (Whisper) and receipt image parsing (GPT-4V) were in the
original plan and dropped — manual cash entry closes the same gap more simply.

## Stack

| Area | Choice | Why |
|---|---|---|
| Orchestration | Agent Framework structured-output classifier + `asyncio.gather` fan-out (V2.1; V2 used LangGraph `StateGraph`; `ConcurrentBuilder` was tried and removed) | Real concurrent fan-out without the workflow engine that deadlocked under uvicorn |
| Frontend | React 19 + TypeScript + Vite | Current stable, fast dev loop |
| Styling | Tailwind v4, CSS-first via `@theme` | No separate config file, current major version |
| Frontend state | Zustand | One small store per concern (auth, chat, goals, budget, statements, alerts UI, …) |
| Charts | Recharts | Spending breakdowns and trend projection |
| Classical ML | scikit-learn (logistic regression, linear regression), NumPy | Small, explainable models where an LLM call would be slower and costlier |
| Encryption | Client-side AES-256-GCM (PBKDF2-derived key) | Server never sees plaintext financial data |
| Vector store | pgvector on the same Postgres instance | One database instead of a separate vector service |
| LLM provider | Azure AI Foundry (gpt-4o / gpt-4.1-mini via Agent Framework's `FoundryChatClient`; V2 called OpenAI directly), local Ollama fallback for hybrid agents | Genuine Foundry Agent Service integration — see migration section above |
| Statement ingestion | CSV parsed directly (no LLM); PDF text extracted client-side (pdfjs-dist) and structured via gpt-4o-mini (gpt-4.1-mini on Foundry) | The PDF itself never reaches the server, only extracted text does |
| Frontend testing | Vitest + React Testing Library | 289 tests (stores, API layer, all components) — see Testing below |

## Testing

- **`backend/tests/`** — 473 pytest tests (454 offline + 19 live-integration), zero setup (`cd backend && pytest`) — unit tests covering
  every concrete bug this build found across V1, V2, and the V2.1 Agent Framework migration (tax
  slab math, deduction gaps, trends, compression, table dedup, budget period-proration,
  duplicate-transaction-ID disambiguation, Ollama's markdown-fence JSON issue,
  concurrent `asyncio.gather` fan-out/merge wiring), plus `@pytest.mark.integration` tests that hit the real
  Foundry/OpenAI APIs.
- **Coverage: 80.0% branch coverage** (`pytest --cov=.`, config in `.coveragerc`) on the
  deterministic, non-integration tier — measured on application code only (test files and one-off
  eval/build scripts excluded from the denominator, since counting a test file's coverage of itself
  isn't meaningful). This undercounts real coverage: several agent node functions' actual LLM-call
  bodies are exercised only by the `@pytest.mark.integration` tier (real Foundry/OpenAI calls, not
  run in CI without live credentials), so their lines show as "missed" here despite being covered
  by a real test elsewhere. Generated on every CI run (`deploy-v2.yml`'s coverage summary step), not
  a one-off number.
- **`backend/rag/eval.py`** — retrieval hit-rate@k, MRR, and generation keyword-coverage against a
  hand-verified ground-truth set. Current (re-run 2026-10-04): 94% hit-rate, 0.853 MRR, 94% keyword coverage.
- **`backend/agent_eval/eval.py`** — the same keyword-coverage approach for narrated agent answers,
  plus forbidden-phrase checks for this build's recurring failure mode (a confidently *wrong*
  conclusion stated despite correct numbers in the same prompt). Current (re-run 2026-10-04): 10 hand-verified cases, 100% pass rate, 0 forbidden phrases stated — a small set, so read it as a regression guard, not a broad accuracy claim.
- **`backend/compression/eval.py`** — real before/after token-cost measurement for context
  compression (Level 1 in-session sliding window, Level 2 cross-session summarization).
- **`paynexus-v2.1-test-suite`** (a separate local project, not in this repo) — a live end-to-end
  pytest suite that makes real HTTP calls against a running backend and real Foundry calls, with an
  HTML report per run. Covers routing for every agent, cross-domain privacy isolation, tax-regime
  math hand-checked against Budget 2025-26, What-If, duplicate detection, and regression tests for a
  real Foundry hang and a regulatory cache false positive. Deliberately not mocked.
- **`.claude/skills/run-paynexus/`** — the agent-facing runbook: direct Python invocation, `curl`
  recipes, and Playwright drivers (`driver.mjs` for V1's flow, `v2_flows_driver.mjs` +
  `v2_flows_driver_part2.mjs` for V2's — registration through every CRUD flow, proactive alerts,
  the subscriptions filter, capability-gap responses, and cross-session memory, verified against
  the real network request, not LLM wording).
- **`frontend/src/` — 289 Vitest + React Testing Library tests** (`npm test`), a real, blocking CI
  gate alongside `pytest` rather than an afterthought: all 10 Zustand stores, all 8 API modules
  (including a hand-rolled Server-Sent-Events stream parser test for the chat endpoint's manual SSE
  reader), and all 27 components — asserting on actual branch conditions and derived state (a
  goal's live-valuation override, a form's error-recovery path, a component's accessibility label
  wiring), not snapshots. Writing this suite itself surfaced and fixed several real, previously-
  shipped bugs, the same "found via a real test, not assumed correct" standard the backend section
  above holds itself to: a decimal-formatting bug that leaked a raw prorated float into three
  separate UI surfaces (once found in one place, proactively grepped and fixed everywhere the same
  pattern existed); a credit-card statement's payment-retry flow where a failed save left a stale,
  still-clickable "Save" button rendered underneath the retry UI (risking a duplicate save attempt)
  while the actual retry-failure error message had its display condition inverted and could never
  be seen at all; and seven components missing `htmlFor`/`id` label associations entirely — a real
  accessibility gap where a screen reader announced no label for any of those fields.

## Performance (2026-09-13, real timed `/chat` calls against the live backend)

Small sample sizes on purpose — this measures actual real Foundry API latency, not a mock, so every
call has a real (small) cost:

| | Sample | Median | Range |
|---|---|---|---|
| Single-agent turn (classifier + 1 agent) | n=8 | **8.1s** | 6.7s–9.2s, plus one 26.6s cold-start outlier (first call after a fresh backend restart) |
| Multi-agent turn (classifier + 3 agents, concurrent fan-out) | n=4 | **8.5s** | 7.4s–12.8s |

The real finding: a 3-agent turn's median (8.5s) is barely above a 1-agent turn's (8.1s) — direct
evidence the `asyncio.gather`-based concurrent fan-out (see the migration section below) is doing
its job; agents run in parallel, not stacked serially, so adding agents costs latency roughly equal
to the slowest one, not the sum of all of them. The cold-start outlier is a separate, already-known
characteristic of Foundry's GlobalStandard capacity tier under an idle-then-first-call pattern, not
a fan-out cost.

## Unit economics (real, from one measured turn's actual `response.usage`)

A single-agent turn's real cost, straight from the app's own per-call cost tracking
(`agents/llm_metrics.py`, sourced from OpenAI/Foundry's own `response.usage`, never estimated):

| Call | Model | Tokens (in/out) | Cost |
|---|---|---|---|
| Intent classifier | gpt-4o | 1,865 / 8 | $0.00474 |
| Regulatory agent (this turn's 1 selected agent) | gpt-4.1-mini | 1,959 / 27 | $0.00083 |
| **Total, this turn** | | | **$0.00557 (~₹0.47)** |

The genuinely interesting finding here, not the headline number: **the classifier costs more than
the actual answer** — it runs on gpt-4o for classification accuracy, while this hybrid-tier question
was answered by the cheaper gpt-4.1-mini. The classifier is a fixed per-turn cost regardless of how
many agents get selected; a multi-agent turn adds roughly $0.0008–$0.005 per additional agent
depending on its tier (hybrid gpt-4.1-mini vs. cloud-only gpt-4o), so a 3-agent turn costs in the
neighborhood of **$0.011–$0.016 (~₹0.9–1.3)** — extrapolated from this same real per-call pricing,
not a second live measurement.

## Observability (2026-09-14)

Added specifically to close a gap: every number in the Performance and Unit economics sections
above came from a one-off manual measurement, not something anyone could go check live.

- **Application Insights, opt-in and off by default.** `api/main.py` only calls
  `configure_azure_monitor()` when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set — every local
  run, CI run, and test run has it unset, so this is a zero-behavior-change addition, verified
  both ways (import succeeds identically with the var unset, and with a syntactically-valid
  connection string set, no live resource needed to prove the wiring itself works). Auto-
  instruments FastAPI request latency/status/exceptions and outbound `httpx` calls with no
  per-route code once it's actually on.
- **`infra/v2-core.bicep` declares the Application Insights resource + its backing Log Analytics
  workspace**, wired to the backend Web App's own `APPLICATIONINSIGHTS_CONNECTION_STRING` app
  setting. **Deployed for real, 2026-09-20** (`az deployment group create`, run by hand, same
  "never applied automatically by CI" rule as the rest of this file — a real deploy is still a
  deliberate human decision, not a push side effect) — both resources are live in `paynexus-rg`,
  and the deploy was verified against the running app afterward (a real `POST /auth/register`
  succeeded post-deploy, confirming every other app setting survived intact), not just trusted
  from `provisioningState: Succeeded`. Both resources stay free at this app's traffic (App
  Insights' free 5GB/month ingestion grant). Two real region-availability bugs were found and
  fixed live in the process, not caught by `az bicep build` or even `what-if`: neither
  `Microsoft.OperationalInsights/workspaces` nor `Microsoft.Web/staticSites` has ever been
  available in `indiasouthcentral` (the resource group's own region) — the first needed a
  dedicated `centralindia` param for the new observability resources, and the second revealed that
  the live frontend has actually been running in **Central US** the whole time, a fact nobody had
  verified before. Application Insights' **Live Metrics**/**Transaction search** in the Azure
  Portal now show real traffic as the app is used.
- **CI now runs two more scans, both non-blocking (report, don't gate — a new finding shouldn't
  silently block a deploy with no human decision, same reasoning as the existing `pip-audit`
  step)**: `bandit` (static analysis of this repo's own Python code — pip-audit only covers
  third-party dependency CVEs) and `Trivy` (scans the actual container image being deployed for
  OS-level CVEs, not just `requirements.txt` on disk). Both post a summary to the run and upload a
  full report artifact. First real run of `bandit` found one genuine (low-severity) issue — a
  SHA1 hash used as a transaction dedup fingerprint (`models.py`), not for anything cryptographic
  — fixed by marking it `usedforsecurity=False` rather than suppressed; two other Low findings
  (a non-crypto `random.uniform()` call, a module-level `assert` sanity check) were reviewed and
  are correctly non-issues.
- **`infra/ROLLBACK.md`** — a written rollback runbook (re-tag/re-push the last-known-good Docker
  image, or point the App Service straight at it via `az webapp config container set`; re-run a
  past Static Web Apps deployment for the frontend). Explicitly documents what it *doesn't* cover
  too (no automated rollback trigger, no DB down-migration story) rather than overclaiming.

## Security review (2026-09-13)

A real pass, not a checkbox — direct code search for each finding, not assumed from the
architecture description above.

**Checked and confirmed solid:**
- **Broken Object Level Authorization (OWASP API1)** — every goal/budget/statement/payslip
  route checks `resource.user_id != current_user.id` before returning or mutating anything (16
  such checks across the route files, confirmed by direct `grep`) — a user cannot reach another
  user's data by guessing an ID.
- **CORS** — `allow_origins` reads from `CORS_ORIGINS`, defaults to `localhost` only; never a
  wildcard.
- **Auth fundamentals** — passwords hashed with `bcrypt` (not a fast general-purpose hash), JWTs
  expire in 60 minutes, and login already returns the *same* error for "no such user" and "wrong
  password" — a genuine anti-enumeration practice that predates this review, not added by it.

**Found and fixed:**
- **No rate limiting on `/auth/login` or `/auth/register` (OWASP API4)** — either could be hit as
  fast as the network allowed; a brute-force password guess or a registration-spam script had
  nothing slowing it down. Added `slowapi`-based limits (`security/rate_limit.py`): 10/minute on
  login, 5/minute on register (tighter, since spamming new accounts is the more expensive abuse
  case). Verified with real tests that actually trigger a 429 (`tests/test_auth_routes.py`), not
  just presence of the decorator.
- **No static analysis of this repo's own code (2026-09-14)** — `pip-audit` only ever covered
  third-party dependency CVEs, never bugs in code we wrote. Added `bandit` to CI (see
  Observability section above); its first real run found a SHA1 hash used as a non-cryptographic
  dedup fingerprint (`models.py`) — fixed by marking it `usedforsecurity=False` so the intent is
  explicit rather than leaving a bare call for the scanner to keep re-flagging.

**Found and disclosed, not fixed (no fix exists):**
- **`ecdsa` 0.19.2 has a known Minerva timing-attack CVE** (`PYSEC-2026-1325`, via `pip-audit`) — a
  transitive dependency (likely pulled in for JWT signing support), and the upstream project has
  explicitly stated side-channel attacks are out of scope for their project, with no planned fix.
  Low practical severity here (a timing side-channel needs sustained local network access to the
  signing operation, not a remote drive-by), disclosed rather than silently accepted. Now scanned
  on every CI run (`deploy-v2.yml`'s dependency vulnerability summary step), so a new CVE surfaces
  automatically instead of requiring someone to remember to run `pip-audit` locally.

**Not done, explicitly out of scope for this pass:** a full penetration test, SSRF/injection
fuzzing, and a formal threat model. This is a focused OWASP-API-Top-10-style pass against the
actual route code, not a substitute for one.

## Layout

```
paynexus-v2.1/
├── backend/
│   ├── agents/          Agent Framework orchestrator (orchestrator_v2.py) + 8 reasoning agents
│   ├── agent_eval/       answer-quality eval harness
│   ├── analytics/        spending trends, trend projection, goal progress, live FD/MF valuation
│   ├── budgeting/        budget vs. actual-spend checks
│   ├── categorization/   rules → logistic-regression tier → LLM fallback
│   ├── ingestion/        CSV statement parsing
│   ├── rag/              retriever, index builder, eval harness
│   ├── compression/      context compression + its eval harness
│   ├── security/         auth, password hashing
│   ├── db/                SQLAlchemy models, session handling
│   ├── tests/             473 pytest tests
│   ├── alembic/          migrations — alembic upgrade head before first run
│   ├── Dockerfile         real, tested container for App Service
│   └── ...                FastAPI app, statement/payslip extraction, tax computation modules
├── frontend/              React 19 + TypeScript + Tailwind v4 (Vite) — 289 Vitest tests (stores,
│                          API layer, all 27 components), `npm test`
│   └── src/components/    Auth, Dashboard (tabs), Chat, ChatWidget, Alerts, GoalTracker,
│                          BudgetPlanner, StatementUploader, PayslipUploader, FinancialProfile
├── infra/                 v2-core.bicep (App Service, Static Web App, App Insights) + ROLLBACK.md
├── rag_documents/         Indian tax-law source docs embedded into pgvector
├── .claude/skills/run-paynexus/   agent-facing runbook — direct invocation, curl, Playwright
└── .github/workflows/     CI/CD to Azure (Docker Hub + Static Web Apps) — `deploy-v2.yml` watches `foundry-v2`
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
