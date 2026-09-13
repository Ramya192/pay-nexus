"""
Unit tests for payslip_trends.py — month-over-month trend computation,
duplicate-month detection, and the effective-payslip fallback that was the
root cause of a real reported bug (payslip_agent and nudge_agent silently
disagreeing on total deductions because only one of them fell back to
payslip history).
"""

from payslip_trends import (
    _bonus_summary,
    compute_trends,
    detect_duplicate_months,
    duplicates_table,
    format_duplicates_for_prompt,
    format_trends_for_prompt,
    resolve_effective_payslip,
    trends_table,
)


class TestResolveEffectivePayslip:
    def test_active_payslip_wins_even_with_history_present(self):
        active = {"month": "2026-06", "basic": 50_000}
        history = [{"month": "2026-05", "basic": 48_000}]
        payslip, used_fallback = resolve_effective_payslip(active, history)
        assert payslip is active
        assert used_fallback is False

    def test_falls_back_to_most_recent_history_when_nothing_active(self):
        """The exact mechanism behind the reported bug: with no
        session-active payslip, this must return the most recent saved
        snapshot (last in the ascending-ordered list) — the fallback
        agents/payslip_agent.py and agents/nudge_agent.py both now share."""
        history = [{"month": "2026-04", "basic": 45_000}, {"month": "2026-05", "basic": 48_000}]
        payslip, used_fallback = resolve_effective_payslip({}, history)
        assert payslip == {"month": "2026-05", "basic": 48_000}
        assert used_fallback is True

    def test_no_active_and_no_history_returns_empty(self):
        payslip, used_fallback = resolve_effective_payslip({}, [])
        assert payslip == {}
        assert used_fallback is False


class TestComputeTrends:
    def test_needs_at_least_two_points_per_field(self):
        assert compute_trends([{"month": "2026-05", "basic": 50_000}]) == []

    def test_up_down_flat_directions(self):
        snapshots = [
            {"month": "2026-01", "basic": 50_000, "tds": 5_000, "hra": 20_000},
            {"month": "2026-02", "basic": 55_000, "tds": 4_000, "hra": 20_000},
        ]
        trends = {t.field: t for t in compute_trends(snapshots)}
        assert trends["basic"].direction == "up"
        assert trends["tds"].direction == "down"
        assert trends["hra"].direction == "flat"

    def test_first_vs_last_ignores_middle_months(self):
        snapshots = [
            {"month": "2026-01", "basic": 50_000},
            {"month": "2026-02", "basic": 999_000},  # a spike in the middle — must not affect the trend
            {"month": "2026-03", "basic": 52_000},
        ]
        trend = compute_trends(snapshots)[0]
        assert trend.first_value == 50_000
        assert trend.last_value == 52_000
        assert trend.direction == "up"

    def test_missing_field_in_some_snapshots_is_skipped_not_treated_as_zero(self):
        snapshots = [
            {"month": "2026-01", "basic": 50_000},
            {"month": "2026-02"},  # no basic field at all
            {"month": "2026-03", "basic": 52_000},
        ]
        trend = compute_trends(snapshots)[0]
        assert trend.first_month == "2026-01"
        assert trend.last_month == "2026-03"

    def test_bool_is_not_treated_as_a_number(self):
        # isinstance(True, int) is True in Python — _is_number must exclude bools explicitly.
        snapshots = [{"month": "2026-01", "basic": True}, {"month": "2026-02", "basic": 50_000}]
        assert compute_trends(snapshots) == []


class TestBonusSummary:
    def test_no_bonus_months_returns_none(self):
        assert _bonus_summary([{"month": "2026-01", "basic": 50_000}]) is None

    def test_a_mid_period_bonus_is_not_lost(self):
        """The exact scenario the module docstring calls out: a June bonus
        must show up here even though it wouldn't survive a first-vs-last
        trend comparison the way _TREND_FIELDS entries do."""
        snapshots = [
            {"month": "2026-05", "bonus": 0},
            {"month": "2026-06", "bonus": 50_000},
            {"month": "2026-07", "bonus": 0},
        ]
        summary = _bonus_summary(snapshots)
        assert summary is not None
        assert "2026-06" in summary
        assert "₹50,000" in summary
        assert "1 of 3" in summary

    def test_multiple_bonus_months_totaled(self):
        snapshots = [{"month": "2026-03", "bonus": 20_000}, {"month": "2026-09", "bonus": 30_000}]
        summary = _bonus_summary(snapshots)
        assert "₹50,000" in summary  # total
        assert "2 of 2" in summary


class TestDetectDuplicateMonths:
    def test_no_duplicates(self):
        snapshots = [{"month": "2026-01"}, {"month": "2026-02"}]
        assert detect_duplicate_months(snapshots) == []

    def test_finds_duplicate_month(self):
        snapshots = [{"month": "2026-01"}, {"month": "2026-01"}, {"month": "2026-02"}]
        assert detect_duplicate_months(snapshots) == [("2026-01", 2)]

    def test_snapshots_missing_month_key_are_ignored(self):
        snapshots = [{"basic": 50_000}, {"basic": 60_000}]
        assert detect_duplicate_months(snapshots) == []


class TestFormatting:
    def test_format_trends_for_prompt_not_enough_data(self):
        text = format_trends_for_prompt([{"month": "2026-01", "basic": 50_000}])
        assert "not enough" in text

    def test_format_trends_for_prompt_includes_arrow_and_change(self):
        snapshots = [{"month": "2026-01", "basic": 50_000}, {"month": "2026-02", "basic": 55_000}]
        text = format_trends_for_prompt(snapshots)
        assert "↑" in text
        assert "₹5,000" in text

    def test_format_duplicates_for_prompt_none_found(self):
        text = format_duplicates_for_prompt([{"month": "2026-01"}])
        assert "no duplicate months found" in text

    def test_format_duplicates_for_prompt_points_to_ui_not_offering_to_delete(self):
        snapshots = [{"month": "2026-01"}, {"month": "2026-01"}]
        text = format_duplicates_for_prompt(snapshots)
        assert "Remove duplicates" in text
        assert "2026-01 (2 copies)" in text

    def test_trends_table_shape(self):
        snapshots = [{"month": "2026-01", "basic": 50_000}, {"month": "2026-02", "basic": 55_000}]
        table = trends_table(snapshots)
        assert table["headers"] == ["Field", "First", "Last", "Change"]
        assert len(table["rows"]) == 1

    def test_trends_table_none_when_nothing_to_show(self):
        assert trends_table([{"month": "2026-01", "basic": 50_000}]) is None

    def test_duplicates_table_none_when_no_duplicates(self):
        assert duplicates_table([{"month": "2026-01"}]) is None

    def test_duplicates_table_shape(self):
        snapshots = [{"month": "2026-01"}, {"month": "2026-01"}]
        table = duplicates_table(snapshots)
        assert table["headers"] == ["Month", "Saved copies"]
        assert table["rows"] == [["2026-01", "2"]]
