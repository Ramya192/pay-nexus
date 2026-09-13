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
19. Nudge card — `components/NudgeCard/NudgeCard.tsx`, wired into `AgentMessage` (see "Financial profile" below for the fuller story)

Also added: `store/{authStore,chatStore,payslipStore,sessionHistoryStore}.ts` (Zustand, replacing the
doc's original Context+`useReducer` plan per the earlier stack update) and `api/{client,auth,chat,payslip}.ts`.

Frontend is now verified end-to-end via Playwright (see "Pending issues resolved" below for the session
that installed Node.js + Playwright and did this) — register → payslip → chat → agent indicator → answer,
zero console errors, confirmed by screenshot.

Remaining frontend gaps:
- **PayslipDashboard/BreakdownChart isn't built.** `recharts` is in `package.json` but nothing uses it yet.
- Auth state (JWT + derived AES key) lives in memory only, not persisted — refreshing the page logs you out.
  Deliberate for now (the alternative is the key sitting in `localStorage`), flagging it as a product decision
  to revisit, not an oversight.
- `esbuild`/Vite dev-server CORS vulnerability (`npm audit` — moderate, dev-only, fix needs a breaking
  Vite 5→8 upgrade not yet attempted).

**Phase 6 (Deployment) — in progress.** Local git repo initialized, GitHub repo created
(`github.com/Ramya192/pay-nexus`), not yet pushed. Azure App Service / Static Web Apps not yet provisioned.

## PDFParser (Aug 2026)

Client-side PDF→JSON payslip extraction, filling the one Phase 5 gap that was still open:
`components/PayslipUploader/PDFParser.tsx` extracts text from an uploaded PDF entirely in the browser
(`pdfjs-dist`) — the PDF file itself never reaches the server, only the extracted text does, via
`POST /payslip/parse` (`backend/payslip_extraction.py`, GPT-4o-mini, `response_format=json_object`).
Upload and manual entry are two paths into the *same* `ManualEntryForm`, not separate flows — extraction
only pre-fills the form (`PayslipUploader.tsx`'s key-remount pattern), every field stays editable, and
anything the model isn't confident about is left blank rather than guessed. Verified against a synthetic
test payslip (generated via Playwright's HTML→PDF): every real figure extracted correctly, and the two
fields deliberately *not* on the test payslip (PF employer contribution, rent paid) were correctly left
blank rather than fabricated — confirmed via a full browser pass, not just the API in isolation.

## Financial profile — investments, loans, insurance (Aug 2026)

The Nudge Agent's 80C/80D/24(b) gap analysis used to be inferred from TDS trends alone. Now there's a
proper encrypted "Financial Profile" (ELSS/other mutual funds, stocks, FDs, RDs, home loan
principal+interest, life and health insurance premiums — personal loan EMIs deliberately excluded, since
they're usually not tax-deductible, unlike home loan interest) that feeds real numbers into both the
Nudge and Payslip agents.

**The key design decision**: exact deduction-gap arithmetic (80C ₹1.5L cap, 80D ₹25k/₹50k, 24(b) ₹2L) is
computed in Python (`backend/tax_calculations.py`), not left to the LLM — a direct response to the earlier
session's finding that a smaller model got 80C subtraction wrong. The agents now quote pre-solved figures
rather than deriving them; `agents/nudge_agent.py`'s system prompt explicitly says "these are already
correct, quote them, don't recompute." Verified hand-checkable: ₹40k ELSS + ₹15k life insurance + ₹30k
home loan principal + ₹72k annualized PF = ₹157k raw, correctly capped at the ₹1.5L limit → ₹0 remaining;
₹18k of ₹25k 80D limit → ₹7k remaining; ₹180k of ₹2L 24(b) limit → ₹20k remaining. All three matched
exactly in a live `/chat` response.

Data model: `FinancialProfile` is one **upserted** row per user (`PUT /financial-profile`), not a growing
log like `PayslipSnapshot` — a mutual fund portfolio doesn't reset every month the way a payslip does.
Same ciphertext-only contract as everything else (`GET`/`PUT /financial-profile`,
`backend/api/routes/financial_profile.py`). `AuthScreen.tsx` fetches + decrypts it on login (404 = no
profile yet, handled as the normal case, not an error) and `ChatInterface.tsx` sends it plaintext with
every `/chat` call, same trust tier as `payslip_data`.

Two real bugs found building this, both fixed:
- **`vite.config.ts`'s dev proxy never had `/financial-profile` added** — requests silently hit Vite's own
  dev server instead of the backend, and Vite's SPA fallback served `index.html` back as if it were a
  successful 200 response, which then failed downstream trying to `atob()`-decode HTML as base64
  ciphertext. Classic "worked in curl, broke in the browser" bug — curl never goes through the Vite proxy,
  so this was invisible until an actual browser test caught it.
- **The intent classifier didn't route "how much more can I invest to save tax this year?" to the Nudge
  Agent at all** — it went to Payslip + Regulatory instead, missing the new deduction-gap answer entirely
  despite that being close to the canonical question this feature exists to answer. Fixed by naming
  deduction-gap questions explicitly in `orchestrator.py`'s `_INTENT_SYSTEM_PROMPT`, with a worked example
  distinguishing it from "regulatory" (about *this user's* remaining room, not the general rule).

Also renamed the Nudge Agent's **display name** to "Savings Advisor" (UI copy only — internal code, file,
and variable names are all still `nudge_agent`) since "Nudge Agent" read as unclear/jargony in the actual
chat UI.

## Payslip history & month-over-month trends (Aug 2026)

Bulk upload of *past* payslips, distinct from the single current-payslip flow: `PayslipHistoryUpload.tsx`
accepts multiple PDFs at once, and — unlike the reviewed, editable current-payslip path — each one is
extracted and saved straight to encrypted storage with **no manual review step**, since archived history
isn't driving today's chat answer the way the active payslip is. `extractPdfText` (the PDF→text logic) was
factored out of `PDFParser.tsx` into `utils/pdfText.ts` so both upload paths share one implementation.

Same "compute exactly in Python" principle as `tax_calculations.py`, applied to trends this time:
`backend/payslip_trends.py` compares first-vs-last snapshot for gradual fields (basic, TDS, HRA) and
handles Bonus separately as a total-plus-per-month list rather than a first-vs-last comparison — caught by
testing against fabricated data with a real mid-period bonus that first-vs-last was hiding entirely (two
zero-bonus months on either end made a real ₹10,000 June bonus read as "flat, no bonus paid"). Verified
end-to-end with 4 synthetic payslips (₹5,000 → ₹8,000 TDS, April → July): the Savings Advisor's answer
quoted the exact trend line verbatim and correctly referenced the bonus as a contributing factor.

Also closed a **pre-existing gap that predates this feature**: `api/payslip.ts`'s `savePayslip` function
existed since Phase 5 but nothing in the UI ever called it — the "Use this payslip" button's own copy
promised a separate save step ("kept in this session only until you choose to save it") that was never
actually built. `ManualEntryForm.tsx` now has a real "Save to history" button alongside "Use this payslip."

Two more real bugs, both fixed the same way as the Financial Profile ones — write it, test it in an actual
browser, not just `curl`:
- Same Vite-proxy class of bug as `/financial-profile`, this time it *didn't* need a fix — `/payslip/snapshots`
  already matched the existing `/payslip` proxy prefix. Worth the reminder anyway: any new top-level route
  needs an explicit proxy entry unless it happens to nest under one that already exists.
- **The intent classifier again routed a canonical question to the wrong agent** — "Do you see any
  concerning trends in my payslips?" went to the single-payslip agent (which doesn't even receive
  `payslip_history`) purely because the word "payslips" appeared in it. Fixed by rewriting
  `_INTENT_SYSTEM_PROMPT` to classify on whether a question is about the one active payslip vs. a pattern
  across several, explicitly calling out that "trend," "increasing," "compare," "over time" all mean nudge
  regardless of whether the word "payslip" also appears — the same failure shape as the earlier 80C-question
  misroute, now hit and fixed twice.

## Live conversation context (Aug 2026, user-reported)

Reported directly from manual testing: asking "can you recommend tax regime" (no active payslip, only
saved history) got "no payslip attached," and the follow-up "can you consider the payslips attached in
payslip history tab" lost the topic entirely and came back as an unrelated generic nudge card. Two
compounding root causes, both fixed:

1. **`payslip_agent.py` never looked at `payslip_history` at all** — only `payslip_data` (the
   session-active payslip). Now falls back to the most recent saved snapshot when nothing is active,
   clearly labeled as such in the response ("Based on your most recently saved payslip, July 2026...").
   Extended further per a follow-up decision: when more than one month is on file, the agent also gets the
   same exact basic/TDS/HRA trend figures `payslip_trends.py` already computes for the Savings Advisor
   (reused, not recomputed) — enough for genuine multi-month regime *reasoning* ("your basic rose ₹2,000 and
   TDS rose ₹3,000 since April, so..."), deliberately **not** extended to computing an actual old-vs-new
   *tax liability* figure, since that needs the full Indian income tax slab table (rates, cess, the 87A
   rebate) which isn't implemented anywhere in this codebase — the prompt explicitly tells the model to say
   so rather than improvise a number.

2. **There was no live conversation memory within a session at all.** Every question was sent to the
   backend in total isolation — a follow-up carried zero memory of what was just asked. This was actually a
   latent gap from the original Phase 3 design: §6's "Level 1 in-session sliding window" was always meant
   for live conversation turns, but `orchestrator.py` had it wired to `session_history` (the cross-session
   *summaries*) instead, and the frontend never sent live turns to begin with. Fixed properly: a new
   `conversation` field (`agents/conversation.py`, `ChatRequest.conversation`, `PayNexusState.conversation`)
   carries this session's own `{query, response}` exchanges, `ChatInterface.tsx` sends the last few with
   every `/chat` call (captured *before* the current turn's own placeholder messages are added, via a new
   shared `buildExchanges()` helper also used by the logout summarization flow), and `orchestrator.py`'s
   intent classifier now sees recent conversation and is explicitly instructed to resolve short follow-ups
   ("consider the payslip history," "what about that") against it instead of classifying them as fresh,
   unrelated requests.

Verified together: the same "recommend tax regime" → "consider payslip history" sequence now stays on
topic throughout, quotes exact trend figures verbatim, and correctly declines to fabricate a tax liability
number rather than guessing one.

## Savings Advisor couldn't answer "what have I entered" (Aug 2026, user-reported)

Reported directly from manual testing: a financial profile was filled in and saved (life insurance
₹35,853, health insurance ₹80,000, senior citizen box checked), confirmed to correctly pre-fill on the
*next* login — proving the save → fetch → decrypt → pre-fill pipeline was already working end to end — but
asking the Savings Advisor "can you tell me my savings that I have entered?" in that next-login session got
back "No specific savings data available."

Root cause: `nudge_agent.py` only ever passed the *aggregated* 80C/80D/24(b) gap totals to the LLM (e.g.
"80C: ₹85,853 used of ₹1,50,000") — never the raw individual declared field values those totals were built
from. A section-level rollup like that can't answer "what did I enter," since it deliberately loses which
part came from life insurance vs. ELSS vs. home loan principal.

Fixed with a new `format_financial_profile_for_prompt()` in `tax_calculations.py` that renders each
declared field as its own labeled line (e.g. "Life insurance premium: ₹35,853"), included in the Savings
Advisor's prompt ahead of the computed gap totals — both are given together now, not one instead of the
other. Also tightened `nudge_agent.py`'s system prompt: when the question is literally "what have I
entered/declared/saved," the agent is now instructed to recite those raw figures directly first, before any
gap analysis or recommendation — the first pass of this fix left the aggregated-gap framing in place, and
while it correctly stopped saying "no data available," it still answered a literal "what did I enter"
question with a savings-limit recommendation instead of just reading the numbers back.

Verified with the user's exact reported sequence via Playwright (save → log out → log back in → ask,
without touching the form): the form still pre-fills correctly on re-login (unaffected — confirms this was
never a persistence bug), and the Savings Advisor now responds "You have entered the following savings:
Life insurance premium: ₹35,853, Health insurance premium: ₹80,000."

## Duplicate payslips and a chat request the system couldn't act on (Aug 2026, user-reported)

Reported directly from manual testing, two compounding problems from the same screenshot:

1. Bulk-uploading 12 payslip PDFs twice produced 24 saved snapshots with no warning — nothing detected
   that the same month had already been saved.
2. Asking chat "can you check and remove if there are any duplicates" got back the Savings Advisor's
   generic "Your Declared Investments Summary" card — unrelated to the question asked.

Root causes, and what changed:

1. **No duplicate detection at save time.** `POST /payslip/save` never checked whether a payslip for that
   (user, month) already existed — it just inserted another row. Fixed: the endpoint now checks by `month`
   (the one payslip field the server ever sees in plaintext, §4 — no need to look at the encrypted figures
   to catch this) and returns 409 if that month is already saved. `ManualEntryForm.tsx` shows this as an
   amber "Already saved" state, not a red error; `PayslipHistoryUpload.tsx`'s bulk loop shows each duplicate
   file as "already saved — skipped" and continues with the rest of the batch rather than treating it as a
   failure.

2. **No agent can write to storage, and nothing told the user that.** None of the three reasoning agents
   (Payslip/Regulatory/Nudge) have — or should have — the ability to delete saved data from a chat message;
   giving an LLM that kind of write access from a free-text request isn't something this app does. But
   previously, a request like "remove duplicates" just fell through the intent classifier into whichever
   agent sounded closest by keyword and produced an unrelated answer, with no signal that the request
   itself was out of scope. Fixed with a fourth orchestrator path: `capability_gap_node`
   (`agents/orchestrator.py`) — a plain, non-LLM response (nothing here needs a model call; what's possible
   is already fixed and known) that says plainly what chat can't do and points at where it actually can be
   done, and a new intent-classifier category ("unsupported") that routes to it. Also built the "where it
   actually can be done": `PayslipHistoryList.tsx`, a new panel in the Payslip history section listing every
   saved month with its own delete button, plus a "Remove duplicates" button that keeps the most recently
   saved entry per month and deletes the rest (`DELETE /payslip/snapshots/{id}`, new). Deleting stays an
   explicit, confirmed UI click — never something an agent decides to do on its own.

   First pass at the classifier prompt overcorrected: plain questions that merely *mentioned* saved data —
   "do you have my payslip history?", "can you tell me my savings that I have entered?" — started getting
   misclassified as "unsupported" too, purely from sharing vocabulary with the delete examples, breaking
   the very question-answering this session had just fixed. Caught by re-testing the classifier in isolation
   against a wider set of phrasings before trusting it, not just the one case that prompted the change.
   Fixed by rewriting the category as a strict test (an explicit instruction verb — delete/remove/clear/
   edit — targeting stored data, never just topic overlap) with contrastive worked examples for exactly the
   phrasings that had failed.

Verified with Playwright end to end: manually saving the same month twice is blocked with "already saved";
bulk-uploading the same two files twice saves each real month once and skips the repeats; a legacy-style
duplicate row seeded directly into the database (simulating the pre-fix 24-row mess) is correctly flagged
with a duplicate count and removed via "Remove duplicates," keeping the newer entry; "do you have my
payslip history?" still gets a real answer from the Savings Advisor; and "can you check and remove if there
are any duplicates" now gets an honest "I can't do that from chat — here's where you can" instead of an
unrelated card.

## "Verify if there are any duplicates" answered with unrelated investment data (Aug 2026, user-reported)

Reported directly from manual testing, right after the fix above: asking "do you have my payslip
history?" correctly listed 24 snapshots, but the follow-up "can you verify if there are any duplicates in
payslip history" got back "Investment Details Recalled" — life insurance and health insurance premiums,
Section 80C gap — nothing to do with duplicates.

This one **was** routed correctly — "can you verify... duplicates" is a question, not an instruction to
change anything, so the classifier (rightly, per the fix above) sent it to the Nudge agent rather than the
capability-gap path. The bug was downstream: `nudge_agent.py` had no computed fact about duplicate months
to answer from at all. Nothing in its prompt ever mentioned duplicates, so the model filled the gap by
pattern-matching to whatever nearby topic it had actual data for — the financial profile — and answered
that instead.

Fixed the same way trends and deduction gaps already work here: exact computation in Python, handed to the
agent pre-solved. Added `detect_duplicate_months()` / `format_duplicates_for_prompt()` to
`payslip_trends.py` — groups saved snapshots by month, returns which months have more than one — included
in the Nudge agent's prompt alongside the trends block whenever payslip history is on file (not only when
the question happens to mention "duplicate," which is exactly how this went missing in the first place).
System prompt updated to answer duplicate questions from that section specifically, and to point at the
"Remove duplicates" button rather than offer to act on it.

Verified with Playwright, reproducing the user's exact two-question sequence against a payslip history with
a seeded duplicate: "do you have my payslip history?" now names the duplicate month directly in its answer,
and "can you verify if there are any duplicates in payslip history" responds "1 month with more than one
saved snapshot — 2026-04 has 2 copies" and points to the Payslip history panel — no investment/insurance
figures in either response.

## Inconsistent deduction totals, a fabricated savings figure, and lengthy prose (Aug 2026, user-reported)

Reported directly from manual testing via a two-turn conversation: "can you recommend the tax regime?"
stated total old-regime deductions of ₹146,333; the very next turn, "can you consider my insurance
savings?", stated ₹114,147 *remaining* under the same Section 80C — two different totals for the same
declared data in the same conversation. Separately, a Savings Advisor card claimed "≈ ₹20,000 saved
annually" from an unused Section 24(b) deduction, and one Payslip agent response slipped into third-person
("assuming **her** tax slab") mid-answer. The user also asked, separately, for calculations to be shown in
a table rather than dense paragraphs.

Four issues, three of them real correctness bugs, not just a formatting complaint:

1. **Inconsistent deduction totals.** `payslip_agent.py` falls back to the most recently saved payslip
   when no payslip is active this session (see the "Live conversation context" fix above) — but that
   fallback was only applied inside `payslip_agent.py`, not `nudge_agent.py`. Both agents call
   `tax_calculations.compute_all_gaps()`, which factors in the payslip's employee PF contribution
   (annualized) for the Section 80C total — so with no session-active payslip, `payslip_agent` computed 80C
   using the saved payslip's PF (₹146,337) while `nudge_agent` computed it from an empty payslip (₹35,853,
   life insurance only) — two different, both "already computed — quote directly" figures for the same
   question, depending on which agent happened to answer. Fixed by extracting the fallback into
   `payslip_trends.resolve_effective_payslip()`, shared by both agents — there is now exactly one place
   that decides which payslip is "current" for a session.

2. **A fabricated tax-savings figure.** The Savings Advisor's "impact" field (e.g. "≈ ₹20,000 saved
   annually") requires knowing the user's marginal tax rate to compute — this system has no income tax
   slab table anywhere, the same limitation already documented for the Payslip agent's regime comparisons.
   Nothing stopped the model from just guessing a plausible-sounding rate anyway when asked to fill the
   field. Fixed by explicitly forbidding a "tax saved" estimate in the prompt — for a deduction-gap
   suggestion, "impact" now states the deduction room available instead (already computed, not guessed).

3. **A third-person slip.** Minor and not deterministically fixable (an LLM phrasing quirk, not a logic
   bug), but added an explicit "address the user in second person, never third person" instruction to the
   Payslip agent's prompt as a mitigation.

4. **Lengthy prose for numeric answers**, the user's direct request. Rather than asking the model to
   format better (unreliable — it's still choosing what numbers to state and could still get one wrong),
   built real tables in Python from the exact same computed data already used for the prose sections
   (`tax_calculations.py`'s `gaps_table()`/`financial_profile_table()`, `payslip_trends.py`'s
   `trends_table()`/`duplicates_table()`, a new `payslip_agent.py`-local `_components_table()` for the raw
   payslip breakdown itself). Each agent picks which precomputed table(s) are relevant to the question
   (a topic-relevance judgment, not a numeric one — a `"tables": ["gaps"]` key it fills, resolved back to
   the real dict by the new shared `agents/tables.py`) and the "detail"/"explanation" prose is now
   instructed to stay to a sentence or two of interpretation, not a restatement of every figure. The
   frontend renders these as actual `<table>` elements (`DataTable.tsx`) below the chat bubble — this also
   fixes a smaller, previously-unnoticed issue where the Payslip agent's `component_breakdown` field was
   being collected in every response and silently discarded by the assembler, never shown anywhere.

Verified together: reproduced the exact reported scenario (financial profile + one saved payslip with PF
set) and confirmed via Playwright that both agents now state the identical ₹3,663 Section 80C remaining
figure, rendered as an actual table; no "saved annually" language appears anywhere; and no third-person
slip in either agent's response for this run.

## Real tax liability calculator (Aug 2026, user-requested)

Every prior session had the Payslip agent explicitly refuse an actual ₹ tax liability figure —
"a precise figure needs the full slab calculation, which isn't available here" — because nothing in the
codebase computed one. A user asked "how much tax do I have to pay? have we applied these savings while
calculating tax?", got that refusal, and then asked what it actually meant. That prompted building the
calculator instead of continuing to explain the gap.

New `tax_slabs.py`: exact old-vs-new regime tax computation — progressive slab bands, the 4% health &
education cess, the Section 87A rebate, and marginal relief for income just above the rebate threshold (so
a rupee over the ₹12L/₹5L cliff doesn't suddenly owe far more than that rupee) — currently pinned to
**FY 2025-26 (AY 2026-27), per Union Budget 2025**. Two caveats travel with every result, disclosed in
plain language in the response, not just logged:

1. **Slab rates have a shelf life.** They change with every Union Budget (typically each February) and
   nothing here checks for a newer one — this table needs a manual update whenever that happens.
2. **The annual income feeding it is usually an estimate.** A new `estimate_annual_gross_income()` prefers
   summing real gross pay across saved history (6+ months → scaled to a year; 12+ months → an actual annual
   total, not extrapolated) over the fallback of multiplying one month's payslip by 12, which is what
   happens with only one payslip on file — and says plainly which method was used.

Wired into `payslip_agent.py` as another table it can offer via the same table-selection mechanism from the
formatting fix above (`agents/tables.py`) — computed whenever a payslip is on file, offered as the
`"liability"` key, selected by the model when the question actually wants a real number ("how much tax do I
owe," a regime comparison). Caught one bug before shipping: the first version only put the *estimation
method* in the model's prompt, never the actual computed totals — with no number in its own context to
reason from, it reasonably answered "no tax liability estimate was provided" despite the table existing.
Fixed by giving it the real old/new regime totals as an explicit "already computed — quote directly" line,
the same pattern the deduction-gaps figures already used.

Hand-verified against manually computed slab math for two cases (₹6L income/no deductions, ₹15L
income/₹2L deductions) before wiring in, then verified via Playwright reproducing the user's actual
question: the response now states a real ₹61,104 (old regime) vs. ₹0 (new regime) figure for the test
scenario, names the FY basis, and states the income-estimation caveat — no more blanket refusal.

## Two agents contradicting each other's regime recommendation (Aug 2026, user-reported)

Reported directly from manual testing, immediately after the tax liability calculator above: asking
"can you recommend a tax regime based on my payslip history" produced the Payslip agent correctly
recommending the **new** regime (₹0 tax vs. ₹65,888) using the real computed liability numbers, while the
Savings Advisor's card in the very same response recommended the **old** regime — "may provide better
savings due to significant available deductions... remaining limits under Section 80C and 24(b)." Two
agents, one response, opposite conclusions.

Root cause: the tax liability calculator (previous fix) was only wired into `payslip_agent.py`.
`nudge_agent.py` — which also runs for a "recommend a regime" question, since that's an intentional
multi-agent case — had no access to it and fell back to its old heuristic: recommending old-regime based on
declared deductions' *remaining room*. That heuristic is actually backwards — unused deduction capacity
("you still have ₹53,667 left in 80C") isn't evidence the old regime is winning, it's the opposite,
capacity not yet used — but more importantly, it's an opinion formed without ever looking at the real ₹
comparison the other agent had.

Fixed by wiring the same `tax_slabs.py` computation (same inputs — `resolve_effective_payslip`'s payslip,
same `total_deductions`) into `nudge_agent.py` too, and adding an explicit instruction: when a "Tax
liability estimate" figure is available, the regime recommendation **must match it** — whichever regime has
the lower real total tax, full stop — rather than an independently-formed opinion from deduction-gap
headroom. The two agents can't disagree anymore because they're now looking at the identical computed
numbers, not just similarly-labeled ones.

Verified via Playwright reproducing the exact scenario (12 months of payslip history, senior-citizen health
insurance, life insurance declared): both agents now state ₹61,104 (old) vs. ₹0 (new) and both recommend
switching to the new regime — including on the user's own skeptical follow-up ("in new regime tax payable
is 0, but why you are recommending old regime?"), which now gets a consistent, correct clarification instead
of the contradiction persisting.

## RAG made visible, evaluated, and the corpus finished (Aug 2026, user-asked)

A user asked two direct questions: "where can I see the actual RAG implementation while testing?" and
"are we implementing evaluation metrics for RAG?" Honest answers at the time: nowhere (retrieved chunks
only ever existed inside the LLM's prompt, never returned to the frontend or logged), and no (nothing
measured retrieval or generation quality — confirmed by checking for the usual signals: RAGAS, precision/
recall, faithfulness scoring, a ground-truth eval set — none existed). Three pieces of work followed.

**1. Retrieval surfaced in the chat UI.** `agents/regulatory_agent.py` now calls
`rag/retriever.py`'s new `retrieve_with_scores()` and returns a table of what was actually retrieved —
source document, distance score (cosine distance; lower = more similar, labeled as such so a "0.38" doesn't
read as "38% relevant"), and an excerpt preview — via `regulatory_tables`, unconditionally (not
LLM-selected like the Payslip/Nudge agents' tables, since retrieval happens on every regulatory question).
No new frontend code was needed — it flows through the same `tables` → SSE → `DataTable.tsx` mechanism
built for the earlier formatting fix.

**2. A real eval harness** (`rag/eval.py`, `rag/eval_dataset.py`, run via `python -m rag.eval`) — two kinds
of metric, deliberately kept separate:
- **Retrieval**: hit-rate@k and MRR, fully deterministic from retrieved-chunk metadata, no LLM involved.
- **Generation**: keyword/fact coverage — runs the actual `regulatory_agent_node` (the real production
  code path) and checks whether known facts appear in its answer. Deliberately not an LLM-graded
  "faithfulness score" — for a corpus this small and factual, "does ₹75,000 appear" is a good, cheap,
  exactly-reproducible proxy, and trades away nothing meaningful yet.

**The first baseline run caught a real bug immediately**, not after the fact: asked "what is the standard
deduction under the new tax regime," retrieval correctly surfaced the current-figure document at rank 1 —
but the model answered ₹50,000 (a stale, pre-Budget-2024 figure) instead of the ₹75,000 the retrieved
context actually contained, alongside a similar miss on the new regime's nil-tax threshold (₹7 lakh stated,
₹12 lakh current). Root cause: the corpus's `new_vs_old_tax_regime_faqs.md` is an AY2024-25-vintage FAQ
page whose Q5/Q8 figures have since been superseded by two later Budgets, and nothing told the model to
prefer the more recent document when two retrieved chunks disagreed — it picked the FAQ's cleaner,
more-quotable phrasing over the Budget doc's correct-but-narrative one. Fixed two ways: an editorial note
added directly to the stale document (the superseded figures plus the current ones, so the same retrieved
chunk is correct regardless of which one a future query happens to surface) and a new system-prompt
instruction to explicitly prefer the more recent Budget/Finance Act when retrieved excerpts conflict on a
figure, rather than silently picking one. Re-running the harness after the fix confirmed both cases now
pass with the correct current figures.

**3. The corpus finished — 4/10 planned topics to 10/10.** `incometaxindia.gov.in` and `indiacode.nic.in`
(the primary/official sources) still block automated fetching, confirming the blocker from earlier in this
project — but secondary sources (cleartax.in and others) are reachable and cross-check cleanly against this
app's own already-verified numbers (`tax_calculations.py`, `tax_slabs.py`). Authored the remaining six
documents from those sources with the same rigor as `tax_slabs.py`: `it_act_key_sections.md` (80C, 80D,
80CCD, 10(13A), 10(14), 192, 194), `budget_2024-25_highlights.txt`, `hra_exemption_rules.md` (with a worked
example), `standard_deduction_history.md` (a full timeline, explaining exactly why the corpus's own
new/old-regime split exists), `form_16_structure.md`, and `professional_tax_state_slabs.md` (Telangana,
Maharashtra, Karnataka, Tamil Nadu — flagged as state-set figures that move independently of the Union
Budget and are the most likely to go stale first). Every new document states it's compiled from secondary
sources, not verbatim statute text.

Extended the eval set with 7 new cases covering the new documents and reran against the completed 10-doc
corpus: 15/17 cases clean, hit-rate@5 94%, MRR 0.853, keyword coverage 94%. The 2 remaining "failures" are
both benign, not real defects, and reported as such rather than quietly worked around: one is the eval
harness's own ground truth being narrower than reality now that the corpus grew (a fact that used to have
one valid source now legitimately has two, since the editorial note above also states it, and retrieval
happened to surface the other one); the other is the same LLM phrasing non-determinism noted earlier in
this file (an answer that's still factually correct but didn't cite a specific section number that run).

## LLM call metrics, and a real compression cost-savings measurement (Aug 2026, user-asked)

A user asked how to actually test/show context compression's cost savings (Level 1/Level 2, §6) in a
demonstrable before-vs-after way, and separately whether Pydantic could structure LLM call metrics.
Checked first: `agents/llm.py`'s `hybrid_complete()` and every direct OpenAI call
(`payslip_agent.py`, the orchestrator's intent classifier, `context_compressor.py`'s Level 2 summary)
discarded `response.usage` entirely, and `PayNexusState.token_usage` was a field declared in the
TypedDict and never once populated or read — a dead stub, not a working feature. Nothing measured
LLM cost at all.

**New `agents/llm_metrics.py`** — a Pydantic `LLMCallMetrics` model (agent, model, input/output
tokens, cost, latency, timestamp) built straight from each OpenAI response's own `.usage` field
(exact counts, never estimated with a tokenizer) plus a dated USD-per-1M-token pricing table
(`PRICING_AS_OF`, same "needs periodic manual refresh" caveat as `tax_slabs.py`'s `FY_LABEL`).
`hybrid_complete()` now returns `(text, metrics)` instead of just `text`; every LLM call site
records its own metrics under its own state key (`payslip_llm_calls`, `regulatory_llm_calls`,
`nudge_llm_calls`, `orchestrator_llm_calls` — separate keys because LangGraph's parallel fan-out
would race on a single shared list), and the assembler aggregates all of them into `token_usage` —
the first time that field has ever actually held data. Surfaced two ways: every `/chat` SSE final
event now carries it, and the chat UI shows a small "N in · M out · $X.XXXXXX" line under each
response (hover for a per-agent breakdown) — real cost, visible per turn, not just in a log file.

**New `compression/eval.py`** — a harness answering "what does compression actually save," built on
top of the metrics above rather than re-estimating anything: Level 1 (in-session sliding window) and
Level 2 (cross-session summary) each get a before/after comparison against a fabricated but
realistic test profile (a 15-exchange conversation, 5 prior sessions), run through the real
`nudge_agent_node` production code path — never a reimplementation. Run via `python -m compression.eval`.

**The harness caught a real bug on its first run, not a clean pass**: Level 2 came back net
*negative* — compression cost more input tokens than sending the raw exchanges would have. Root
cause, confirmed by inspecting the actual compressed output: the Level 2 summarizer was embedding
the *full* `payslip_snapshot` object (month, basic, HRA, PF, TDS...) verbatim in every single
session's summary, and with `GET /payslip/history` returning every summary a user has ever had with
no limit, that snapshot was duplicated byte-for-byte across however many past sessions existed — an
inefficiency that gets *worse* the longer someone uses the app, the opposite of what compression is
for. Two fixes: the summary now carries only `payslip_month` (a cheap anchor, not the full
breakdown — the Payslip/Nudge agents already get the real figures through their own state fields,
never through `session_history`), and a new `cap_session_history()` keeps only the 10 most recent
summaries in play, the cross-session analogue of Level 1's sliding window, applied in
`orchestrator_node` alongside it.

Re-run after the fix: Level 1 saves ~18% of input tokens for the test conversation; Level 2 is now
genuinely positive (real $ savings per turn, with a computed break-even point for the one-time
summarization cost); a third comparison — one longer, more realistic session compressed on its own —
shows an ~89% size reduction, making the point that Level 2's advantage *grows* with how much a
session actually covers, which the short conservative test sessions alone undersold.

## "Use this payslip" gave no confirmation (Aug 2026, user-reported)

Reported directly from manual testing: "Save to history" gives clear feedback ("Saving…" →
"Saved to history ✓"), but "Use this payslip" — the button that actually sets what drives today's
chat answers — gave none at all. The user clicked it several times, unsure whether anything had
happened.

Fixed two ways, not just one, since a click-time confirmation alone only helps at the moment of the
click: `ManualEntryForm.tsx` now tracks its own `useStatus` (mirroring `saveStatus`'s existing
pattern) so the button itself reads "Using this payslip ✓" right after submit, resetting to idle on
any further field edit — a stale checkmark next to edited-but-not-resubmitted fields would be
actively misleading. Separately, a new `ActivePayslipBanner.tsx` sits at the top of the sidebar,
reactively reading `payslipStore`, so "is a payslip actually active this session, and which one" is
always visible — not just for a moment after clicking, and not lost if you scroll past the form.

Verified via Playwright: before using any payslip, the banner reads "No payslip active this
session"; after submitting, both the button and the banner confirm it (banner names the month);
editing a field afterward reverts the button (form no longer matches what's active) while the
banner correctly keeps showing the payslip that's still actually driving chat, since editing a
field alone doesn't change the store until re-submitted.

## Regime recommendation contradiction, again — this time despite correct shared numbers (Aug 2026, user-reported)

Reported directly from manual testing: asking "so my tax regime should be old or new?" got the Payslip
agent correctly recommending the **new** regime (₹0 vs ₹92,304), while the Savings Advisor's card in the
same response said "Choose Old Regime for Savings" — and its own sentence was internally
self-contradictory: *"With the old regime total tax at ₹92,304 compared to the new regime's zero tax
liability, switching to the new regime does not provide any financial benefit"* — stating both correct
figures, then drawing the opposite conclusion from what they say.

This is the same class of bug fixed earlier in this file ("Two agents contradicting each other's regime
recommendation"), recurring in a strictly worse form: that fix synced the two agents' *numbers* (both
compute from `tax_slabs.py`, both got ₹92,304/₹0 right here — confirmed by hand). What it didn't cover was
the *comparison step* — "which of these two numbers is smaller" was still left for the LLM to reason
about in prose, and evidently having the correct numbers in front of it wasn't a strong enough guardrail
on its own to stop that comparison from occasionally inverting.

Fixed by extending the same "compute exactly, never let the LLM derive it" rule this codebase already
applies to every other figure to cover the comparison judgment too, not just its inputs: new
`tax_slabs.cheaper_regime_statement()` computes the conclusion itself ("The NEW regime is cheaper: ₹X vs
₹Y — recommend the new regime") and both agents are now instructed to quote that line directly rather
than compare the two totals themselves, even though they technically could. Unit-tested all three
branches (new cheaper, old cheaper, a tie) directly before wiring in.

Verified via Playwright reproducing the user's exact question sequence and payslip profile: both agents
now state the identical conclusion, and the Savings Advisor's card quotes the pre-computed sentence
almost verbatim rather than re-deriving one of its own.

## Token-usage line was visible to every account, not just for testing (Aug 2026, user-reported)

Reported directly from manual testing: the "N in · M out · $X.XXXXXX" line under each chat response —
built specifically so LLM cost could be seen while testing (the compression cost-savings work above) —
was rendering unconditionally for every account, with nothing distinguishing local testing from what a
real deployed user would see. A real end user asking about their HRA exemption has no use for a raw API
cost figure; this was a debugging tool that had leaked into being an always-on feature by omission, not
by design.

Fixed by gating `AgentMessage.tsx`'s `TokenUsageLine` behind Vite's built-in `import.meta.env.DEV` —
true under `npm run dev`, `false` in a production build. Confirmed this isn't just a runtime `if` a
curious user could still find evidence of: ran `npm run build` and grepped the output bundle for the
component's distinctive strings — completely absent, dead-code-eliminated rather than merely hidden.
The backend still always computes and returns `token_usage` in every `/chat` response regardless — left
alone deliberately, since that's harmless AI-system metadata (not user data) with real future value for
logging/ops/billing tooling; only what's *displayed* to a real end user needed gating.

## Same table rendered twice on a multi-agent question (Aug 2026, user-reported)

Reported directly from manual testing: logging in and immediately asking "can you recommend the tax
regime?" (a multi-agent question — both Payslip agent and Savings Advisor run) showed the identical "Tax
liability estimate" table twice, back to back, in the same response.

Root cause: `payslip_agent.py` and `nudge_agent.py` each independently compute their own copy of the
"gaps" and "liability" tables (each needs its own copy to reason from in its own prompt) and each has its
own LLM call independently deciding whether to show it via the `agents/tables.py` selection mechanism —
so on a question that fans out to both, both can pick the same table, and `assembler_node` was simply
concatenating `payslip_tables + nudge_tables + regulatory_tables` with no de-duplication.

Fixed with content-based de-duplication in the assembler — keyed on each table's full serialized content
(title, headers, and rows), not just its title, so a genuine coincidental title match wouldn't wrongly
collapse two actually-different tables. General fix, not specific to the liability table: covers "gaps"
(which has the identical dual-computation risk) and any future case where two agents legitimately compute
the same data independently.

Verified by reproducing the user's exact scenario — fresh login, straight to a regime-recommendation
question with no prior conversation — via Playwright: exactly one "Tax liability estimate" table renders,
down from two.

## An over-hedging disclaimer, and a real conflation of taxable income with tax payable (Aug 2026, user-reported)

Reported directly from manual testing, two issues from the same conversation:

1. Asking "what is the definition of taxable income?" got a genuinely good, correct definition from the
   Regulatory agent — general knowledge, sensibly blended with what the retrieved excerpts did cover
   (Section 16(ia), 80C/80D mentions) — immediately followed by *"Since the details concerning 'taxable
   income' itself are not directly covered in the retrieved documents, you may want to consult the Income
   Tax Act... for a precise definition."* A correct, complete answer undercutting itself with a disclaimer
   that reads as "I don't actually know this."
2. Caught independently while reviewing the same screenshots, not something the user flagged directly: the
   turn just before that, asking (in context) "what is taxable income?" got the Payslip agent answering
   *"the new regime resulting in zero taxable income"* — factually wrong. Per the very table it was
   quoting, the new regime's taxable income was ₹10,87,900, not zero; the *tax* was zero (via the 87A
   rebate). The agent conflated two different rows of its own table.

**Issue 1** came from `regulatory_agent.py`'s system prompt applying its "don't guess at tax law" guardrail
too broadly — right for a Budget-dependent figure that could have changed, wrong for a stable, basic
definitional concept the model can state confidently regardless of which document happened to contain the
exact phrase. Fixed by splitting the instruction into the two cases explicitly: a specific figure/rule not
in the retrieved excerpts still gets the hedge (unchanged — this is the guardrail that's caught real stale-
data bugs earlier in this file); a basic stable concept gets a direct, confident answer, with an explicit
instruction not to close a correct answer with a "go consult elsewhere" disclaimer.

**Issue 2** traced back to an asymmetry in what the agent actually has to work with: the prompt gave it an
explicit, quotable **total tax** figure for each regime (`"Old regime total tax ≈ ₹X"`), but **taxable
income** only ever existed inside the `tax_liability_table()` structure — real data, but not restated as
text the model could cite directly. Asked specifically about taxable income, it had nothing exact to quote
and either hedged confusingly or, this time, conflated it with the number it did have (total tax). Fixed
the same way every other figure in this codebase already is: taxable income for both regimes is now also
given as an explicit prompt line, alongside gross income and total tax, with an instruction that these are
three distinct figures that can move independently (the new regime's taxable income being *higher* while
its tax is *lower* is real and correct, not a contradiction to paper over).

Verified by reproducing the user's exact three-turn conversation via Playwright: the definition question no
longer ends with the undercutting disclaimer, and "what is taxable income?" now states the correct, exact,
distinct figures for both regimes and correctly explains why higher taxable income can still mean lower tax.

## Literal "null" text rendered in a nudge card, and an under-caveated 24(b) suggestion (Aug 2026, user-reported)

Reported directly from manual testing, two issues from the same review pass:

1. Asking "can you consider my insurance savings?" (with 80C and 80D both already fully used) rendered
   the literal word **"null"** as its own line in the Savings Advisor card.
2. A separate suggestion to use remaining Section 24(b) room ("You have ₹2,00,000 remaining under Section
   24(b)... Utilizing this could further reduce your taxable income") didn't caveat that 24(b) only applies
   to actual home loan interest — unlike Section 80C, it's not something you can just go invest into.

**Issue 1** — `NudgeCard.tsx` renders the impact line with `{nudge.impact && <p>...}`, which correctly
hides a real `null`. The bug was upstream: the prompt asks the model for the JSON literal `null` when
there's no impact figure, but a JSON-mode model can instead emit the *string* `"null"` — valid JSON, wrong
value — which is truthy and renders literally. Fixed in `orchestrator.py`'s `_parse_nudge()` with a
`_normalize_impact()` step that collapses `"null"`/`"none"`/`"n/a"`/an empty string (case-insensitive) back
to a real `None`, rather than patching the same check into the frontend a second time. Verified directly
against three cases (the string `"null"`, a real impact string, and actual JSON `null`) before confirming
in the browser that the line disappears entirely rather than showing empty or literal text.

**Issue 2** — a wording gap, not a numeric error (the ₹2,00,000 remaining figure was correct). Added an
explicit instruction to `nudge_agent.py`'s system prompt: unlike 80C/80D, Section 24(b) only applies to
interest actually paid on an existing home loan, so any suggestion using remaining 24(b) room must be
framed conditionally ("if you have a home loan...") rather than presented as a generic actionable
opportunity.

Verified both via Playwright: the insurance-savings card no longer shows any "null" text, and a fresh
24(b) suggestion now reads "...that you could use **if you have a home loan**."

## Code + functionality review and dead-code cleanup (Aug 2026, user-requested)

A user asked for a code review, functionality review, and removal of stale/unused code. Ran actual tooling
rather than eyeballing: installed `ruff` (F401/F811/F841/F821 — unused imports, redefinitions, unused
vars, undefined names) and `vulture` (dead functions/classes) for the backend, `tsc --noEmit` and
`npm run build` for the frontend. All clean — no unused imports, no orphaned components, bundle size
unchanged after removing the one genuinely dead dependency found (confirming it was never bundled at all).

Six pieces of dead code/stale docs removed, each confirmed zero-references first and verified with a full
backend restart + frontend rebuild + browser smoke test afterward:
- `recharts` — a frontend dependency, installed, never imported anywhere (`npm uninstall`, not just an
  edit, so the lockfile matches).
- `security/encryption.py`'s server-side Fernet helper (`encrypt_server_side`/`decrypt_server_side`) —
  self-acknowledged unused in its own docstring, zero callers.
- `ENABLE_PROMPT_CACHE`/`MAX_CONTEXT_TOKENS` config flags — declared, read from `.env`, never actually
  consulted by any code. Worse than plain dead code: looked like live, flippable settings.
- `.env.example` — existed, but at the repo root instead of `backend/` where the real `.env` lives, and
  was stale (still listed the two removed flags). Moved and updated.
- `requirements.txt` — a redundant standalone `cryptography` pin (already covered by
  `python-jose[cryptography]`'s extra) and a duplicate `pydantic` line.
- `.claude/skills/run-paynexus/SKILL.md` — one factually wrong line (`component_breakdown`, removed from
  the real API contract when `tables` replaced it) plus missing documentation for `llm_metrics`, the
  per-node table/cost state keys, and the `rag`/`compression` eval harnesses.

**The headline finding, not a nice-to-have**: zero automated tests exist anywhere in this repository — no
pytest, no test directory, no vitest config, confirmed by direct check. Every bug found and fixed across
this entire build was verified once, by hand, then the verification script discarded. `rag/eval.py` and
`compression/eval.py` are the only real, checked-in, repeatable exceptions — and both already caught real
regressions on their own first runs — but they cover 2 of the app's ~10 major features. Nothing plays that
role for the agent prompts, the tax-slab math, duplicate detection, or the encryption boundary, all of
which had at least one real bug this session.

Four smaller functional gaps flagged, not auto-fixed (judgment calls, not unambiguous cleanup): two LLM
calls (`payslip_extraction.py`'s PDF parse, `rag/retriever.py`'s embedding lookup) aren't covered by the
`llm_metrics` cost-tracking work, so the displayed per-turn cost undercounts true spend; `session_history`
is capped in the prompt but not over the wire (still fetched/transmitted unbounded on every `/chat` call);
no DELETE endpoint for the financial profile, asymmetric with payslip snapshots; `db.database.init_db()`
remains a documented-but-real footgun for a future deploy script.

Full findings, verified numbers, and priority order published as an artifact rather than left in chat
scrollback.

## A pytest regression suite, closing the headline finding from the code review (Aug 2026, user-requested)

The code review above flagged zero automated tests as the headline finding. `backend/tests/` now has 101
tests covering every one of this session's ~15 reported/fixed bugs, run with `pytest` from `backend/` — no
setup required for 97 of them:

- **`test_tax_calculations.py`** (17 tests) — 80C/80D/24(b) gap math, including the exact PF-annualization
  mechanism behind the "two agents disagreed on the same total" bug and the reported ₹1,46,337 scenario.
- **`test_tax_slabs.py`** (14 tests) — old/new regime slab math, and `cheaper_regime_statement()`'s three
  branches. The "old regime cheaper" branch is the one that actually broke in production and the one every
  ad hoc manual test that session happened to skip, since the app's realistic deduction caps under the
  current slabs make the new regime cheaper almost universally — that branch is tested here with directly
  constructed `TaxResult` fixtures rather than hunting for real inputs that reach it.
- **`test_payslip_trends.py`** (22 tests) — trend direction, the mid-period-bonus-not-lost case, duplicate
  detection, and `resolve_effective_payslip`'s fallback (the root cause of payslip_agent and nudge_agent
  once disagreeing on total deductions).
- **`test_compression.py`** (9 tests) — Level 1 sliding window, Level 2's session cap, and a structural
  check that a summary never re-embeds the full payslip snapshot (the actual net-negative-compression bug).
- **`test_orchestrator_assembler.py`** (21 tests) — content-based table dedup (the duplicated-table bug) and
  `_normalize_impact` (the literal-`"null"`-string-in-a-nudge-card bug).
- **`test_llm_metrics.py`** (14 tests) — the Pydantic model's validation, `compute_cost_usd`'s
  unknown-model-returns-zero-not-a-guess behavior, and `summarize()`'s aggregation.
- **`test_integration_agents.py`** (4 tests, `@pytest.mark.integration`) — the handful of fixes that were
  bugs in the LLM's *prose*, not in any number, so a unit test alone can't catch a regression: both
  payslip_agent and nudge_agent narrating the correct cheaper-regime conclusion from shared numbers (the
  contradiction bug that survived a first fix because only the numbers, not the conclusion, were synced),
  payslip_agent not conflating zero tax with zero taxable income, and the Regulatory Agent answering a basic
  concept without an over-hedging disclaimer. Skipped automatically unless a real `OPENAI_API_KEY` is
  available (see `tests/conftest.py`) — on this dev machine that's already true via `backend/.env`, so a
  bare `pytest` run includes them; all four passed against the live API and, for the Regulatory Agent test,
  the live pgvector index.

`pytest>=8.0` added to `requirements.txt` as a dev dependency. Full suite: **101 passed in ~17s**.

## Tabs + a minimizable chat popup, replacing the sidebar/main-panel layout (Aug 2026, user-requested)

A user asked to restructure the left sidebar into tabs (Upload payslip / Payslip history / Investments &
loans) and turn the always-visible chat into a popup with a minimize control. Both implemented as asked:

- **`components/Dashboard/TabbedPanel.tsx`** — the three old stacked `<details>` sidebar sections became
  three tabs over the same unchanged content (`ActivePayslipBanner`+`PayslipUploader`,
  `PayslipHistoryUpload`+`PayslipHistoryList`, `FinancialProfileForm`). Inactive tabs stay mounted
  (`hidden`, not unmounted) rather than being torn down on switch — `ManualEntryForm` holds meaningful
  in-progress typed values a user shouldn't lose by checking another tab and coming back.
- **`components/ChatWidget/ChatWidget.tsx`** — a floating launcher button (bottom-right) that opens into a
  fixed-position panel with a header bar and a minimize control, collapsing back to the launcher button.
  Defaults **open** on load rather than closed, unlike a typical support-chat widget: chat is PayNexus's
  actual core feature here, not a secondary channel, so starting closed would hide a first-time user's main
  way of asking a question. Minimizing mid-answer doesn't lose or interrupt anything in flight — the
  streaming SSE callbacks write straight to `chatStore` (Zustand), not to `ChatInterface`'s own component
  state, so the panel unmounting doesn't touch it.
- **`App.tsx`** — the two-column `flex` layout (fixed `w-80` sidebar + `flex-1` chat) is gone; now a single
  scrollable main area holding `TabbedPanel`, with `ChatWidget` floating on top via `position: fixed`.

Verified with a clean `tsc -b && vite build` and the running dev server confirmed serving the restructured
`App.tsx`/new components live via HMR. Same caveat as the other UI work this session: no browser-automation
tool was available to click through it visually.

## Agent answer-quality eval — closing the RAG/agent eval gap (Aug 2026, user-requested)

A user asked whether industry-standard evaluation metrics were implemented; the honest answer at the time
was "partially" — `rag/eval.py` covers the Regulatory Agent's retrieval + generation quality, but nothing
scored whether the Payslip Agent or Savings Advisor's actual prose *answers* were correct, only whether the
underlying numbers were (the pytest suite above). `backend/agent_eval/` closes that gap, run manually via
`python -m agent_eval.eval` (real OpenAI calls, same cost trade-off `rag/eval.py` already makes):

- **Keyword coverage** — same deterministic, comma/case-insensitive substring check as `rag/eval.py`: does
  the agent's real narration quote the exact already-computed figure it was given (e.g. `21,840`,
  `1,002,600`), run through the actual production node, not a reimplementation.
- **Forbidden phrases** — new, and the actual point of this harness: this build's highest-recurrence bug
  was never a missing fact, it was a confidently WRONG conclusion stated despite the right numbers sitting
  in the same prompt (the regime-recommendation inversion, twice; the taxable-income/zero-tax conflation).
  Keyword coverage alone can't catch that — an answer can quote every right number and still draw the wrong
  conclusion. Every case that's ever actually broken this way now has an explicit
  `forbidden_phrases` check (e.g. `"old regime is cheaper"` must never appear when the new regime is the
  cheaper one for that fixture).

8 cases across both agents (regime recommendation from both agents on a shared fixture, taxable-income
distinctness, 80C used/remaining, duplicate-month detection, a month-over-month trend, and the fully
deterministic no-payslip-attached path as a harness sanity check) — **all 8 hand-verified against direct
`tax_calculations.py`/`tax_slabs.py`/`payslip_trends.py` invocations before being written into the dataset**,
same rigor as the pytest suite's fixtures. First real run: **100% pass rate, 100% keyword coverage, 0/8
forbidden phrases stated.**

Together with `rag/eval.py`, this now covers answer-quality for all three reasoning agents, not just one.

## UI changes, following the design audit (Aug 2026, user-requested)

Implemented the "Now" tier from the design audit below (the low-effort/high-impact items — a full
dashboard-first restructure stayed out of scope):

- **A real brand palette** — `index.css`'s `@theme` block now defines a `brand-*` color scale (deep
  navy/petrol, `#1F4B5E` at 600) as actual Tailwind v4 utilities (`bg-brand-600` etc., confirmed present in
  the compiled CSS). Every `indigo-*` class across all 9 files that had one was swapped to the equivalent
  `brand-*` shade — confirmed zero `indigo` references left anywhere in `src/` or the production bundle.
  Slate stayed as the neutral scale; that part of the old palette wasn't the problem.
- **A real icon system** — added `lucide-react`, replaced all 8 emoji-as-icon instances across 6 files
  (`AgentIndicator`, `AlertBanner`, `ActivePayslipBanner`, `ManualEntryForm`, `FinancialProfileForm`) with
  proper `<Icon>` components (`FileText`, `Scale`, `Lightbulb`, `Info`, `AlertTriangle`, `Check`, `X`,
  `CircleDashed`). Confirmed zero emoji glyphs remain anywhere in `src/`.
- **Right-aligned numeric table columns** — `DataTable.tsx` now detects, per column, whether every
  non-empty cell in it is currency/count/percentage-shaped (`isNumericColumn`, regex-based against the
  actual cell formats the backend's `*_table()` builders produce) and right-aligns only those columns. A
  single non-matching cell (e.g. a text label, or the `_bonus_summary` prose row mixed into a trends
  column) correctly keeps the whole column left-aligned rather than guessing — verified with 12 direct
  cell-pattern cases plus 4 full-table scenarios before wiring it in.
- **A first pass at type hierarchy** — the header now pairs a `Landmark` icon mark with a larger, tighter
  `PayNexus` wordmark instead of plain `text-base` text; sidebar section headers (`Your payslip`, `Payslip
  history`, `Your investments & loans`) became uppercase, letter-spaced micro-labels — the dashboard-sidebar
  convention the audit called out as missing — instead of looking like body text with `font-semibold`.

Verified with a clean `tsc -b && vite build` (bundle: 754KB → 762KB gzip, from `lucide-react`'s tree-shaken
icon imports — negligible), the compiled CSS actually containing the new `brand-*` utility classes, and the
running Vite dev server confirmed serving the edited source files live via HMR. No browser-automation tool
was available this session to click through it visually — noted rather than silently skipped, same as the
alerts feature below.

## UI design audit (Aug 2026, user-requested)

A user asked whether the UI could look more like "an MIT-level project or a professional payroll domain
UI." Scoped to a written audit + recommendations first, not a rebuild. Findings: the app is functionally
solid but visually is Tailwind's out-of-the-box defaults, not a chosen identity — every accent is a raw
`indigo-600`/`slate-*` token (13× `text-slate-400`, 9× `indigo` text/bg, zero custom palette in
`index.css`), 8 emoji stand in for a real icon system across 6 files, there's no defined type scale, and
the actual payslip figures only ever surface inside a chat answer rather than a persistent glanceable
summary. Full findings, evidence, and a Now/Next/Later prioritized fix list published as an artifact rather
than left in chat scrollback.

## Date/data-driven alert banners (Aug 2026, user-requested)

A user asked for login alerts — a July 31st tax-filing deadline reminder specifically, plus "any other
alert we can popup." Landed on four, all computed the same way as the tax math throughout this build:
exact Python-style logic (here, TypeScript), never an LLM guess, since "is it currently within N days of a
real calendar deadline" has one right answer.

`frontend/src/utils/alerts.ts`'s `computeAlerts(now, snapshots, financialProfile)` — a pure function of the
current date and data already loaded into stores at login (no new network round trip) — returns whichever
of these currently apply:
- **ITR filing deadline** — June 1 through July 31, with a days-remaining count; severity escalates to
  `warning` inside the last 14 days.
- **Regime declaration reminder** — mid-February through April, when employers typically collect the
  old-vs-new regime choice for the new financial year.
- **Unused deduction headroom** — January through March (last chance to actually invest before the FY
  closes), only fires if the financial profile shows ₹20,000+ of unused 80C/80D/24(b) room. Note: the
  section limits are duplicated here from `backend/tax_calculations.py`, not imported — there's no shared
  package between the Python backend and this TS frontend, so both need updating if a limit ever changes.
  Deliberately a rougher check than the backend's real version (no employee-PF annualization) — good enough
  for "you have room, go ask," not a replacement for the chat-computed figure.
- **Stale payslip history** — no saved snapshot in 2+ months.

Rendered by `components/Alerts/AlertBanner.tsx` as dismissible banners under the header (not a blocking
modal — a two-month-wide window that can't be dismissed would get old fast), wired into `App.tsx` right
after login. Dismissal is per-day (`localStorage`, not account data — deliberately never encrypted/synced),
so closing a banner doesn't hide it for the rest of the window, just until tomorrow.

Verified by direct invocation (12 scenarios covering all four branches: each window boundary, the
day-of/day-after edges, a fully-maxed profile producing no headroom alert, a null profile, fresh vs. stale
payslip data, and all four firing together) plus a clean `tsc -b && vite build`. No browser-automation tool
was available in this session to click through it visually — noted here rather than silently skipped.

## Code + functionality review, Pass 2 (Aug 2026, user-requested)

A user asked for another review pass now that more had shipped. Re-ran every Pass 1 check fresh (`ruff`,
`vulture`, `tsc -b && vite build`) plus the two new automated suites (`pytest`, `agent_eval`) — all clean,
no new dead code found in either the backend or the frontend (every component file is still imported
somewhere, no orphaned npm dependencies, `indigo`/emoji fully purged from the compiled output).

**The actual finding worth flagging**: `.claude/skills/run-paynexus/driver.mjs` — the project's own
Playwright browser driver — turned out to have two real bugs, both found only by actually executing it
rather than reading the code and assuming it still worked:

1. **A pre-existing false-negative in its PASS/FAIL check**, unrelated to anything this session touched.
   `GET /financial-profile` correctly 404s for any account with no saved profile yet — the backend's own
   designed "empty" signal, already handled gracefully by the frontend — but the driver registers a
   brand-new user on every single run, so it 404s every time, and the browser logs a generic
   `Failed to load resource: ...404` line to the console regardless of the app handling it correctly. The
   driver's old blanket "any console error = FAIL" meant this script had likely never printed a clean
   `PASS` since it was first written (confirmed via `git log` — this file hasn't changed since the initial
   scaffold commit). Fixed by filtering that one generic message and name-checking real HTTP failures
   against a small `EXPECTED_404_PATHS` list, so a genuinely broken resource still fails the run.
2. **Real breakage from this session's own tabs/popup restructuring**: the driver waited on
   `text=Your payslip` — the old sidebar's `<h2>`, gone since the tab rewrite. Fixed to wait on
   `text=Upload payslip PDF` instead.

Both fixed and re-verified: `node driver.mjs` now completes register → tab renders → payslip entered →
question asked → real answer + table rendered, with the numeric "Amount" column correctly right-aligned
and the new brand-colored "Using this payslip ✓" confirmation visible — **clean PASS, zero console
errors.** `SKILL.md` updated to document both as Gotchas, add `pytest`/`agent_eval` to the
"what to use when" table, and correct the flow description for the new tab/popup layout.

Also worth being honest about: earlier in this session, UI changes (the alert banners, the tab/popup
restructuring) were verified by build/typecheck/direct-invocation only, with a note that "no
browser-automation tool was available." That wasn't quite accurate — `driver.mjs` was available the whole
time; it just wasn't checked for. Corrected here, and it's what caught finding #2 above.

3 of Pass 1's 4 flagged functional gaps are still open (re-confirmed via grep, not carried forward from
memory): the two uncounted LLM calls in cost tracking, `session_history` uncapped over the wire, and no
`DELETE` for the financial profile. One new minor item: `DevAlertPreview.tsx`'s three preview dates are
hardcoded independently of `utils/alerts.ts`'s real window constants — safe today, a coupling risk if the
windows are ever adjusted without updating both.

Full findings republished to the same review artifact rather than a new one, since it's a direct
continuation of the same review.

## Ollama hybrid inference, actually tested for the first time (Aug 2026, user-asked)

A user asked "did we test Ollama?" Honest answer at the time: no — `USE_LOCAL_SLM=False` in `.env` this
entire build, so `agents/llm.py`'s `_try_ollama()` had never actually executed in any real run. Two more
things surfaced just from checking, before any real testing: Ollama (already installed and running on this
machine) only had `llama3.1:8b` pulled, not the `phi4-mini` the code hardcodes — so even flipping
`USE_LOCAL_SLM=True` today would have silently fallen back to OpenAI, logging only a warning, never
surfacing as a real error.

Pulled `phi4-mini` (2.5GB) and actually exercised the path for real, via direct invocation with
`USE_LOCAL_SLM` overridden true:

- **Plain-text completion**: worked correctly — real answer generated locally, metrics correctly showed
  `model: phi4-mini` (confirming no silent OpenAI fallback) and `cost_usd: 0.0`. **Latency: ~18 seconds**
  for one short sentence — worth knowing before ever enabling this for a live chat flow; OpenAI's cloud
  latency for the same kind of call is more like 1-3 seconds.
- **JSON mode (what `nudge_agent` actually depends on) — failed on first real test.** phi4-mini wrapped its
  answer in a ` ```json ` fence despite the prompt explicitly saying "no prose outside the JSON object,"
  and the JSON inside also had an invalid inline `//` comment and objects where plain strings were
  expected. `json.loads()` rejected it outright. Had `USE_LOCAL_SLM` been on, `nudge_agent`'s
  `_parse_nudge()` would have silently returned `None` on every answer, and the user would have seen the
  raw fenced JSON blob dumped into the chat.

Fixed the fixable part: `_strip_markdown_fence()` in `agents/llm.py` strips the fence before parsing —
re-tested, now produces valid, correctly-typed JSON. The other part (a smaller model not always following
a "plain string, not an object" instruction) isn't something a strip can reliably fix — documented
honestly in `hybrid_complete()`'s docstring rather than papered over, and a caller of this path still needs
its own `try/except` around `json.loads()`, same as every OpenAI JSON-mode caller already has. 5 new
regression tests in `tests/test_llm.py`, including the exact malformed shape phi4-mini actually produced,
so this doesn't need a real Ollama call to keep verifying. Suite: **106 passed.**

`USE_LOCAL_SLM` stays `False` in `.env` — this wasn't a request to turn local inference on, just to
actually test the path that already existed rather than leave it as an untested toggle.

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
