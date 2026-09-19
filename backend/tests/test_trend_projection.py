"""analytics/trend_projection.py — pure math, no LLM/network, no DB."""

from analytics.trend_projection import MIN_POINTS_FOR_PROJECTION, project_linear_trend


class TestProjectLinearTrend:
    def test_too_few_points_returns_none(self):
        assert project_linear_trend([100.0, 200.0]) is None
        assert MIN_POINTS_FOR_PROJECTION == 3  # documents the actual threshold this test relies on

    def test_perfectly_linear_data_projects_exactly(self):
        # 100, 200, 300, 400 -- slope of exactly 100/period, no noise at all.
        result = project_linear_trend([100.0, 200.0, 300.0, 400.0], periods_ahead=2)
        assert result is not None
        assert result.slope_per_period == 100.0
        assert result.r_squared > 0.999
        assert result.projected_values == [500.0, 600.0]

    def test_flat_data_projects_a_flat_line(self):
        result = project_linear_trend([500.0, 500.0, 500.0, 500.0], periods_ahead=1)
        assert result is not None
        assert abs(result.slope_per_period) < 1e-9
        assert result.projected_values[0] == 500.0

    def test_declining_trend_has_negative_slope(self):
        result = project_linear_trend([1000.0, 800.0, 600.0], periods_ahead=1)
        assert result is not None
        assert result.slope_per_period < 0
        assert result.projected_values[0] < 600.0

    def test_noisy_data_has_a_lower_r_squared_than_perfectly_linear_data(self):
        """Real proof the R² number means something -- not just present in
        the dataclass, actually reflects fit quality."""
        clean = project_linear_trend([100.0, 200.0, 300.0, 400.0])
        noisy = project_linear_trend([100.0, 350.0, 120.0, 380.0])
        assert clean is not None and noisy is not None
        assert clean.r_squared > noisy.r_squared

    def test_default_projects_three_periods_ahead(self):
        result = project_linear_trend([100.0, 200.0, 300.0])
        assert result is not None
        assert len(result.projected_values) == 3
