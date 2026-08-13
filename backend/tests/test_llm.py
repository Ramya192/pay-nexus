"""
Unit test for agents/llm.py's _strip_markdown_fence — added after a real
Ollama call (see README's Ollama testing note) confirmed phi4-mini reliably
wraps its JSON-mode answer in a ```json fence despite being told not to,
which json.loads() rejects outright. Pure string function, no LLM call.
"""

from agents.llm import _strip_markdown_fence


class TestStripMarkdownFence:
    def test_json_labeled_fence_stripped(self):
        raw = '```json\n{"title": "x", "detail": "y", "impact": "z"}\n```'
        assert _strip_markdown_fence(raw) == '{"title": "x", "detail": "y", "impact": "z"}'

    def test_bare_fence_stripped(self):
        raw = '```\n{"a": 1}\n```'
        assert _strip_markdown_fence(raw) == '{"a": 1}'

    def test_no_fence_passed_through_unchanged(self):
        raw = '{"a": 1}'
        assert _strip_markdown_fence(raw) == raw

    def test_surrounding_whitespace_trimmed(self):
        raw = '  \n```json\n{"a": 1}\n```\n  '
        assert _strip_markdown_fence(raw) == '{"a": 1}'

    def test_real_observed_phi4_mini_output(self):
        """The exact shape from a real hybrid_complete(json_mode=True) call
        against phi4-mini this session — reproduced here as a fixture
        rather than re-hitting Ollama on every test run."""
        raw = (
            '```json\n'
            '{\n'
            '    "title": "Utilize Unused Section 80C Deductions",\n'
            '    "detail": "You have room left.",\n'
            '    "impact": "Tax savings possible."\n'
            '}\n'
            '```'
        )
        stripped = _strip_markdown_fence(raw)
        assert not stripped.startswith("```")
        assert not stripped.endswith("```")
        assert stripped.startswith("{")
        assert stripped.endswith("}")
