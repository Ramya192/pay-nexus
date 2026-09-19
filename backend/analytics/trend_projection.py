"""
Linear regression trend projection — fits a least-squares line over a
series of (period, value) points and projects it forward.

Deliberately separate from payslip_trends.py's compute_trends and
spending_trends.py's category_period_trends, not a replacement for either:
those answer "is this going up or down overall" from as few as 2 points,
and are explicit about not claiming more precision than that (see
payslip_trends.py's own module docstring: "not a full regression... without
pretending to a precision this data doesn't support"). A linear fit is only
a meaningful upgrade over first-vs-last once there's enough history that
"projection" means something more than connecting two dots — hence
MIN_POINTS_FOR_PROJECTION below.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LinearRegression

# Fewer than this, a "trend line" is just first-vs-last with extra math
# dressing -- return None instead of projecting from noise. 3 is the
# minimum for a line fit to mean anything at all (2 points always fit a
# line perfectly, R² of 1.0, telling you nothing about whether that line
# means anything).
MIN_POINTS_FOR_PROJECTION = 3


@dataclass
class TrendProjection:
    slope_per_period: float  # e.g. rupees of change per period, sign included
    r_squared: float  # 0-1, how well a straight line actually fits the real points
    projected_values: list[float]  # one per period_ahead requested, in order


def project_linear_trend(values: list[float], periods_ahead: int = 3) -> TrendProjection | None:
    """`values` must already be sorted oldest -> newest. Returns None with
    fewer than MIN_POINTS_FOR_PROJECTION points -- not enough to fit a
    meaningful line, same "say so rather than inventing a direction"
    principle payslip_trends.py's compute_trends already uses for its own,
    simpler first-vs-last trend.
    """
    if len(values) < MIN_POINTS_FOR_PROJECTION:
        return None

    X = np.arange(len(values)).reshape(-1, 1)
    y = np.array(values, dtype=float)
    model = LinearRegression()
    model.fit(X, y)

    future_X = np.arange(len(values), len(values) + periods_ahead).reshape(-1, 1)
    projected_values = model.predict(future_X).tolist()

    return TrendProjection(
        slope_per_period=float(model.coef_[0]),
        r_squared=float(model.score(X, y)),
        projected_values=projected_values,
    )
