# PayNexus — Project Context File for Claude Code
> Feed this file to Claude Code at the start of every session.
> Last updated: August 11, 2026

---

## 1. Project Overview

**Name:** PayNexus
**Tagline:** "Your pay, explained. Your finances, guided."
**Type:** Multi-agent Agentic AI system — NOT a chatbot
**Domain:** Personal finance intelligence for Indian salaried employees
**Target user:** Any salaried employee in India confused about their payslip, tax regime, or financial decisions

**The problem:**
Over 60 million salaried employees in India receive a payslip monthly but lack the literacy to interpret it. Tax regime decisions (old vs new) alone can mean ₹30,000–₹80,000 difference annually. CAs are expensive for routine questions. No existing tool reasons over a specific payslip and gives personalized, actionable intelligence.

**What PayNexus does:**
A user uploads or enters their payslip data, asks a question in plain language, and four specialized AI agents collaborate to answer — explaining pay changes, translating regulatory updates into personal impact, and nudging toward smarter financial decisions.

---

## 2. Architecture — Four Agents + Orchestrator

### Agent 1 — Payslip Reasoning Agent
**Role:** Parses payslip components and answers "why did my pay change" with step-by-step reasoning.
**Handles:**
- Basic, HRA, Special Allowance, PF (employee + employer), Professional Tax, TDS, Bonus, Reimbursements
- HRA exemption calculation (actual rent paid, 50/40% of basic, HRA received — least of three)
- Old vs new tax regime comparison for user's specific salary structure
- Bonus tax impact estimation
- Form 16 component reconciliation
- Month-on-month pay change explanation
**LLM:** GPT-4o (complex reasoning required — accuracy is critical here)
**Input:** Structured payslip JSON from user session
**Output:** Structured JSON with explanation, component breakdown, and follow-up suggestions

### Agent 2 — Regulatory Intelligence Agent
**Role:** Monitors Indian tax law and translates regulatory changes into personal impact.
**Handles:**
- Budget 2024/2025/2026 changes to tax slabs, standard deduction, regime defaults
- IT Act sections (80C, 80D, 80CCD, 24b, 10(13A) for HRA, 10(14) for allowances)
- EPFO circulars and PF limit changes
- State-specific Professional Tax rules
- TDS rate changes (192, 194)
- New vs old regime default change (FY2024-25 new regime is default)
**LLM:** GPT-4o-mini (default) OR Ollama Phi-4-mini (when USE_LOCAL_SLM=True)
**Mechanism:** RAG over curated Indian tax document knowledge base (FAISS vector store)
**Prompt caching:** System prompt + regulatory knowledge base chunks are cached — static content, never changes per user
**Input:** User query + retrieved regulatory chunks
**Output:** Plain-language impact statement with approximate ₹ figures where calculable

### Agent 3 — Financial Nudge Agent
**Role:** Tracks payroll patterns across sessions and proactively nudges toward better financial decisions.
**Handles:**
- Detecting tax bracket shifts due to overtime/bonus
- 80C utilization gaps ("you've used only ₹45,000 of your ₹1.5L 80C limit")
- HRA claim optimization
- Regime switch recommendations based on actual deduction profile
- Session-over-session pattern detection ("your TDS has increased 3 months running")
**LLM:** GPT-4o-mini (default) OR Ollama Phi-4-mini (when USE_LOCAL_SLM=True)
**Input:** Compressed session history + current payslip snapshot + user query
**Output:** Proactive nudge cards with specific ₹ impact and action steps

### Agent 4 — Orchestrator
**Role:** LangGraph-based orchestrator. Routes user queries to correct agent(s), manages conversation state, assembles final response, handles multi-agent coordination.
**Responsibilities:**
- Intent classification: which agent(s) does this query need?
- Parallel vs sequential agent invocation depending on query type
- Context compression: before each LLM call, compress prior session history into structured summary to minimize token usage
- Graceful fallback: if an agent fails, orchestrator handles degraded response
- Agent indicator: emits which agent is currently reasoning (visible in UI)
**LLM:** GPT-4o (routing decisions need strong reasoning)
**Framework:** LangGraph (StateGraph with typed state, conditional edges)

---

## 3. Tech Stack

### Backend
```
Language:        Python 3.11+
Framework:       FastAPI
Agent Framework: LangGraph 0.2+
LLM (cloud):     OpenAI GPT-4o + GPT-4o-mini (via openai Python SDK)
LLM (local):     Ollama with Phi-4-mini (toggled via config flag)
RAG:             FAISS + LangChain document loaders
Embeddings:      text-embedding-3-small (OpenAI) for vector store
Encryption:      cryptography library (Fernet/AES-256) for server-side key handling
Database:        PostgreSQL (Azure Database for PostgreSQL — flexible server)
Auth:            JWT tokens (python-jose)
Environment:     python-dotenv for config management
```

### Frontend
```
Framework:       React 18 + TypeScript
Styling:         Tailwind CSS
State:           React Context + useReducer
Encryption:      Web Crypto API (AES-GCM, client-side, before any network call)
HTTP client:     Axios
Chat UI:         Custom — shows agent indicator ("Payslip Agent is reasoning...")
Charts:          Recharts (for payslip breakdown visualization)
Hosting:         Azure Static Web Apps (always free tier)
```

### Infrastructure
```
Cloud:           Microsoft Azure (free $200 credit account)
Backend host:    Azure App Service (B1 tier — within free credit)
Database:        Azure Database for PostgreSQL
Vector store:    FAISS (runs in-memory on App Service, index persisted to Azure Blob)
Frontend host:   Azure Static Web Apps (always free)
CI/CD:           GitHub Actions → Azure deployment
```

### Config flags
```python
# config.py
USE_LOCAL_SLM = False       # True = Ollama Phi-4-mini for Regulatory + Nudge agents
ENABLE_PROMPT_CACHE = True  # Cache regulatory knowledge base system prompt
ENABLE_CONTEXT_COMPRESSION = True  # Compress session history before LLM calls
MAX_CONTEXT_TOKENS = 2000   # Compressed context window budget per agent call
```

---

## 4. Privacy & Security Architecture

### Client-side encryption (AES-256-GCM)
- User enters payslip data in browser
- Before any network call: Web Crypto API encrypts data using a key derived from the user's password (PBKDF2 — 100,000 iterations, SHA-256)
- Encrypted blob travels to backend — backend stores ciphertext only
- Decryption happens client-side on login — server never sees plaintext salary figures
- Demo pitch: *"Even the system admin cannot read your salary data"*

### Session data
- Payslip data: encrypted at rest in PostgreSQL
- Conversation history: compressed summaries stored encrypted
- LLM API calls: plaintext values sent only within authenticated session, never logged

### What the LLM sees
- Payslip Reasoning Agent: sees actual values (decrypted client-side, sent over HTTPS in session)
- Regulatory Agent: sees only query text + regulatory document chunks — no user salary values
- Nudge Agent: sees compressed pattern summary (e.g., "TDS increased ₹X over 3 months") — not raw payslips

---

## 5. RAG Knowledge Base — Regulatory Agent

### Documents to index
```
1. Income Tax Act 1961 — key sections (80C, 80D, 80CCD, 10(13A), 10(14), 192, 194)
2. Budget 2024-25 Finance Bill highlights
3. Budget 2025-26 Finance Bill highlights  
4. New tax regime vs old regime comparison (FY2024-25 onwards)
5. EPFO circulars — PF wage ceiling, VPF rules
6. State-wise Professional Tax slabs (focus: Telangana, Maharashtra, Karnataka, Tamil Nadu)
7. HRA exemption calculation rules
8. Standard deduction history and current limits
9. Form 16 Part A and Part B structure explanation
10. TDS on salary — Section 192 detailed guide
```

### RAG pipeline
```
PDF/text ingestion → LangChain document loader
→ RecursiveCharacterTextSplitter (chunk_size=1000, overlap=200)
→ text-embedding-3-small embeddings
→ FAISS index (persisted to Azure Blob Storage)
→ Similarity search (top-k=5) on each Regulatory Agent call
→ Retrieved chunks injected into agent system prompt
```

### Prompt caching strategy
- Regulatory Agent system prompt + all indexed document chunks = static content
- Enable OpenAI prompt caching header on every Regulatory Agent call
- Estimated ~70% token cost reduction on this agent

---

## 6. Context Compression Strategy

### Problem
User interacts across multiple sessions — payslip history, past nudges, prior explanations accumulate. Sending full history to LLM on every call wastes tokens and hits context limits.

### Solution — Two-level compression
```
Level 1 (in-session): 
  Sliding window — keep last 3 exchanges verbatim, summarize older ones
  
Level 2 (cross-session):
  After each session ends, Orchestrator calls GPT-4o-mini to compress 
  full session into a structured JSON summary:
  {
    "payslip_snapshot": { "month": "Jul 2026", "basic": X, "tds": Y, ... },
    "key_changes": ["TDS increased by ₹Z", "HRA unchanged"],
    "nudges_given": ["Suggested 80C top-up of ₹X"],
    "regime_recommendation": "old regime saves ₹X annually at current deduction profile"
  }
  This summary (~200 tokens) replaces full session history in next session's context
```

---

## 7. Ollama Integration (Local SLM Toggle)

### When USE_LOCAL_SLM=True
```python
# agents/regulatory_agent.py
if config.USE_LOCAL_SLM:
    llm = OllamaLLM(model="phi4-mini", base_url="http://localhost:11434")
else:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
```

### Models
- **Phi-4-mini** via Ollama — handles RAG summarization and pattern nudges well
- Runs locally on user's machine — zero token cost, zero data leaves device for these agents
- Fallback: if Ollama not running, auto-falls back to GPT-4o-mini with a warning log

### Demo Day strategy
- Default demo: USE_LOCAL_SLM=False (stable, reliable)
- Architecture slide: show both paths, explain the toggle as a cost/privacy design decision
- Pitch: *"PayNexus supports hybrid inference — cloud LLMs for complex reasoning, local SLMs for routine tasks — making it deployable in cost-constrained or air-gapped environments"*

---

## 8. LangGraph State Design

```python
from typing import TypedDict, Annotated, List
from langgraph.graph import StateGraph, END

class PayNexusState(TypedDict):
    # User inputs
    user_query: str
    payslip_data: dict           # Decrypted payslip components
    session_history: List[dict]  # Compressed conversation history
    user_id: str
    
    # Routing
    intent: str                  # "payslip_explain" | "regulatory" | "nudge" | "multi"
    agents_to_invoke: List[str]
    
    # Agent outputs
    payslip_response: str
    regulatory_response: str
    nudge_response: str
    
    # Final
    final_response: str
    active_agent: str            # Sent to frontend for agent indicator UI
    token_usage: dict            # Track tokens per agent per call

# Graph edges (simplified)
graph = StateGraph(PayNexusState)
graph.add_node("orchestrator", orchestrator_node)
graph.add_node("payslip_agent", payslip_agent_node)
graph.add_node("regulatory_agent", regulatory_agent_node)
graph.add_node("nudge_agent", nudge_agent_node)
graph.add_node("assembler", response_assembler_node)

graph.set_entry_point("orchestrator")
graph.add_conditional_edges("orchestrator", route_to_agents)
# ... edges to assembler → END
```

---

## 9. API Endpoints (FastAPI)

```
POST /auth/register          — Register user, derive encryption key server-side salt
POST /auth/login             — Login, return JWT
POST /chat                   — Main endpoint: receives encrypted payslip + query, runs LangGraph, streams response
POST /payslip/save           — Save encrypted payslip snapshot
GET  /payslip/history        — Fetch compressed session summaries for Nudge Agent
GET  /health                 — Health check
```

### Streaming response
- `/chat` uses FastAPI StreamingResponse
- Orchestrator emits `active_agent` events as agents activate
- Frontend renders agent indicator in real time

---

## 10. Frontend Chat UI — Key Components

```
PayNexusApp
├── AuthScreen (login / register)
├── PayslipUploader
│   ├── ManualEntryForm (encrypted before submission)
│   └── PDFParser (client-side PDF text extraction → structured JSON)
├── ChatInterface
│   ├── MessageList
│   │   ├── UserMessage
│   │   └── AgentMessage
│   │       └── AgentIndicator ("🔍 Payslip Agent reasoning..." | "📋 Regulatory Agent..." | "💡 Nudge Agent...")
│   ├── ChatInput
│   └── NudgeCard (proactive suggestion cards from Agent 3)
└── PayslipDashboard
    └── BreakdownChart (Recharts — visual payslip component breakdown)
```

---

## 11. Project Folder Structure

```
paynexus/
├── backend/
│   ├── agents/
│   │   ├── orchestrator.py       # LangGraph StateGraph definition
│   │   ├── payslip_agent.py      # Agent 1
│   │   ├── regulatory_agent.py   # Agent 2 (RAG + prompt cache)
│   │   └── nudge_agent.py        # Agent 3 (context compression)
│   ├── rag/
│   │   ├── build_index.py        # One-time FAISS index builder
│   │   ├── loader.py             # Document ingestion pipeline
│   │   └── retriever.py          # Similarity search wrapper
│   ├── api/
│   │   ├── main.py               # FastAPI app entry point
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   └── payslip.py
│   │   └── models/
│   │       ├── user.py
│   │       └── payslip.py
│   ├── db/
│   │   ├── database.py           # PostgreSQL connection (SQLAlchemy)
│   │   └── models.py             # ORM models
│   ├── security/
│   │   ├── encryption.py         # Salt generation, key derivation helpers
│   │   └── auth.py               # JWT handling
│   ├── compression/
│   │   └── context_compressor.py # Session history compression logic
│   ├── config.py                 # All config flags (USE_LOCAL_SLM etc.)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   ├── PayslipUploader/
│   │   │   ├── AgentIndicator/
│   │   │   └── NudgeCard/
│   │   ├── crypto/
│   │   │   └── clientEncryption.ts  # Web Crypto API AES-GCM implementation
│   │   ├── api/
│   │   │   └── client.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── tailwind.config.js
├── rag_documents/               # Indian tax PDFs and text files for indexing
├── .github/
│   └── workflows/
│       └── deploy.yml           # GitHub Actions → Azure deployment
├── .env.example
└── README.md
```

---

## 12. Environment Variables

```bash
# .env (never commit this)
OPENAI_API_KEY=your_openai_key_here

# LLM config
USE_LOCAL_SLM=False
OLLAMA_BASE_URL=http://localhost:11434

# Database
DATABASE_URL=postgresql://user:password@host:5432/paynexus

# Auth
JWT_SECRET_KEY=your_jwt_secret
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# Azure (populated after deployment)
AZURE_STORAGE_CONNECTION_STRING=
FAISS_INDEX_BLOB_NAME=paynexus_faiss_index

# Feature flags
ENABLE_PROMPT_CACHE=True
ENABLE_CONTEXT_COMPRESSION=True
MAX_CONTEXT_TOKENS=2000
```

---

## 13. Build Order for Claude Code

Follow this exact sequence — do not skip ahead:

**Phase 1 — Foundation**
1. Project scaffold (folder structure, requirements.txt, package.json)
2. Config module (config.py with all flags)
3. Database models and connection (SQLAlchemy + PostgreSQL)
4. Auth system (JWT + user registration/login endpoints)

**Phase 2 — RAG Pipeline**
5. Document loader (ingest Indian tax PDFs from rag_documents/)
6. FAISS index builder (build_index.py — run once)
7. Retriever wrapper (similarity search, top-k=5)

**Phase 3 — Agents**
8. Payslip Reasoning Agent (Agent 1 — GPT-4o, structured output)
9. Regulatory Intelligence Agent (Agent 2 — RAG + prompt cache + Ollama toggle)
10. Financial Nudge Agent (Agent 3 — context compression + Ollama toggle)
11. Orchestrator (LangGraph StateGraph — routing + assembly)

**Phase 4 — API**
12. FastAPI app + chat endpoint (streaming)
13. Payslip save/fetch endpoints
14. Wire agents to API

**Phase 5 — Frontend**
15. React app scaffold (Vite + TypeScript + Tailwind)
16. Client-side encryption (Web Crypto API)
17. Chat UI with agent indicator
18. Payslip uploader (manual entry form)
19. Nudge cards component

**Phase 6 — Deployment**
20. Dockerfile (backend)
21. GitHub Actions workflow (deploy to Azure App Service + Static Web Apps)
22. Azure PostgreSQL setup + FAISS index upload to Blob Storage

---

## 14. Key Design Decisions to Defend

| Decision | Reason |
|---|---|
| LangGraph over raw LangChain | Production-grade state management, typed state, conditional routing — not just a chain |
| GPT-4o for Payslip Agent | Tax calculation errors directly mislead users — accuracy over cost |
| GPT-4o-mini for Regulatory + Nudge | RAG retrieval + summarization — smaller model sufficient, major cost saving |
| Ollama toggle (not default) | Demo stability first; local SLM as architecture feature, not liability |
| Client-side AES-256 | Server-side encryption still exposes data during processing — client-side means zero plaintext on server |
| FAISS over ChromaDB | Simpler to deploy on Azure App Service — no separate vector DB service needed for prototype |
| Prompt caching on Regulatory Agent | Regulatory docs are static — caching is free money; ~70% cost reduction on that agent |
| Context compression | Without it, multi-session users hit context limits and token costs balloon |
| FastAPI + StreamingResponse | Agent indicator in UI requires streaming — Flask/Django don't stream as cleanly |
| Stateless payslip option (future) | If user opts out of storage, session-only mode still works — privacy-first design |

---

## 15. Demo Day Flow (What to Show)

**Scene 1 — The hook (30 seconds)**
> Show a real Indian payslip. Ask PayNexus: *"Why did my take-home drop by ₹4,200 this month?"*
> Agent indicator shows: *"Payslip Agent reasoning..."*
> Response: step-by-step breakdown showing TDS increased due to bonus pushing into higher bracket.

**Scene 2 — Regulatory intelligence (30 seconds)**
> Ask: *"How does the new Budget 2025 standard deduction change affect me?"*
> Agent indicator: *"Regulatory Agent reasoning..."*
> Response: "Standard deduction increased to ₹75,000 — based on your salary, this saves you approximately ₹X annually under the new regime."

**Scene 3 — Proactive nudge (20 seconds)**
> PayNexus proactively shows a nudge card: *"You've used only ₹45,000 of your ₹1.5L 80C limit this financial year. Investing ₹1.05L more could save you ₹X in tax."*

**Scene 4 — Architecture (40 seconds)**
> Show the architecture diagram — four agents, orchestrator, LangGraph routing, hybrid inference toggle.
> One sentence on each engineering decision.

**Total demo: ~2 minutes. Leave 1 minute for questions.**

---

*End of context file. Feed this to Claude Code at the start of each session with:*
*"Read this context file fully before writing any code. Follow the build order in Section 13."*
