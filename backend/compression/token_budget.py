"""
Capacity-aware ("headroom") sizing for context compression — the dynamic
counterpart to context_compressor.py's fixed _SLIDING_WINDOW/_MAX_SESSIONS
caps. Those fixed caps are deliberately tiny and always safe regardless of
which model ends up serving a turn, but that safety margin is wasted
whenever the model actually in play has far more room than the tightest
one this app ever routes to — Ollama's local phi4-mini (when
config.USE_LOCAL_SLM is on) has a context window two orders of magnitude
smaller than gpt-4o's. This module lets Level 1 (compress_in_session) and
Level 2 (cap_session_history) keep MORE history when there's real
headroom, and trim down to the same small floor only when the model
actually serving this turn genuinely demands it — see
agents/orchestrator_v2._context_window_for_turn for how the "which model(s)
this turn" part is resolved.

Every token count here is a pre-call ESTIMATE, not a real usage figure —
unlike agents/llm_metrics.py, which only ever reports exact numbers read
back from a completed call's own `.usage` field, there is no real number
yet at the point this runs (compression happens BEFORE the call it's
sizing for). Uses tiktoken when available (a real BPE tokenizer, close to
exact for OpenAI's own models) and falls back to a conservative chars/4
heuristic otherwise (tiktoken not installed, or a model — phi4-mini isn't
a tiktoken encoding at all) — either way this feeds a sizing/safety
decision, never cost tracking or billing, which stays exclusively real
numbers per llm_metrics.py's own docstring.
"""

import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:  # tiktoken not installed — fall back to the chars/4 estimate below
    tiktoken = None
    _TIKTOKEN_AVAILABLE = False

_CHARS_PER_TOKEN_ESTIMATE = 4  # only used when tiktoken (or a model's encoding) isn't available
_encoding_cache: dict[str, object] = {}


def _encoding_for(model: str):
    """None means "use the chars/4 fallback" — either tiktoken isn't
    installed, or `model` isn't one tiktoken knows a real encoding for
    (e.g. phi4-mini, an Ollama-local model with no OpenAI-style BPE
    tokenizer). Cached per model name since building an encoding isn't
    free and this runs once per compression call, not once per process."""
    if not _TIKTOKEN_AVAILABLE:
        return None
    if model not in _encoding_cache:
        try:
            _encoding_cache[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            # Newer/renamed deployments (e.g. "gpt-4.1-mini") tiktoken
            # doesn't have a name mapping for yet — o200k_base is the real
            # encoding behind every current GPT-4o/4.1-family model, so
            # this is still a close-to-exact count, not a guess.
            try:
                _encoding_cache[model] = tiktoken.get_encoding("o200k_base")
            except Exception:  # pragma: no cover - only if tiktoken's own data files are missing
                logger.warning("token_budget: could not load any tiktoken encoding — falling back to chars/4 estimate.")
                _encoding_cache[model] = None
    return _encoding_cache[model]


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Best-effort token count for `text` under `model`'s tokenizer. Never
    raises — a tokenizer failure degrades to the chars/4 estimate rather
    than blowing up a compression step that only exists to keep a request
    from failing in the first place."""
    if not text:
        return 0
    encoding = _encoding_for(model)
    if encoding is not None:
        try:
            return len(encoding.encode(text))
        except Exception:
            logger.warning("token_budget: tiktoken encode failed for model=%s — falling back to chars/4 estimate.", model)
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


# --- Real context windows, deployment/model name -> max tokens ---
# Provider-published figures that change independently of this codebase —
# dated like tax_slabs.py's FY_LABEL / llm_metrics.py's PRICING_AS_OF, same
# "needs a manual refresh, not a live source" reasoning.
CONTEXT_WINDOW_AS_OF = "2026-01 — verify against the model provider's docs before relying on this"
MODEL_CONTEXT_WINDOW: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1-mini": 1_000_000,  # Foundry's real deployment behind config.FOUNDRY_DEPLOYMENT_MAP's "gpt-4o-mini" entry
    "phi4-mini": 4_096,  # Ollama's default local context length (num_ctx) unless overridden — the tightest ceiling this app ever routes to
}
_DEFAULT_CONTEXT_WINDOW = 8_000  # conservative fallback for a model name not in the table above


def context_window_for(model: str) -> int:
    return MODEL_CONTEXT_WINDOW.get(model, _DEFAULT_CONTEXT_WINDOW)


# --- Headroom math ---

# No agent in this codebase sets a real max_tokens/max_completion_tokens
# cap on its own completion (verified — grepped for it, nothing found), so
# there's no real number to reserve for "the response itself" — this is a
# deliberately generous placeholder for that, not a measured figure.
RESERVED_OUTPUT_TOKENS = 1_000

# What compress_in_session/cap_session_history have zero visibility into
# at the point they run: the agent's own system prompt, plus whatever else
# (payslip snapshot, financial profile, deduction gaps, budget/goal
# tables...) that specific agent adds to its own prompt afterward. A flat,
# deliberately conservative allowance for all of that — NOT model-specific,
# since it's about this app's own prompts, not the model serving them.
FIXED_OVERHEAD_TOKENS = 2_000

# Extra slack on top of the above two — same ">2x margin, don't cut it to
# the wire" reasoning as FOUNDRY_CALL_TIMEOUT_SECONDS's own comment.
SAFETY_MARGIN_PCT = 0.15


def headroom_tokens(context_window: int) -> int:
    """How many tokens of a `context_window`-sized model are actually free
    for the compressible history (conversation / session_history) once
    RESERVED_OUTPUT_TOKENS, FIXED_OVERHEAD_TOKENS, and SAFETY_MARGIN_PCT
    are set aside. Floors at 0 rather than going negative — a model whose
    window is smaller than the fixed overhead alone (only realistic for
    phi4-mini's 4,096-token window against a genuinely large system
    prompt) has no headroom left to offer, not negative headroom."""
    usable = context_window * (1 - SAFETY_MARGIN_PCT)
    return max(0, int(usable - RESERVED_OUTPUT_TOKENS - FIXED_OVERHEAD_TOKENS))


def trim_to_headroom(
    items: list,
    render,
    headroom: int,
    *,
    min_keep: int = 1,
    max_keep: int | None = None,
    model: str = "gpt-4o",
) -> list:
    """Keeps as many of the most recent `items` (list is oldest-first, same
    order compress_in_session/cap_session_history already receive) as fit
    inside `headroom` tokens — dropping older ones first, same direction
    the old fixed-size slice always trimmed in.

    `min_keep` is a floor: always kept even if it alone doesn't fit inside
    `headroom` (matches the old fixed window's own implicit floor of
    always keeping exactly _SLIDING_WINDOW items regardless of size —
    trimming everything away isn't a real option here). `max_keep` is a
    ceiling: never exceeded even when headroom would allow more — more
    history has diminishing narrative value and real latency/cost even
    when a huge context window could technically fit it, so this doesn't
    become "keep the entire history" just because gpt-4o has a 128K
    window.

    `render(item) -> str` turns one item into the text it would actually
    contribute to a prompt, so token counting reflects the real payload
    rather than a naive str() of the dict.
    """
    if not items:
        return items

    kept: list = []
    used = 0
    for item in reversed(items):
        if max_keep is not None and len(kept) >= max_keep:
            break
        cost = count_tokens(render(item), model=model)
        if len(kept) >= min_keep and used + cost > headroom:
            break
        kept.append(item)
        used += cost

    kept.reverse()
    return kept
