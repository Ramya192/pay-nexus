"""
A genuine offline test double for agent_framework's chat client protocol —
closes a real gap in the test suite: every existing test either makes a
real LLM call (@pytest.mark.integration) or never touches an LLM at all
(a pure-Python fallback path). Nothing in between existed — a test that
exercises a real Agent/ChatOptions/response round trip without hitting a
network or costing tokens.

Built per agent_framework's own documented extension pattern (subclass
BaseChatClient, implement _inner_get_response — see
agent_framework/_clients.py's docstrings), not a hand-rolled duck-type.
`ChatResponse` accepts an explicit `value=` — so this fake doesn't need to
serialize its canned Pydantic instance to JSON and rely on the framework
re-parsing it; it hands the already-typed object straight through, exactly
as a real structured-output call's `.value` would ultimately resolve to.
"""

from collections.abc import Sequence
from typing import Any

from agent_framework import BaseChatClient, ChatResponse, Message
from pydantic import BaseModel


class FakeChatClient(BaseChatClient):
    """Returns the same canned value on every call — good enough for
    testing an agent's own prompt-building/table-selection/state-merging
    logic in isolation from real model output. Not a fidelity stand-in for
    real narration quality (that's what @pytest.mark.integration tests and
    agent_eval are for); this is for the wiring around the LLM call, not
    the call's actual output quality.
    """

    def __init__(self, canned_values: BaseModel | str | list[BaseModel | str]) -> None:
        super().__init__()
        self._canned_values = canned_values if isinstance(canned_values, list) else [canned_values]
        self.calls: list[dict[str, Any]] = []  # every call's messages/options, for assertions

    async def _inner_get_response(self, *, messages: Sequence[Message], stream: bool, options: dict, **kwargs: Any):
        self.calls.append({"messages": list(messages), "stream": stream, "options": dict(options)})
        # A list of canned values is consumed in order (e.g. a deliberately
        # bad first answer, then a good one — to test agent_complete()'s
        # retry-on-suspicious-response path deterministically, offline);
        # once exhausted, the last value repeats.
        value = self._canned_values[min(len(self.calls) - 1, len(self._canned_values) - 1)]
        if isinstance(value, BaseModel):
            return ChatResponse(messages=[Message("assistant", [value.model_dump_json()])], value=value)
        return ChatResponse(messages=[Message("assistant", [value])])
