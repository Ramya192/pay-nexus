"""Unit tests for agents/tables.py's resolve_selected_tables() — pure
Python, no LLM/network call. Shared by payslip_agent.py and nudge_agent.py
to map an LLM's chosen "tables" keys back to their real, precomputed
values (see that module's own docstring)."""

import json

from agents.tables import resolve_selected_tables

_AVAILABLE = {
    "gaps": {"title": "Deduction gaps", "rows": [["80C", "50000"]]},
    "trends": {"title": "Payslip trends", "rows": [["TDS", "up"]]},
}


def _answer(tables):
    return json.dumps({"explanation": "x", "tables": tables})


class TestResolveSelectedTables:
    def test_single_valid_key_resolves(self):
        assert resolve_selected_tables(_answer(["gaps"]), _AVAILABLE) == [_AVAILABLE["gaps"]]

    def test_multiple_valid_keys_resolve_in_order(self):
        result = resolve_selected_tables(_answer(["trends", "gaps"]), _AVAILABLE)
        assert result == [_AVAILABLE["trends"], _AVAILABLE["gaps"]]

    def test_unknown_key_silently_dropped(self):
        assert resolve_selected_tables(_answer(["gaps", "not_a_real_key"]), _AVAILABLE) == [_AVAILABLE["gaps"]]

    def test_empty_list_returns_empty(self):
        assert resolve_selected_tables(_answer([]), _AVAILABLE) == []

    def test_missing_tables_key_returns_empty_not_a_crash(self):
        assert resolve_selected_tables(json.dumps({"explanation": "x"}), _AVAILABLE) == []

    def test_malformed_json_returns_empty_not_a_crash(self):
        assert resolve_selected_tables("not valid json{{{", _AVAILABLE) == []

    def test_tables_key_not_a_list_returns_empty(self):
        assert resolve_selected_tables(json.dumps({"tables": "gaps"}), _AVAILABLE) == []

    def test_non_string_entries_in_list_ignored(self):
        assert resolve_selected_tables(json.dumps({"tables": ["gaps", 123, None]}), _AVAILABLE) == [_AVAILABLE["gaps"]]

    # The actual reported gap: a repeated key must not render the same
    # table twice — see resolve_selected_tables' own docstring for why
    # this can genuinely happen (nothing stops the LLM from repeating a
    # key in its own "tables" field).
    def test_duplicate_key_resolves_only_once(self):
        result = resolve_selected_tables(_answer(["gaps", "gaps"]), _AVAILABLE)
        assert result == [_AVAILABLE["gaps"]]

    def test_duplicate_key_preserves_first_occurrence_position(self):
        """Dedup must not silently reorder the surviving keys — the first
        time a key appears is where it stays."""
        result = resolve_selected_tables(_answer(["trends", "gaps", "trends"]), _AVAILABLE)
        assert result == [_AVAILABLE["trends"], _AVAILABLE["gaps"]]
