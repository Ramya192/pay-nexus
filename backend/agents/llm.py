"""
Local-SLM (Ollama) inference path, kept for the GPT-4o-mini/Ollama hybrid
toggle (USE_LOCAL_SLM) still used by budget_agent/goal_agent/nudge_agent/
regulatory_agent. See PROJECT_CONTEXT.md §7.

The CLOUD half of that hybrid toggle — and every direct-OpenAI agent — moved
to Agent Framework + Azure AI Foundry (agents/agent_framework_llm.py — see
that module's docstring for why Ollama specifically stayed on this
separate, unchanged path rather than also moving to Agent Framework:
there's no first-party Ollama chat client in the installed agent_framework
packages, and this module's own documented quirks below aren't worth
risking on a path that's off by default anyway). This module used to also
own the cloud path itself (hybrid_complete/_openai_complete, a direct
openai.OpenAI client) — removed once agent_framework_llm.hybrid_agent_complete
became the only real caller of the cloud half; that history is in git log
if it's ever needed again.
"""

import logging
import time

from agents.llm_metrics import LLMCallMetrics, record_manual
from config import config

logger = logging.getLogger(__name__)


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
