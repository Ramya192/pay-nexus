"""
Agent Framework migration — replaces agents/llm.py's `hybrid_complete`
and the direct-OpenAI agents' own `_client.chat.completions.create` calls
with `agent_framework.Agent` + `FoundryChatClient`.

Deliberately does NOT route Ollama through Agent Framework: there's no
first-party Ollama chat client in the installed agent_framework packages,
and Ollama's plain-completion API shape is a different, already-tested,
best-effort path (see agents/llm.py's `_try_ollama` docstring for its own
documented quirks — markdown-fence stripping, occasionally-invalid JSON).
Forcing it through Agent Framework's structured-output machinery would risk
breaking a working (if imperfect) fallback for no real benefit, since
USE_LOCAL_SLM is off by default anyway. So: Ollama keeps using
`agents.llm._try_ollama` completely unchanged; only the CLOUD half of the
hybrid toggle — and every direct-OpenAI agent — moves to Agent Framework.

Every agent's JSON contract becomes a Pydantic model (see each agent
module) instead of a raw dict the agent hand-parses with `json.loads` +
`try/except`. `hybrid_agent_complete`/`agent_complete` still return a JSON
*string* (`model.model_dump_json()`), not the parsed model itself — this
keeps every downstream consumer (state["*_response"], agents/tables.py's
resolve_selected_tables, agent_eval/eval.py, every existing test) working
completely unchanged; the Pydantic model only buys internal validation
during this call, not a new external contract.
"""

import asyncio
import logging
import random
import re
import time

from agent_framework import Agent, ChatOptions
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from pydantic import BaseModel

from agents.llm import _try_ollama
from agents.llm_metrics import LLMCallMetrics, record_from_agent_response
from config import config

logger = logging.getLogger(__name__)

# A completion whose narrative text is this short is treated as suspect and
# retried once — see _is_suspiciously_short()'s docstring for why this
# exists and what it does and doesn't catch.
_MIN_NARRATIVE_CHARS = 60


def _narrative_text(parsed: BaseModel) -> str:
    """Every agent's response model has a "the actual narration" field, just
    under a different name — "explanation" (budget/goal/payslip/spending/
    whatif) or "detail" (nudge). Falls back to the model's full JSON if
    neither is present, rather than assuming one specific shape."""
    for field in ("explanation", "detail"):
        value = getattr(parsed, field, None)
        if isinstance(value, str):
            return value
    return parsed.model_dump_json()


def _is_suspiciously_short(text: str) -> bool:
    """A real, observed failure mode under sustained load against Foundry's
    GlobalStandard (shared, best-effort — not dedicated) deployment tier:
    an occasional completion comes back schema-valid but contentless — e.g.
    "Based on your provided payslip data for March 2026." instead of
    actually stating the ₹1,002,600 figure the prompt handed it. Reproduced
    0/8 times calling an agent directly, in isolation; only appeared
    embedded in a large test suite firing many rapid real LLM calls in quick
    succession — consistent with GlobalStandard's documented shared-capacity
    behavior under load, not a prompt/schema defect. A real user asking one
    question at a time is exceptionally unlikely to hit this.

    This length check is a blunt, content-agnostic heuristic — it can't
    tell a genuinely short-but-complete answer (rare, given every agent's
    prompt requires citing real figures) from a genuinely lazy one, and it
    won't catch every bad completion. See _is_suspiciously_generic() below
    for a second, sharper check that catches a bad completion long enough
    to slip past this one.
    """
    return len(text.strip()) < _MIN_NARRATIVE_CHARS


# A real ₹ figure in this codebase is always comma-grouped (every table/
# prompt builder formats with f"₹{x:,.0f}") — this matches "₹1,002,600" or
# "1,002,600" but deliberately not a bare 4-digit year like "2026", which a
# still-evasive completion can otherwise slip in as its only digits (a real,
# observed case: "...for March 2026." with zero actual figures stated).
_RUPEE_FIGURE_RE = re.compile(r"₹|\d,\d{2,3}(?:,\d{3})*\b")


def _is_suspiciously_generic(text: str) -> bool:
    """Companion to _is_suspiciously_short() for the JSON-structured agents
    (budget/goal/nudge/payslip/spending/whatif) — checks for an actual
    rupee figure instead of length. Deliberately NOT `_is_suspiciously_short
    (text) or ...`: an earlier version was, and a real offline test
    (tests/test_agent_framework_llm.py) caught it flagging a genuinely
    short-but-correctly-grounded answer ("Your total is ₹1,002,600.") as
    suspicious purely for brevity, triggering a pointless retry. Both real,
    observed bad completions this was built to catch lacked a rupee figure
    regardless of their length (one was short, one was 120 characters) —
    so the figure check alone catches both without the length check's false
    positive. Every one of these agents' prompts explicitly requires citing
    real ₹ figures whenever the data supports it, so a rupee figure's
    absence entirely is a strong signal on its own — unlike
    regulatory_agent's plain-prose path, which legitimately answers purely
    definitional questions with no rupee figure at all (see
    hybrid_agent_complete_text, which uses only the length check, not this
    one, for exactly that reason)."""
    return not _RUPEE_FIGURE_RE.search(text)


def _merge_metrics(first: LLMCallMetrics, second: LLMCallMetrics) -> LLMCallMetrics:
    """Combines two calls' worth of metrics into one — used when a retry
    actually happens, so token/cost accounting reflects both real calls
    (the discarded first attempt still cost real tokens), not just
    whichever attempt's answer was kept."""
    return LLMCallMetrics(
        agent=second.agent,
        model=second.model,
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cost_usd=first.cost_usd + second.cost_usd,
        latency_ms=first.latency_ms + second.latency_ms,
    )


class FoundryUnavailableError(TimeoutError):
    """Raised instead of a bare `TimeoutError` once every retry attempt in
    `_run_with_timeout` has timed out — a subclass, not a new exception
    family, so nothing that already catches `TimeoutError`/`Exception`
    upstream needs to change; it exists purely so api/routes/chat.py CAN
    catch this specific, well-understood case (Foundry's shared capacity
    tier genuinely saturated, confirmed by the fact that even a
    backed-off retry didn't help) and give the user an honest, specific
    explanation instead of the generic "something went wrong" every other
    unexpected exception gets. See _run_with_timeout's docstring for the
    full reasoning (2026-09-12 addition) and the Azure guidance it's
    grounded in."""


# Backoff before a timeout retry — deliberately NOT an immediate re-attempt.
# Per Microsoft's own documented guidance for Azure OpenAI/Foundry's shared
# GlobalStandard tier (learn.microsoft.com Q&A threads on 429/latency
# handling, cross-checked against multiple independent write-ups, not
# assumed): the standard, recommended pattern for a saturated shared-capacity
# pool is exponential backoff WITH jitter, never an immediate retry — hitting
# the same contended pool again with zero delay does nothing to improve the
# odds and, at any real scale, is exactly the kind of synchronized retry
# ("thundering herd") that makes shared-tier contention worse for everyone
# on it, not just this one request. A few seconds of backoff is negligible
# next to the 90-120s timeout that already elapsed to get here.
_TIMEOUT_RETRY_BACKOFF_BASE_S = 1.5
_TIMEOUT_RETRY_BACKOFF_JITTER_S = 1.5


async def _run_with_timeout(agent: str, coro_factory, timeout: float | None = None, retries: int = 1):
    """Guards every real Foundry call against hanging indefinitely — and,
    as of 2026-09-12, against having to fail the whole user turn the first
    time that bound is hit.

    Real, observed root cause (2026-09-11): nothing here ever wrapped
    `runner.run()` in a timeout, so a slow/throttled response from
    Foundry's GlobalStandard (shared, best-effort — not dedicated) tier —
    the same shared-capacity behavior documented in
    _is_suspiciously_generic()'s docstring, just manifesting as latency
    instead of a contentless completion — just hung the whole request
    forever: no error, no fallback, no feedback beyond a spinner. Confirmed
    live: the exact same single-agent query hung twice in a row and had to
    be manually stopped both times.

    **2026-09-12 addition, found live**: the timeout guard above turned an
    indefinite hang into a bounded failure, but did nothing to actually
    recover from it — a timed-out call still surfaced the generic SSE
    error to the user every single time, who then had to notice the
    failure and manually re-ask the exact same question themselves before
    it would work (confirmed live: a "new payslip rules" regulatory
    question — the slower of the two regulatory paths, since a RAG-miss
    triggers a second, real web-search call on top of the first — failed
    outright on one attempt, then succeeded on unmodified retry).

    Grounded in Microsoft's own documented guidance for exactly this
    situation (Azure OpenAI/Foundry Q&A threads on GlobalStandard latency
    and 429 handling — not guessed): (1) retry with exponential backoff
    AND jitter, never an immediate re-attempt against a saturated shared
    pool (see _TIMEOUT_RETRY_BACKOFF_BASE_S's comment); (2) Provisioned
    Throughput (PTU) is Microsoft's own stated fix for consistently low
    latency — GlobalStandard is explicitly a best-effort tier by design,
    and no amount of client-side retry logic changes that; a genuinely
    latency-sensitive production deployment of this app should budget for
    PTU, not lean on retries alone indefinitely. This function is the
    honest, bounded mitigation available at zero additional infra cost,
    not a claim that it makes the underlying tier behave like a dedicated
    one.

    `coro_factory` is a zero-argument callable returning a FRESH coroutine
    each time it's invoked (e.g. `lambda: runner.run(user_prompt)`), not a
    bare coroutine object — a coroutine can only ever be awaited once, so
    retrying requires creating a new one per attempt rather than reusing
    the one `asyncio.wait_for` already consumed (and cancelled) on the
    prior timeout.

    Still only retries on `TimeoutError` specifically — any other
    exception (a real 4xx/5xx from Foundry, an auth failure, etc.)
    propagates immediately, same as before this existed. After `retries`
    timeouts in a row (default 1, i.e. 2 attempts total), raises
    `FoundryUnavailableError` (a `TimeoutError` subclass, so anything
    upstream that already handles `TimeoutError`/`Exception` is
    unaffected) specifically so api/routes/chat.py can recognize this
    exact, well-understood case and give the user an honest, specific
    message ("high demand, try again shortly") instead of the generic
    catch-all error every other unexpected exception still gets.
    """
    effective_timeout = timeout if timeout is not None else config.FOUNDRY_CALL_TIMEOUT_SECONDS
    attempt = 0
    while True:
        try:
            return await asyncio.wait_for(coro_factory(), timeout=effective_timeout)
        except TimeoutError:
            attempt += 1
            if attempt > retries:
                logger.warning(
                    "%s: Foundry call exceeded the %ss timeout on attempt %d/%d (with backoff between "
                    "attempts) — giving up and surfacing a high-demand error to the user.",
                    agent, effective_timeout, attempt, retries + 1,
                )
                raise FoundryUnavailableError(
                    f"{agent}: Foundry call exceeded the {effective_timeout}s timeout on all "
                    f"{retries + 1} attempt(s)."
                ) from None
            backoff = _TIMEOUT_RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(
                0, _TIMEOUT_RETRY_BACKOFF_JITTER_S
            )
            logger.warning(
                "%s: Foundry call exceeded the %ss timeout on attempt %d/%d — backing off %.1fs then retrying.",
                agent, effective_timeout, attempt, retries + 1, backoff,
            )
            await asyncio.sleep(backoff)


# One shared credential + one FoundryChatClient per deployment name — built
# lazily (not at import time) so importing this module never requires Azure
# credentials to be resolvable (e.g. in a unit-test process with no
# az login/managed identity available), only actually calling it does.
_credential: DefaultAzureCredential | None = None
_clients: dict[str, FoundryChatClient] = {}


def _foundry_client(deployment: str) -> FoundryChatClient:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    if deployment not in _clients:
        _clients[deployment] = FoundryChatClient(
            project_endpoint=config.FOUNDRY_PROJECT_ENDPOINT,
            model=deployment,
            credential=_credential,
            allow_preview=True,
        )
    return _clients[deployment]


async def agent_complete(
    system_prompt: str,
    user_prompt: str,
    model: str,
    response_model: type[BaseModel],
    agent: str,
    check_for_generic_response: bool = True,
) -> tuple[str, LLMCallMetrics]:
    """Cloud-only structured completion via Agent Framework + Foundry — the
    direct replacement for payslip_agent/spending_agent/whatif_agent's own
    `_client.chat.completions.create(...)` calls, and for the cloud half of
    hybrid_agent_complete() below. `model` is one of this file's existing
    OpenAI model constants (e.g. config.BUDGET_AGENT_MODEL); resolved to a
    real Foundry deployment name via config.FOUNDRY_DEPLOYMENT_MAP.

    Returns (json_string, metrics) — same shape as agents/llm.py's
    hybrid_complete(), so callers don't need to change their own return
    handling beyond swapping which function they call. Retries once (see
    _is_suspiciously_generic()) if the first completion looks like the
    contentless-under-load failure mode; a second suspicious result is
    still returned as-is rather than looping indefinitely.

    `check_for_generic_response=False` skips that check entirely — for a
    response_model with no "explanation"/"detail" narrative field at all
    (e.g. orchestrator_v2.IntentClassification), _narrative_text() falls
    back to the model's full JSON dump, which is legitimately short and
    figure-free for a correct answer like {"agents": ["budget"]} — applying
    the narrative check there would misfire as a false positive on every
    single call, not just the rare bad ones.
    """
    deployment = config.FOUNDRY_DEPLOYMENT_MAP.get(model, model)
    client = _foundry_client(deployment)
    runner = Agent(client=client, instructions=system_prompt, name=agent)
    options = ChatOptions(response_format=response_model)

    start = time.perf_counter()
    response = await _run_with_timeout(agent, lambda: runner.run(user_prompt, options=options))
    metrics = record_from_agent_response(
        agent=agent, model=deployment, response=response, latency_ms=(time.perf_counter() - start) * 1000
    )
    parsed: BaseModel = response.value

    if check_for_generic_response and _is_suspiciously_generic(_narrative_text(parsed)):
        logger.warning("%s: suspiciously short completion, retrying once. Got: %r", agent, _narrative_text(parsed))
        start = time.perf_counter()
        retry_response = await _run_with_timeout(agent, lambda: runner.run(user_prompt, options=options))
        retry_metrics = record_from_agent_response(
            agent=agent, model=deployment, response=retry_response, latency_ms=(time.perf_counter() - start) * 1000
        )
        parsed = retry_response.value
        metrics = _merge_metrics(metrics, retry_metrics)

    return parsed.model_dump_json(), metrics


async def hybrid_agent_complete(
    system_prompt: str, user_prompt: str, model: str, response_model: type[BaseModel], agent: str
) -> tuple[str, LLMCallMetrics]:
    """Structured-output replacement for agents/llm.py's `hybrid_complete`,
    used by three of the four agents on the GPT-4o-mini/Ollama hybrid tier
    (budget, goal, nudge — all JSON-mode). Ollama path is untouched (see
    module docstring); only the cloud fallback moves to Agent Framework +
    Foundry. regulatory_agent is plain prose, not JSON — see
    hybrid_agent_complete_text() below.
    """
    if config.USE_LOCAL_SLM:
        local_result = _try_ollama(system_prompt, user_prompt, json_mode=True, agent=agent)
        if local_result is not None:
            return local_result
        logger.warning("Ollama unavailable — falling back to Foundry (%s).", model)

    return await agent_complete(system_prompt, user_prompt, model, response_model, agent)


async def hybrid_agent_complete_text(system_prompt: str, user_prompt: str, model: str, agent: str) -> tuple[str, LLMCallMetrics]:
    """Same as hybrid_agent_complete(), for regulatory_agent specifically —
    the one hybrid-tier agent whose response is plain prose (rendered
    directly in the chat UI, never JSON-parsed), not a structured object.
    Reads `.text` instead of `.value`; no response_format on ChatOptions."""
    if config.USE_LOCAL_SLM:
        local_result = _try_ollama(system_prompt, user_prompt, json_mode=False, agent=agent)
        if local_result is not None:
            return local_result
        logger.warning("Ollama unavailable — falling back to Foundry (%s).", model)

    deployment = config.FOUNDRY_DEPLOYMENT_MAP.get(model, model)
    client = _foundry_client(deployment)
    runner = Agent(client=client, instructions=system_prompt, name=agent)

    start = time.perf_counter()
    response = await _run_with_timeout(agent, lambda: runner.run(user_prompt))
    metrics = record_from_agent_response(
        agent=agent, model=deployment, response=response, latency_ms=(time.perf_counter() - start) * 1000
    )
    text = response.text

    if _is_suspiciously_short(text):
        logger.warning("%s: suspiciously short completion, retrying once. Got: %r", agent, text)
        start = time.perf_counter()
        retry_response = await _run_with_timeout(agent, lambda: runner.run(user_prompt))
        retry_metrics = record_from_agent_response(
            agent=agent, model=deployment, response=retry_response, latency_ms=(time.perf_counter() - start) * 1000
        )
        text = retry_response.text
        metrics = _merge_metrics(metrics, retry_metrics)

    return text, metrics


# The only deployed model confirmed (via direct testing, not assumed from
# docs) to support get_web_search_tool()'s allowed_domains/filters param —
# gpt-4.1-mini 400s with "Parameter 'filters' not supported with model
# 'gpt-4.1-mini-2025-04-14'". Hardcoded rather than looked up from
# FOUNDRY_DEPLOYMENT_MAP's caller-supplied model, since this function's
# whole point is domain-restricted web search, which only works at all on
# this one model.
_WEB_SEARCH_MODEL = "gpt-4o"


async def web_search_complete_text(
    system_prompt: str, user_prompt: str, agent: str, allowed_domains: list[str]
) -> tuple[str, LLMCallMetrics]:
    """Cloud-only, tool-using completion via Agent Framework + Foundry's
    built-in web search tool (GA, Microsoft-managed Bing — no separate
    search API key or account needed, unlike a typical custom RAG-fallback
    setup) restricted to `allowed_domains`. Built for regulatory_agent's
    RAG-miss fallback (see its module docstring): when the local pgvector
    index doesn't cover a question, this searches the live web instead of
    leaving the user to go look it up themselves.

    Always gpt-4o (see _WEB_SEARCH_MODEL) and always cloud — no Ollama/
    hybrid path, since a live web search inherently needs a real internet-
    connected cloud call; there's nothing meaningful to fall back to
    locally. No retry-on-suspicious-response handling either: a real web
    search's answer length depends entirely on what's actually out there,
    so a short "I couldn't find that" from the model here is more likely a
    genuinely honest result than a load-related contentless completion.
    """
    deployment = config.FOUNDRY_DEPLOYMENT_MAP.get(_WEB_SEARCH_MODEL, _WEB_SEARCH_MODEL)
    client = _foundry_client(deployment)
    tool = client.get_web_search_tool(allowed_domains=allowed_domains)
    runner = Agent(client=client, instructions=system_prompt, name=agent, tools=[tool])

    start = time.perf_counter()
    # lambda, not a bare coroutine — see _run_with_timeout's docstring. Real,
    # newly-introduced bug (2026-09-12, found via code inspection while
    # hardening the regulatory web-search-fallback path — unrelated to the
    # separate "no such payslip rules exist" wrong-ANSWER report, which was
    # a genuine content gap, not a crash): this call site was missed when
    # the other 4 call sites were converted to the coro_factory pattern
    # earlier in the same retry/backoff change, so EVERY web-search-fallback
    # call was raising "'coroutine' object is not callable" here, crashing
    # the whole regulatory_agent_node turn instead of ever reaching a
    # useful retry. No offline test caught it — tests/fakes.py's
    # FakeChatClient never exercised this function before this bug's own
    # regression test (TestWebSearchCompleteText below) was added.
    response = await _run_with_timeout(
        agent, lambda: runner.run(user_prompt), timeout=config.FOUNDRY_WEB_SEARCH_TIMEOUT_SECONDS
    )
    metrics = record_from_agent_response(
        agent=agent, model=deployment, response=response, latency_ms=(time.perf_counter() - start) * 1000
    )
    return response.text, metrics
