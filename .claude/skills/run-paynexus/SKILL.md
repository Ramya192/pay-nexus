---
name: run-paynexus
description: Build, launch, and drive PayNexus (FastAPI + LangGraph backend, React/Vite frontend) end-to-end on Windows. Use when asked to run PayNexus, start the backend or frontend, test an agent directly, hit the API with curl, screenshot the UI, or verify a change works in the real app.
---

All paths below are relative to the repo root (`paynexus/`) unless stated otherwise. This was built
and verified on **native Windows, Git Bash** — not a Linux container. There's no `xvfb`/`tmux` here;
skip any Linux-container advice you've seen elsewhere for this kind of skill. Two dev servers, three
ways to drive the app depending on what you're checking — pick the cheapest one that answers your
question:

| Checking... | Use |
|---|---|
| One agent's prompt/logic in isolation | **Direct Python invocation** — fastest, no servers needed |
| The API contract (auth, streaming, persistence) | **`curl` against `uvicorn`** |
| The actual UI a user sees | **Playwright driver** (`driver.mjs`) |

## Prerequisites

- Python 3.11+, a venv at `backend/.venv` with `pip install -r backend/requirements.txt` run.
- **Node.js.** Not installed by default on this machine — installed via `winget install OpenJS.NodeJS.LTS`.
  After install, PATH doesn't propagate to already-open shells; explicitly prepend it in Git Bash:
  ```bash
  export PATH="/c/Program Files/nodejs:$PATH"
  ```
  Put that at the top of every command block below that uses `node`/`npm`/`npx`.
- `backend/.env` filled in — `OPENAI_API_KEY` and `DATABASE_URL` (Azure Database for PostgreSQL with
  the `vector` extension enabled: `CREATE EXTENSION IF NOT EXISTS vector;`). See `.env.example`.
- `frontend/` deps: `npm install` (from `frontend/`).
- This driver's own deps: `npm install` (from `.claude/skills/run-paynexus/` — separate `package.json`,
  deliberately not merged into the frontend's own dependencies).

## Build / start the servers

```bash
# One-time (or after a schema change) — from backend/, venv activated
source .venv/Scripts/activate
alembic upgrade head
```

The app no longer creates tables on startup — that was `db.database.init_db()`'s `create_all`, removed
from `api/main.py` once Alembic existed, since the two don't mix safely (see Gotchas' Alembic entries).
Skipping this step means `/auth/register` and everything else DB-touching 500s on a fresh database.

```bash
# Backend — from backend/, venv activated
source .venv/Scripts/activate
PYTHONIOENCODING=utf-8 uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```bash
export PATH="/c/Program Files/nodejs:$PATH"
# Frontend — from frontend/
npm run dev   # → http://localhost:5173, proxies /auth /chat /payslip to :8000 per vite.config.ts
```

Run each in the background (Claude Code: `run_in_background: true` on the Bash call; from a real
terminal: separate windows, or `start` on Windows). **Do not add `--reload` to the uvicorn command** —
see Gotchas.

`PYTHONIOENCODING=utf-8` matters: Windows' console defaults to cp1252, which crashes on the ₹ symbol
the agents routinely emit.

## Run (agent path)

### 1. Direct Python invocation — cheapest, no servers needed

Import a node function straight from `backend/agents/` and call it with a hand-built state dict. This
is how every agent got its first real test in this project — no LangGraph, no HTTP, just the function:

```bash
cd backend && source .venv/Scripts/activate
PYTHONIOENCODING=utf-8 python -c "
from agents.payslip_agent import payslip_agent_node
state = {
    'user_query': 'Why did my take-home drop this month?',
    'payslip_data': {'month': '2026-07', 'basic': 50000, 'hra': 20000, 'tds': 8000, 'rentPaid': 18000, 'isMetro': True},
}
print(payslip_agent_node(state)['payslip_response'])
"
```

Same pattern for `agents.regulatory_agent.regulatory_agent_node` (needs the pgvector index built first
— `python -m rag.build_index`), `agents.nudge_agent.nudge_agent_node`, and the full graph via
`agents.orchestrator.paynexus_graph.invoke(state)`.

### 2. `curl` against the running API

```bash
# Register (or /auth/login if the user already exists) — returns a JWT + encryption_salt
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "TestPass123"}'

# Save the token, then stream a chat response (SSE — curl -N disables buffering so you see it live)
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "TestPass123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -sN -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "Why did my take-home drop this month?", "payslip_data": {"month":"2026-07","basic":50000,"hra":20000,"tds":8000}, "session_history": []}'
```

### 3. Playwright browser driver — the real UI

```bash
export PATH="/c/Program Files/nodejs:$PATH"
cd .claude/skills/run-paynexus
node driver.mjs
```

Requires both dev servers already running (this drives the browser, it doesn't launch the app).
Registers a fresh test user each run — no state to reset between runs. Screenshots land in
`.claude/skills/run-paynexus/shots/` (`01-landing.png` → `04-final-response.png`, or `99-error-state.png`
on failure). Prints `PASS`/`FAIL` based on whether any browser console errors were seen, plus the raw
error text if so. Override the target with `FRONTEND_URL=... node driver.mjs`.

The flow it drives: register → switch off the checked-in default (login) mode → enter a payslip →
ask a question → wait for the response to actually finish (not for the agent indicator — see Gotchas).

## Run (human path)

Open `http://localhost:5173` after starting both servers per "Build" above. Useless for an agent —
opens a real browser window — but that's the manual-testing path.

## Gotchas

- **`uvicorn --reload` silently fails to pick up changes on this Windows setup.** Hit this directly:
  edited `orchestrator.py`, saw `WatchFiles detected changes... Reloading...` in the log, but the fix
  visibly wasn't applied on the next request. Killed the server and started a fresh process (no
  `--reload`) and the same edit worked immediately. If a code change doesn't seem to take effect,
  don't debug the change — restart the server fresh first and retest.
- **The agent indicator (`text=/reasoning/`) often won't be caught by a `waitForSelector`.** Agent 1
  alone can stream back in well under a second, faster than a polling wait can land mid-flight. Don't
  treat a miss here as failure — `driver.mjs` logs it but waits on the "Ask" button re-enabling (tied to
  `sending` state in `ChatInterface.tsx`) as the real completion signal instead.
- **React controlled inputs need Playwright's `fill()`, not `element.value = ...` via `page.evaluate`.**
  The latter doesn't fire React's `onChange`, so the app's state never updates even though the DOM looks
  filled.
- **Payslip Reasoning Agent (Agent 1) returns structured JSON**
  (`{"explanation": ..., "component_breakdown": ..., "follow_up_suggestions": [...]}`), not plain text.
  `agents/orchestrator.py`'s `assembler_node` formats this into prose before it reaches the frontend —
  if you ever see a raw `{"explanation":...}` blob in the chat UI, that formatting step broke (it did,
  once, during initial build — see git history on `_format_agent_response`).
- **`passlib` is incompatible with `bcrypt>=4.1`** and will crash every register/login with
  `ValueError: password cannot be longer than 72 bytes` — not a real password-length issue, it's
  `passlib`'s internal backend self-test failing on init. `security/auth.py` calls `bcrypt` directly for
  exactly this reason; don't reintroduce `passlib`.
- **Regulatory Agent (Agent 2) needs the pgvector index built first** —
  `python -m rag.build_index` from `backend/` — or it queries an empty/nonexistent collection.
- **`alembic revision --autogenerate` will try to DROP pgvector's own tables**
  (`langchain_pg_collection`, `langchain_pg_embedding`) if you ever remove or weaken
  `alembic/env.py`'s `include_object` filter — they're live in the same database but aren't part of
  this app's SQLAlchemy models, so autogenerate sees them as "should be removed." Applying that
  migration deletes the RAG index. The filter exists specifically to stop this; don't autogenerate
  with it commented out "just to see the diff."
- **A password (or anything routed through `DATABASE_URL`) containing a literal `%` breaks Alembic**
  if the URL ever goes through `config.set_main_option()`/`get_main_option()` — Python's `configparser`
  treats `%` as its own interpolation syntax and raises `ValueError: invalid interpolation syntax`.
  `alembic/env.py` builds the engine directly from `app_config.DATABASE_URL` instead, bypassing
  configparser entirely, for exactly this reason. Hit this for real with a URL-encoded `%24` in a DB
  password.
- **After running `Base.metadata.drop_all()` (e.g. to regenerate a clean Alembic autogenerate diff),
  every previously-registered test user is gone.** Obvious in hindsight, easy to forget mid-task — the
  next `curl`/driver run needs `/auth/register` again, not `/auth/login`, or you'll chase a confusing
  "Invalid or expired token" that's actually just "that user doesn't exist anymore."

## Troubleshooting

- **`node`/`npm` "command not found"** — PATH issue, not a missing install (check with
  `Test-Path "C:\Program Files\nodejs\node.exe"` in PowerShell first). Prepend PATH per Prerequisites.
- **`UnicodeEncodeError: 'charmap' codec can't encode character '\u20b9'`** — forgot
  `PYTHONIOENCODING=utf-8`. The ₹ symbol crashes Windows' default console codepage.
- **`/chat` or any DB-touching endpoint 500s** — check `DATABASE_URL` in `backend/.env` is real (not
  the `.env.example` placeholder) and the `vector` extension is enabled on that database.
- **Playwright `chromium.launch()` hangs or errors "executable doesn't exist"** — browser binary not
  downloaded: `npx playwright install chromium` from this skill directory.
- **Port 8000 already in use on restart** — a previous `uvicorn` didn't die cleanly. Find and stop it:
  `Get-NetTCPConnection -LocalPort 8000 | Select -Expand OwningProcess | Stop-Process -Force` (PowerShell).
