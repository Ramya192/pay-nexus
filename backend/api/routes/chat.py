"""
POST /chat — the main endpoint (PROJECT_CONTEXT.md §9). Runs the LangGraph
orchestrator and streams progress as it goes, via Server-Sent Events, so the
frontend's agent indicator ("Payslip Agent reasoning...", §10) can update in
real time as each LangGraph node actually completes — driven by
stream_mode="updates", not simulated.
"""

import json
import logging
from collections.abc import Generator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agents.llm_metrics import summarize as summarize_metrics
from agents.orchestrator import paynexus_graph
from api.models.chat import ChatRequest, SummarizeRequest, SummarizeResponse
from compression.context_compressor import compress_session_summary
from db.models import User
from security.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(body: ChatRequest, user: User = Depends(get_current_user)) -> StreamingResponse:
    initial_state = {
        "user_query": body.query,
        "payslip_data": body.payslip_data or {},
        "financial_profile": body.financial_profile or {},
        "session_history": body.session_history or [],
        "payslip_history": body.payslip_history or [],
        "conversation": body.conversation or [],
        "transactions": body.transactions or [],
        "goals": body.goals or [],
        "budgets": body.budgets or {},
        "user_id": user.id,
    }
    return StreamingResponse(_stream_graph(initial_state), media_type="text/event-stream")


@router.post("/chat/summarize", response_model=SummarizeResponse)
def summarize(body: SummarizeRequest, _user: User = Depends(get_current_user)) -> SummarizeResponse:
    """Level 2 context compression (§6) — call once when a session ends
    (wired from the frontend's logout flow). Returns plaintext; the client
    encrypts it and persists via POST /payslip/session-summary, since the
    server never holds the AES key. Auth-gated so only a logged-in user can
    burn an OpenAI call here, but the summary itself isn't tied to their
    stored data — it's computed fresh from what the client sends."""
    summary, metrics = compress_session_summary(body.exchanges, body.payslip_data or {})
    return SummarizeResponse(
        summary=summary, token_usage=summarize_metrics([metrics] if metrics else [])
    )


def _stream_graph(initial_state: dict) -> Generator[str, None, None]:
    """One SSE `data:` line per LangGraph node completion. The frontend
    watches for `{"event": "agent_active", "agent": ...}` to drive the
    agent indicator, and a closing `{"event": "final", ...}` with the
    assembled response."""
    try:
        for step in paynexus_graph.stream(initial_state, stream_mode="updates"):
            for node_name, node_update in step.items():
                if node_name == "assembler":
                    yield _sse(
                        {
                            "event": "final",
                            "response": node_update.get("final_response", ""),
                            "active_agent": node_update.get("active_agent", ""),
                            "nudge": node_update.get("nudge_card"),
                            "tables": node_update.get("tables") or [],
                            "token_usage": node_update.get("token_usage") or {},
                        }
                    )
                elif node_name != "orchestrator":
                    yield _sse({"event": "agent_active", "agent": node_name})
    except Exception:
        # Graceful fallback (§4) — an agent failing shouldn't leak a raw
        # traceback to the client; log it server-side instead.
        logger.exception("paynexus_graph.stream failed")
        yield _sse({"event": "error", "detail": "Something went wrong reasoning over that question."})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
