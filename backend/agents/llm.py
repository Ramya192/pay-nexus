"""
Hybrid inference for the two agents the doc marks eligible for the local-SLM
toggle — Regulatory (Agent 2) and Nudge (Agent 3). Routes to GPT-4o-mini or
local Ollama phi4-mini depending on USE_LOCAL_SLM, falling back to
GPT-4o-mini automatically (with a warning log) if Ollama isn't reachable.
See PROJECT_CONTEXT.md §7.

Payslip Reasoning (Agent 1) and the Orchestrator's own intent-classification
call always use OpenAI directly and don't go through this module — see
agents/payslip_agent.py and agents/orchestrator.py.
"""

import logging
import time

from openai import OpenAI

from agents.llm_metrics import LLMCallMetrics, record_from_response, record_manual
from config import config

logger = logging.getLogger(__name__)
_openai_client = OpenAI(api_key=config.OPENAI_API_KEY)


def hybrid_complete(
    system_prompt: str, user_prompt: str, model: str, json_mode: bool = False, agent: str = "unknown"
) -> tuple[str, LLMCallMetrics]:
    """Complete a single-turn prompt on whichever backend USE_LOCAL_SLM
    selects. `model` is the OpenAI model to use when running cloud, or as
    the fallback if the local path fails — e.g. config.REGULATORY_AGENT_MODEL.
    `agent` names the caller for metrics purposes (e.g. "nudge_agent") —
    see agents/llm_metrics.py.

    `json_mode`: OpenAI gets a hard guarantee (`response_format=json_object`).
    Ollama's plain completion wrapper has no equivalent, so it only gets an
    appended instruction — best-effort, not enforced, and confirmed to
    actually matter with a real call: phi4-mini reliably wraps its answer
    in a ```json fence (stripped in _try_ollama — see
    _strip_markdown_fence) and has been observed emitting invalid JSON
    inside it too (inline `//` comments, an object where a plain string was
    asked for). The fence gets stripped; the rest doesn't get "fixed" — a
    caller parsing this path's output needs the same try/except around
    json.loads() every OpenAI JSON-mode caller already has, and shouldn't
    assume Ollama JSON mode is equivalent to OpenAI's. A caller that needs
    an actual guarantee would need to switch to langchain_ollama's
    ChatOllama with `format="json"` instead of this module's plain-text
    OllamaLLM wrapper — not done here since USE_LOCAL_SLM is off by default
    and this is a real, tested limitation to know about, not yet a reason
    to rearchitect this module.

    Returns (text, metrics) — every caller now gets exact token/cost data
    alongside the answer, not just the answer; see agents/llm_metrics.py's
    module docstring for why this didn't exist until a user asked how
    LLM-call cost was being measured at all.
    """
    if config.USE_LOCAL_SLM:
        local_result = _try_ollama(system_prompt, user_prompt, json_mode, agent)
        if local_result is not None:
            return local_result
        logger.warning("Ollama unavailable at %s — falling back to %s.", config.OLLAMA_BASE_URL, model)

    return _openai_complete(system_prompt, user_prompt, model, json_mode, agent)


def _try_ollama(
    system_prompt: str, user_prompt: str, json_mode: bool, agent: str
) -> tuple[str, LLMCallMetrics] | None:
    try:
        from langchain_ollama import OllamaLLM  # imported lazily — optional dependency path
    except ImportError:
        logger.warning("langchain-ollama not installed — install it or set USE_LOCAL_SLM=False.")
        return None

    if json_mode:
        system_prompt = system_prompt + "\n\nRespond with JSON only — no prose outside the JSON object."

    try:
        llm = OllamaLLM(model="phi4-mini", base_url=config.OLLAMA_BASE_URL)
        start = time.perf_counter()
        text = llm.invoke(f"{system_prompt}\n\n{user_prompt}")
        latency_ms = (time.perf_counter() - start) * 1000
        if json_mode:
            text = _strip_markdown_fence(text)
        # OllamaLLM's plain-text wrapper reports no token usage at all —
        # ~4 chars/token is a rough, clearly-labeled estimate (see
        # llm_metrics.record_manual's docstring), only used because this
        # path has no real count to read the way the OpenAI path does.
        metrics = record_manual(
            agent=agent,
            model="phi4-mini",
            input_tokens=len(system_prompt + user_prompt) // 4,
            output_tokens=len(text) // 4,
            latency_ms=latency_ms,
        )
        return text, metrics
    except Exception as exc:  # Ollama not running, model not pulled, connection refused, etc.
        logger.warning("Ollama call failed: %s", exc)
        return None


def _strip_markdown_fence(text: str) -> str:
    """phi4-mini routinely wraps its JSON-mode answer in a ```json ... ```
    fence despite being told "no prose outside the JSON object" — confirmed
    with a real call, not assumed: the raw model output was
    '```json\\n{...}\\n```', which json.loads() rejects outright before ever
    reaching the actual (also occasionally invalid — inline `//` comments,
    a value typed as an object where a plain string was asked for) content
    inside. This strips only the fence; it does NOT guarantee the remaining
    text is valid JSON — callers still need their own try/except around
    json.loads(), same as every OpenAI JSON-mode caller already has, since
    phi4-mini not following the type of a field (string vs. object) isn't
    something a strip can fix. See README's Ollama testing note."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]  # drop the opening ``` or ```json line
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -len("```")]
    return stripped.strip()


def _openai_complete(
    system_prompt: str, user_prompt: str, model: str, json_mode: bool, agent: str
) -> tuple[str, LLMCallMetrics]:
    # OpenAI's automatic prompt caching kicks in on its own for prompts over
    # ~1024 tokens with a stable prefix — not something this app toggles or
    # needs to flag per-call, as long as the system prompt stays
    # byte-identical across calls, which every caller of this function
    # already does.
    start = time.perf_counter()
    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"} if json_mode else None,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    metrics = record_from_response(agent=agent, model=model, response=response, latency_ms=latency_ms)
    return response.choices[0].message.content or "", metrics
