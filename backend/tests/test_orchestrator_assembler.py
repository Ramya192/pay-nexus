"""
Unit tests for agents/orchestrator.py's pure-Python assembly logic:
assembler_node's table dedup and _parse_nudge/_normalize_impact — the fixes
for two real reported bugs (a table rendered twice, and a literal "null"
string rendered in a nudge card). No LLM call in any of this — assembler_node
only merges state that upstream agent nodes already produced.
"""

from agents.orchestrator import _format_agent_response, _normalize_impact, _parse_nudge, assembler_node


class TestNormalizeImpact:
    def test_real_none_passes_through(self):
        assert _normalize_impact(None) is None

    def test_string_null_collapsed_to_none(self):
        """The exact bug: JSON-mode model emits the STRING "null" instead
        of the JSON literal — valid JSON, wrong value, and truthy in JS."""
        assert _normalize_impact("null") is None

    def test_case_and_whitespace_insensitive(self):
        assert _normalize_impact(" Null ") is None
        assert _normalize_impact("N/A") is None
        assert _normalize_impact("NONE") is None

    def test_empty_string_collapsed_to_none(self):
        assert _normalize_impact("") is None

    def test_real_impact_value_passes_through_unchanged(self):
        assert _normalize_impact("₹12,500/year") == "₹12,500/year"


class TestParseNudge:
    def test_valid_nudge_json_parsed(self):
        raw = '{"title": "Max out 80C", "detail": "You have ₹50,000 headroom left.", "impact": "₹15,000/year"}'
        result = _parse_nudge(raw)
        assert result == {"title": "Max out 80C", "detail": "You have ₹50,000 headroom left.", "impact": "₹15,000/year"}

    def test_string_null_impact_normalized_within_parse(self):
        raw = '{"title": "Max out 80C", "detail": "detail text", "impact": "null"}'
        result = _parse_nudge(raw)
        assert result["impact"] is None

    def test_missing_required_keys_returns_none(self):
        assert _parse_nudge('{"title": "only a title"}') is None

    def test_not_json_returns_none(self):
        assert _parse_nudge("plain text nudge, not JSON") is None

    def test_json_but_not_an_object_returns_none(self):
        assert _parse_nudge("[1, 2, 3]") is None


class TestFormatAgentResponse:
    def test_structured_json_rendered_as_prose_plus_bullets(self):
        raw = '{"explanation": "Your tax is lower under the new regime.", "follow_up_suggestions": ["Check 80C", "Check HRA"]}'
        text = _format_agent_response(raw)
        assert "Your tax is lower under the new regime." in text
        assert "• Check 80C" in text
        assert "• Check HRA" in text

    def test_plain_text_passed_through_unchanged(self):
        assert _format_agent_response("Section 80C allows up to ₹1,50,000.") == "Section 80C allows up to ₹1,50,000."

    def test_json_without_explanation_key_passed_through_unchanged(self):
        raw = '{"foo": "bar"}'
        assert _format_agent_response(raw) == raw


class TestAssemblerNodeTableDedup:
    def test_identical_table_from_two_agents_kept_once(self):
        """The exact reported bug: payslip_agent and nudge_agent each
        independently select the same "liability" table on a multi-agent
        question — must render once, not twice."""
        table = {"title": "Tax liability estimate", "headers": ["Regime", "Tax"], "rows": [["Old", "98,883"], ["New", "62,400"]]}
        state = {
            "payslip_response": "some payslip narration",
            "payslip_tables": [table],
            "nudge_response": '{"title": "Switch regimes", "detail": "d", "impact": null}',
            "nudge_tables": [dict(table)],  # a fresh dict, same content — the point of content-based dedup
        }
        result = assembler_node(state)
        assert result["tables"] == [table]

    def test_distinct_tables_from_different_agents_both_kept(self):
        payslip_table = {"title": "Payslip breakdown", "headers": ["Field", "Amount"], "rows": [["Basic", "50,000"]]}
        nudge_table = {"title": "Deduction gaps", "headers": ["Section", "Used"], "rows": [["80C", "50,000"]]}
        state = {
            "payslip_response": "narration",
            "payslip_tables": [payslip_table],
            "nudge_response": '{"title": "t", "detail": "d", "impact": null}',
            "nudge_tables": [nudge_table],
        }
        result = assembler_node(state)
        assert len(result["tables"]) == 2
        assert payslip_table in result["tables"]
        assert nudge_table in result["tables"]

    def test_no_tables_returns_empty_list(self):
        result = assembler_node({"payslip_response": "narration only"})
        assert result["tables"] == []


class TestAssemblerNodeSections:
    def test_active_agents_and_final_response_labeled(self):
        state = {
            "payslip_response": "payslip narration",
            "regulatory_response": "regulatory narration",
        }
        result = assembler_node(state)
        assert result["active_agent"] == "payslip_agent,regulatory_agent"
        assert "[Payslip Reasoning Agent]" in result["final_response"]
        assert "[Regulatory Intelligence Agent]" in result["final_response"]

    def test_nudge_card_populated_and_prose_uses_title_only(self):
        state = {"nudge_response": '{"title": "Max out 80C", "detail": "long detail text here", "impact": "₹15,000"}'}
        result = assembler_node(state)
        assert result["nudge_card"] == {"title": "Max out 80C", "detail": "long detail text here", "impact": "₹15,000"}
        assert "💡 Max out 80C" in result["final_response"]
        assert "long detail text here" not in result["final_response"]  # detail is in the card, not duplicated in prose

    def test_no_agent_responses_returns_graceful_fallback(self):
        result = assembler_node({})
        assert result["active_agent"] == ""
        assert "went wrong" in result["final_response"].lower()

    def test_unsupported_response_labeled_as_paynexus_not_an_agent(self):
        state = {"unsupported_response": "I can't modify your payslip data directly."}
        result = assembler_node(state)
        assert result["active_agent"] == "capability_gap_node"
        assert "[PayNexus]" in result["final_response"]

    def test_token_usage_aggregated_from_all_four_call_lists(self):
        from agents.llm_metrics import LLMCallMetrics

        call = LLMCallMetrics(agent="x", model="gpt-4o-mini", input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200)
        state = {
            "payslip_response": "r",
            "orchestrator_llm_calls": [call],
            "payslip_llm_calls": [call],
        }
        result = assembler_node(state)
        assert result["token_usage"]["total_input_tokens"] == 200
