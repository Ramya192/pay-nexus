"""
FastAPI app entry point — mounts auth, chat, and payslip routers and wires
CORS for the Vite dev server (and the Azure Static Web Apps origin once
deployed). See PROJECT_CONTEXT.md §9 for the full endpoint list and §13
Phase 4 for where this fits.

Run `alembic upgrade head` from backend/ before starting this for the first
time against a given database — schema setup is Alembic's job now, not
this app's; see db/database.py's init_db docstring for why the two don't
mix safely.

Run from backend/: uvicorn api.main:app
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, budget, chat, financial_profile, goals, payslip, statement
from config import config

app = FastAPI(title="PayNexus API")

app.add_middleware(
    CORSMiddleware,
    # Add the deployed frontend's origin via CORS_ORIGINS in .env, not by
    # editing this list — see config.py.
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(payslip.router)
app.include_router(financial_profile.router)
app.include_router(statement.router)
app.include_router(goals.router)
app.include_router(budget.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
