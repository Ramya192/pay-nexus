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

from openai import OpenAI

from config import config

logger = logging.getLogger(__name__)
_openai_client = OpenAI(api_key=config.OPENAI_API_KEY)


def hybrid_complete(system_prompt: str, user_prompt: str, model: str, json_mode: bool = False) -> str:
    """Complete a single-turn prompt on whichever backend USE_LOCAL_SLM
    selects. `model` is the OpenAI model to use when running cloud, or as
    the fallback if the local path fails — e.g. config.REGULATORY_AGENT_MODEL.

    `json_mode`: OpenAI gets a hard guarantee (`response_format=json_object`).
    Ollama's plain completion wrapper has no equivalent, so it only gets an
    appended instruction — best-effort, not enforced. A caller that needs
    guaranteed-valid JSON from the local path too would need to switch to
    langchain_ollama's ChatOllama with `format="json"` instead of this
    module's plain-text OllamaLLM wrapper.
    """
    if config.USE_LOCAL_SLM:
        local_response = _try_ollama(system_prompt, user_prompt, json_mode)
        if local_response is not None:
            return local_response
        logger.warning("Ollama unavailable at %s — falling back to %s.", config.OLLAMA_BASE_URL, model)

    return _openai_complete(system_prompt, user_prompt, model, json_mode)


def _try_ollama(system_prompt: str, user_prompt: str, json_mode: bool) -> str | None:
    try:
        from langchain_ollama import OllamaLLM  # imported lazily — optional dependency path
    except ImportError:
        logger.warning("langchain-ollama not installed — install it or set USE_LOCAL_SLM=False.")
        return None

    if json_mode:
        system_prompt = system_prompt + "\n\nRespond with JSON only — no prose outside the JSON object."

    try:
        llm = OllamaLLM(model="phi4-mini", base_url=config.OLLAMA_BASE_URL)
        return llm.invoke(f"{system_prompt}\n\n{user_prompt}")
    except Exception as exc:  # Ollama not running, model not pulled, connection refused, etc.
        logger.warning("Ollama call failed: %s", exc)
        return None


def _openai_complete(system_prompt: str, user_prompt: str, model: str, json_mode: bool) -> str:
    # OpenAI's automatic prompt caching (ENABLE_PROMPT_CACHE, §5) kicks in on
    # its own for prompts over ~1024 tokens with a stable prefix — nothing to
    # flag per-call, as long as the system prompt stays byte-identical across
    # calls, which every caller of this function already does.
    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"} if json_mode else None,
    )
    return response.choices[0].message.content or ""
