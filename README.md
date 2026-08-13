# PayNexus

> "Your pay, explained. Your finances, guided."

A multi-agent agentic AI system that helps salaried employees in India understand their payslip, tax
regime, and financial decisions — not a chatbot, a coordinated team of four specialized agents behind
a LangGraph orchestrator.

Full spec: see [`paynexus_context.md`](../paynexus_context.md) one level up (or the copy in this folder,
`PROJECT_CONTEXT.md`). Feed that file to Claude Code at the start of every build session and follow the
build order in its Section 13 — do not skip phases.

## Status

Following the build order in `PROJECT_CONTEXT.md` §13:

**Phase 1 — Foundation** ✅
1. Project scaffold
2. Config module (`backend/config.py`)
3. Database models and connection — `backend/db/database.py` (engine, session factory, `get_db`), `backend/db/models.py` (`User`, `PayslipSnapshot`, `SessionSummary` — ciphertext-only tables, see PROJECT_CONTEXT.md §4)
4. Auth system — `backend/security/encryption.py` (per-user salt generation for client-side PBKDF2, plus an unrelated server-side Fernet helper), `backend/security/auth.py` (JWT issue/verify, bcrypt password hashing, `get_current_user` dependency), `backend/api/routes/auth.py` + `backend/api/models/user.py` (`POST /auth/register`, `POST /auth/login` — not yet mounted on an app; that's Phase 4)

**Phase 2 — RAG Pipeline** ✅
5. Document loader (`backend/rag/loader.py`) — loads `.pdf`/`.txt`/`.md` from `rag_documents/`
6. Index builder (`backend/rag/build_index.py`) — run once via `python -m rag.build_index` from `backend/`
7. Retriever (`backend/rag/retriever.py`) — top-k=5 similarity search, used by the Regulatory Agent

`rag_documents/` itself is still empty — see `rag_documents/README.md` for the source list to add before
`build_index.py` has anything to embed.

**Phase 3 — Agents** ✅
8. Payslip Reasoning (`backend/agents/payslip_agent.py`) — Agent 1, GPT-4o, structured JSON output
9. Regulatory Intelligence (`backend/agents/regulatory_agent.py`) — Agent 2, hybrid model via `agents/llm.py`, RAG-grounded
10. Financial Nudge (`backend/agents/nudge_agent.py`) — Agent 3, hybrid model, reads `compression/context_compressor.py` output
11. Orchestrator (`backend/agents/orchestrator.py`) — Agent 4, LangGraph `StateGraph`: intent classification → fan-out → assembler. Compiled graph exported as `paynexus_graph`.

**Phase 4 — API** ✅
12. FastAPI app + streaming chat (`backend/api/main.py`, `backend/api/routes/chat.py`, `backend/api/models/chat.py`) — `POST /chat` runs `paynexus_graph` and streams progress as Server-Sent Events, driven by LangGraph's `stream_mode="updates"` so `{"event": "agent_active", "agent": ...}` fires as each agent node actually finishes, not simulated
13. Payslip save/fetch (`backend/api/routes/payslip.py`, `backend/api/models/payslip.py`) — `POST /payslip/save`, `GET /payslip/history`, ciphertext in and out, never decrypted server-side
14. Wired: `api/main.py` mounts `auth`, `chat`, and `payslip` routers, adds CORS (origins configurable via `CORS_ORIGINS` in `.env`), and exposes `GET /health`. Schema setup is Alembic's job now (`alembic upgrade head`) — `api/main.py` no longer calls `init_db()` on startup; see "Pending issues resolved" below for why.

### Live testing status (Aug 2026 — Azure Postgres + real OpenAI key)

Verified actually running, not just syntax-checked:
- ✅ `pip install -r requirements.txt` — clean install (`langgraph` resolved to **1.2.11**, well past the `>=0.2`
  pin from Phase 3 — worth knowing if you touch `agents/orchestrator.py`, though it compiled and ran fine as-is)
- ✅ DB connectivity — `init_db()` against Azure Database for PostgreSQL (pgvector-enabled) created all three
  tables with no errors
- ✅ Agent 1 (Payslip Reasoning) standalone — correct HRA exemption math (least-of-three, ₹13,000 on a
  ₹20,000/₹18,000-rent/metro example), structured JSON parsed clean
- ✅ Agent 4 (Orchestrator) end-to-end — `paynexus_graph.invoke(...)` on a payslip-only query: intent
  classification, conditional fan-out, and assembler merge all worked correctly under langgraph 1.2.11
- ✅ Agent 3 (Financial Nudge) standalone — **found and fixed a real bug**: GPT-4o-mini initially got 80C
  gap arithmetic wrong (said ₹5,000 remaining on a ₹1,50,000 limit with ₹45,000 invested — should be
  ₹1,05,000). Fixed by adding an explicit "show the subtraction inline" instruction to its system prompt;
  retested and it now computes correctly. This is a real instance of the exact failure mode §14 cites as
  the reason Agent 1 stays on GPT-4o — Agent 3 has no equivalent hard guarantee, only a stronger prompt, so
  don't treat this as fully closed, just meaningfully mitigated.
- ✅ Agent 2 (Regulatory Intelligence) — RAG pipeline built and tested end-to-end. `rag_documents/` now has 4
  real government documents (fetched via WebFetch/WebSearch — see "RAG corpus" below), indexed into pgvector
  (65 chunks). Tested with an on-topic query (regime-default question — accurate, grounded answer) and a
  deliberately off-topic one (HRA formula, not indexed) — it correctly said the retrieved context didn't
  cover it instead of guessing. Also fixed a real bug along the way: `rag/loader.py` was ingesting
  `rag_documents/README.md` itself as a 5th "source document" (it's a `.md` file, matched the loader's own
  filter) — excluded it by filename now.
- ✅ Full API, live against `uvicorn` — `POST /auth/register` → `POST /auth/login` → `POST /chat`
  (streaming) → `POST /payslip/save` → `GET /payslip/history`, all tested with `curl`. Found and fixed a
  second real bug along the way: **`passlib` (unmaintained since 2020) crashes against `bcrypt>=4.1`** —
  its internal backend self-test hard-errors with `ValueError: password cannot be longer than 72 bytes`
  before ever touching the actual password. Replaced `security/auth.py`'s passlib `CryptContext` with
  direct `bcrypt.hashpw`/`checkpw` calls (72-byte truncation handled explicitly, matching bcrypt's own
  hard limit) — removed the `passlib` dependency entirely rather than pin to an old, and also unmaintained,
  bcrypt version. `/payslip/history` correctly returned `[]` in this test — expected, not a bug, since it
  reads `SessionSummary` (nothing writes there yet), not `PayslipSnapshot` (which `/payslip/save` does
  write to and which round-tripped correctly).
- ✅ Frontend against the live backend, driven headlessly via Playwright (Node.js + Playwright installed
  fresh this session — neither existed on this machine before): register → enter a payslip → ask a question
  → agent indicator → final answer, all confirmed by screenshot, zero browser console errors. Found and
  fixed a third real bug in the process: the assembler was dumping Agent 1's raw JSON (literal `{"explanation":
  ...}`, escaped `\n` and all) straight into the chat bubble instead of prose — added `_format_agent_response()`
  to `orchestrator.py`'s assembler, which renders the `explanation` field as text and `follow_up_suggestions`
  as a bullet list, leaving Agent 2/3's plain-text responses untouched. Confirmed the fix once and *seemed*
  to still see raw JSON on the second check — turned out to be `uvicorn --reload`'s WatchFiles reloader
  silently not picking up the change on Windows, not the fix being wrong. Killed the server and started a
  completely fresh process to confirm; worth remembering if a fix doesn't seem to take effect here again.

**All items in the original testing plan (below) are now complete.**

### RAG corpus (Aug 2026)

`rag_documents/` currently has 4 of the 10 source documents originally scoped in this file's own README:

| Topic | Status |
|---|---|
| IT Act sections (80C, 80D, 80CCD, 10(13A) HRA, 10(14), 192, 194) | ❌ Every fetch attempt at `incometaxindia.gov.in` (where the statutory text lives) returned HTTP 403 |
| Budget 2024-25 Finance Bill | ❌ Not sourced |
| Budget 2025-26 highlights | ✅ `budget_2025-26_highlights.txt` — headline figures only (₹12L/₹12.75L threshold, ₹75,000 standard deduction, TDS rationalization), not the full Finance Bill |
| New vs old regime comparison | ✅ `new_vs_old_tax_regime_faqs.md` — detailed 14-Q&A FAQ, the strongest document in the corpus |
| EPFO circulars (PF wage ceiling, VPF) | 🟡 `epfo_employer_information_booklet.txt` — general employer booklet, not the specific wage-ceiling circulars |
| State Professional Tax slabs | ❌ Not sourced |
| HRA exemption rules | ❌ Not sourced as a document (Agent 1's system prompt hardcodes the formula independently, so payslip questions aren't blind here — only Agent 2's regulatory answers are) |
| Standard deduction history | 🟡 Current figure only, via the Budget doc |
| Form 16 structure | ❌ Not sourced |
| TDS Section 192 detailed guide | 🟡 `tds_compliance_faqs.md` — mostly the 1961→2025 Act transition, not full Section 192 mechanics |

Two things worth knowing if you extend this corpus later: `incometaxindia.gov.in` (both the `/w/...` wiki
pages and the `/Acts/...` mirror) blocked WebFetch outright with 403 — that's where the actual Section 80C/
80CCD/10(13A) statutory text lives, so it needs a different retrieval approach (a real browser session, a
different mirror, or manually downloading and dropping the PDFs into `rag_documents/` yourself). Separately,
`static.pib.gov.in` PDFs downloaded fine but WebFetch's own summarizer refused to reproduce their text
("copyright" caution on public government material) — worked around by extracting the raw PDF text with
`pypdf` directly instead of relying on the fetch tool's summary.

~~Known gaps~~ — CORS, Level 2 compression, and Alembic migrations were all resolved in a later session;
see "Pending issues resolved" below.

**Phase 5 — Frontend** ✅ (items 15–19 from §13, plus an Auth screen since nothing else works without login)
15. React 19 + TS + Vite scaffold — `index.html`, `tsconfig*.json`, `src/main.tsx`, Tailwind v4 via `src/index.css`
16. Client-side encryption — `src/crypto/clientEncryption.ts`: PBKDF2 key derivation + AES-256-GCM encrypt/decrypt, both exercised from `AuthScreen` (key derivation on login/register) and `ManualEntryForm`/payslip save path
17. Chat UI with agent indicator — `components/Chat/*` (`ChatInterface`, `MessageList`, `UserMessage`, `AgentMessage`, `ChatInput`) + `components/AgentIndicator/AgentIndicator.tsx`, driven by real `agent_active` SSE events from `api/chat.ts`'s hand-rolled SSE reader (not `EventSource`, which can't send the `Authorization` header `/chat` requires)
18. Payslip uploader — `components/PayslipUploader/{PayslipUploader,ManualEntryForm}.tsx`, manual entry only
19. Nudge card — `components/NudgeCard/NudgeCard.tsx`, built but **not wired into ChatInterface** (see gap below)

Also added: `store/{authStore,chatStore,payslipStore,sessionHistoryStore}.ts` (Zustand, replacing the
doc's original Context+`useReducer` plan per the earlier stack update) and `api/{client,auth,chat,payslip}.ts`.

Frontend is now verified end-to-end via Playwright (see "Pending issues resolved" below for the session
that installed Node.js + Playwright and did this) — register → payslip → chat → agent indicator → answer,
zero console errors, confirmed by screenshot.

Remaining frontend gaps (both new-feature work, not bugs):
- **PDFParser isn't built.** `PayslipUploader` only offers manual entry; client-side PDF→JSON extraction
  from the doc's component tree (§10) is still open.
- **PayslipDashboard/BreakdownChart isn't built.** `recharts` is in `package.json` but nothing uses it yet.
- Auth state (JWT + derived AES key) lives in memory only, not persisted — refreshing the page logs you out.
  Deliberate for now (the alternative is the key sitting in `localStorage`), flagging it as a product decision
  to revisit, not an oversight.
- `esbuild`/Vite dev-server CORS vulnerability (`npm audit` — moderate, dev-only, fix needs a breaking
  Vite 5→8 upgrade not yet attempted).

**Not yet started — Phase 6 (Deployment).**

## Pending issues resolved (Aug 2026, continued session)

A later session went through the gaps this file used to list under "Known gaps"/"Known frontend gaps" —
skipping RAG corpus completeness and Phase 6, which are separate, larger efforts — and closed out the rest:

- **CORS** — `config.CORS_ORIGINS` (comma-separated, env-configurable) replaces the hardcoded
  `["http://localhost:5173"]` in `api/main.py`.
- **Stale `langgraph`/`openai` pins** — tightened to `>=1.2,<2.0` and `>=2.0,<3.0` respectively, matching
  what was actually verified working (1.2.11 / 2.54.0), so the *next* accidental major-version jump doesn't
  happen silently the way this one did.
- **Alembic migrations** — `backend/alembic/`, one initial migration covering `users`, `payslip_snapshots`,
  `session_summaries`. Two real snags along the way, both now documented in `.claude/skills/run-paynexus/SKILL.md`'s
  Gotchas: autogenerate initially proposed *dropping pgvector's own tables* (not part of this app's
  SQLAlchemy models, so it read them as "should be removed" — fixed with an `include_object` filter in
  `env.py`), and the DB password's URL-encoded `%` character broke Python's `configparser` interpolation
  when routed through Alembic's config object — fixed by building the engine directly from
  `config.DATABASE_URL` instead. `api/main.py` no longer calls `init_db()` on startup — the two don't mix
  safely (see `db/database.py`'s updated docstring).
- **NudgeCard wired in** — `nudge_agent.py` now returns structured `{title, detail, impact}` JSON (same
  pattern as Agent 1), `orchestrator.py`'s assembler parses it into a separate `nudge_card` field (kept out
  of the main prose, which still gets a one-line `💡 <title>` pointer so the chat bubble is never empty when
  Nudge is the only agent that ran), `/chat`'s SSE final event carries it as `nudge`, and
  `AgentMessage.tsx` renders `<NudgeCard>` when present. Verified live: with no history, correctly renders
  "not enough history" (`impact: null`, not fabricated); with real history (see below), a real ₹ figure.
- **Level 2 context compression, fully wired** — this was the big one. New endpoints `POST /chat/summarize`
  (server computes the plaintext summary via `compress_session_summary`, since only the client holds the
  AES key — same trust boundary `/chat` already uses for `payslip_data`) and
  `POST /payslip/session-summary` (persists the client-encrypted result). `AuthScreen.tsx` fetches +
  decrypts history on login (per-row error handling, so one bad row can't block login);
  `ChatInterface.tsx` now passes real `session_history` instead of a hardcoded `[]`; `App.tsx`'s logout
  handler gathers the session's exchanges from `chatStore`, calls `/chat/summarize`, encrypts the result,
  and calls `/payslip/session-summary` before actually logging out (skipped entirely if nothing was asked
  this session, so an idle logout doesn't burn an OpenAI call). **Verified with a full round-trip**:
  register → chat → logout → log back in → ask a nudge question — the Nudge Agent's answer no longer says
  "not enough history," confirming the summary genuinely persisted, decrypted, and fed back in.

All of the above was verified live against the running app, not just written — including a full
register→chat→logout→login→chat Playwright pass.

See `PROJECT_CONTEXT.md` §13 for all six phases.

## Testing plan (once credentials are provided)

Per-agent, in isolation, before wiring end-to-end:
1. `rag/build_index.py` against a couple of real source docs in `rag_documents/`, confirm `rag/retriever.py` returns sane chunks
2. `agents/payslip_agent.py` directly with a sample payslip dict
3. `agents/regulatory_agent.py` directly with a regulatory question
4. `agents/nudge_agent.py` directly with a fabricated session-history summary
5. `agents/orchestrator.py`'s `paynexus_graph.invoke(...)` for routing correctness (single-intent and multi-intent queries)
6. Full API: `POST /auth/register` → `POST /chat` streaming → `POST /payslip/save` → `GET /payslip/history`
7. Frontend against the running backend: register → enter a payslip manually → ask a question → confirm the
   agent indicator lights up per SSE event and the final answer renders

## Stack decisions since the original context doc (Aug 2026)

`PROJECT_CONTEXT.md` is the original spec; these are updates layered on top of it, already
reflected in this scaffold:

| Area | Original doc | Now | Why |
|---|---|---|---|
| Frontend build | Vite | Vite (unchanged) | Already current |
| React | 18 | **19** | Current stable |
| Styling | Tailwind v3 + `tailwind.config.js` | **Tailwind v4** — CSS-first via `@theme` in `src/index.css`, `@tailwindcss/vite` plugin, no config file | Current major version, simpler setup |
| Frontend state | Context + `useReducer` | **Zustand** | Less boilerplate for chat/session state |
| Vector store | FAISS index persisted to Azure Blob | **pgvector** extension on the existing Postgres (`DATABASE_URL`) | One fewer service — no index file to build/persist/sync |
| LLM provider | OpenAI GPT-4o / GPT-4o-mini | **Unchanged — OpenAI**, kept deliberately (existing paid plan) | — |

Everything else (LangGraph orchestration, the four-agent split, client-side AES-256-GCM,
context compression, the Ollama hybrid-inference toggle) stands as written in `PROJECT_CONTEXT.md`.

## Layout

```
paynexus/
├── backend/
│   ├── alembic/      migrations — alembic upgrade head before first run
│   └── ...           FastAPI + LangGraph agents, RAG pipeline (pgvector), DB, security
├── frontend/          React 19 + TypeScript + Tailwind v4 chat UI (Vite)
├── rag_documents/     Indian tax source docs embedded into pgvector (4 of 10 topics — see RAG corpus above)
├── .claude/skills/run-paynexus/   agent-facing skill: launch + drive the app (direct invocation, curl, Playwright)
└── .github/workflows/  CI/CD to Azure
```

## Quick start

Needs `.env` filled in first (copy `.env.example`) — `OPENAI_API_KEY` and a `DATABASE_URL` pointing at a
Postgres with the `vector` extension enabled (`CREATE EXTENSION IF NOT EXISTS vector;`).

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head        # schema setup — required once, before first run
python -m rag.build_index   # only once rag_documents/ has real source files in it
uvicorn api.main:app        # no --reload — see .claude/skills/run-paynexus/SKILL.md Gotchas

# frontend
cd frontend
npm install
npm run dev
```

Both sides are now verified working this way — see "Pending issues resolved" above and
`.claude/skills/run-paynexus/SKILL.md` for the full agent-facing runbook (direct Python invocation,
`curl` recipes, and the Playwright driver), all with commands actually re-run to confirm they work as
written, not just described.
