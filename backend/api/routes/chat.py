"""
POST /chat — the main endpoint (PROJECT_CONTEXT.md §9). Runs the Agent
Framework orchestrator (agents/orchestrator_v2.py — asyncio.gather-based
concurrent fan-out, replacing the original LangGraph StateGraph) and
streams progress as it goes, via Server-Sent Events, so the frontend's
agent indicator ("Payslip Agent reasoning...", §10) shows the whole
selected agent set up front, before any of them actually run — see
stream_paynexus_workflow()'s own docstring for why. The SSE contract
itself (event names/fields) is unchanged from the original LangGraph-based
route; only what produces those events changed.
"""

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agents.agent_framework_llm import FoundryUnavailableError
from agents.llm_metrics import summarize as summarize_metrics
from agents.orchestrator_v2 import stream_paynexus_workflow
from api.models.chat import ChatRequest, SummarizeRequest, SummarizeResponse
from compression.context_compressor import compress_session_summary
from db.models import User
from security.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, user: User = Depends(get_current_user)) -> StreamingResponse:
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
    return StreamingResponse(_stream_workflow(initial_state), media_type="text/event-stream")


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


async def _stream_workflow(initial_state: dict) -> AsyncGenerator[str, None]:
    """One SSE `data:` line per agent completion. The frontend watches for
    `{"event": "agent_active", "agent": ...}` to drive the agent indicator,
    and a closing `{"event": "final", ...}` with the assembled response —
    identical contract to the original LangGraph-based route; only the
    generator underneath (stream_paynexus_workflow, agents/orchestrator_v2.py)
    changed."""
    try:
        async for event in stream_paynexus_workflow(initial_state):
            if event["kind"] == "final":
                yield _sse(
                    {
                        "event": "final",
                        "response": event.get("final_response", ""),
                        "active_agent": event.get("active_agent", ""),
                        "nudge": event.get("nudge_card"),
                        "tables": event.get("tables") or [],
                        "token_usage": event.get("token_usage") or {},
                    }
                )
            else:
                yield _sse({"event": "agent_active", "agent": event["agent"]})
    except FoundryUnavailableError:
        # A specific, well-understood case, not just "something broke" —
        # agent_framework_llm._run_with_timeout already retried once (with
        # backoff) before giving up, so this means Foundry's shared
        # GlobalStandard tier was genuinely saturated across both attempts,
        # not a one-off blip. Named explicitly for the user (2026-09-12,
        # found live: the old generic message here made a well-understood,
        # temporary capacity issue look identical to a real app bug — a bad
        # first impression for something that isn't actually broken) rather
        # than folded into the catch-all below, and logged at a lower level
        # since it's an expected, already-retried condition, not a bug to
        # investigate.
        logger.warning("Foundry unavailable after retry with backoff — surfacing a high-demand message.")
        yield _sse(
            {
                "event": "error",
                "detail": (
                    "Our AI service is experiencing unusually high demand right now — we already "
                    "retried automatically, but it's still slow. Please try asking again in a moment."
                ),
            }
        )
    except Exception:
        # Graceful fallback (§4) — an agent failing shouldn't leak a raw
        # traceback to the client; log it server-side instead.
        logger.exception("stream_paynexus_workflow failed")
        yield _sse({"event": "error", "detail": "Something went wrong reasoning over that question."})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
