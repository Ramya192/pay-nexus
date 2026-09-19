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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.routes import auth, budget, chat, financial_profile, goals, payslip, statement
from config import config
from security.rate_limit import limiter

# Opt-in, not automatic: only runs when APPLICATIONINSIGHTS_CONNECTION_STRING
# is actually set (deployed App Service only -- see config.py). Every local/
# CI/test run has it unset and this whole block is a no-op, so nothing about
# existing dev/test behavior changes. Auto-instruments FastAPI (request
# latency, status codes, exceptions) and outbound httpx/requests calls with
# no per-route code -- this is what closes the "no APM/tracing, every number
# in the README came from a one-off command" gap (see PayNexus Scorecard.html
# Ops/cost section).
if config.APPLICATIONINSIGHTS_CONNECTION_STRING:
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=config.APPLICATIONINSIGHTS_CONNECTION_STRING)

app = FastAPI(title="PayNexus API", version="2.0.0")

if config.APPLICATIONINSIGHTS_CONNECTION_STRING:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)

# See security/rate_limit.py's docstring for why this exists and its scope.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
