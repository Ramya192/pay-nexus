"""
Live current-value lookup for investment-linked savings goals (GoalTracker,
V2.1) — closes the gap analytics/goal_progress.py's own module docstring
flagged: "no live price-lookup source is wired in yet."

Two genuinely different kinds of "current value," deliberately not treated
the same way (a real design distinction found while scoping this feature,
not an implementation detail):

- **Fixed deposits have no live price to fetch at all.** An FD's value on
  any given day is fully determined by its principal, rate, and elapsed
  time — there is no market to query, so `fd_current_value` below is pure
  compound-interest math, no network call, always available, always exact.
- **Mutual funds have a real, fluctuating market price** (NAV) that
  genuinely needs a live source. `fetch_mf_nav` calls mfapi.in — a free,
  actively-maintained public API that republishes AMFI's own official daily
  NAV data under a simple per-scheme-code REST endpoint, rather than
  parsing AMFI's own ~30MB raw NAVAll.txt dump directly for one scheme code
  (technically "more official," but disproportionate parsing work for what
  this feature needs). Individual stock price lookup was deliberately
  scoped out (Ramya's call) — mutual funds and FDs cover the real use case.

Both fail gracefully (None / an error string), never raise into the
route — a stale or unreachable price source shouldn't break the whole
Goals tab, just leave that one goal's live value unavailable this time.
"""

from __future__ import annotations

from datetime import date

import httpx

_MFAPI_BASE_URL = "https://api.mfapi.in/mf"
_MFAPI_TIMEOUT_SECONDS = 8.0

# Indian bank FDs are conventionally quarterly-compounded — this is the
# real, standard convention (not an arbitrary choice), matching how banks
# themselves compute FD maturity/current value.
_FD_COMPOUNDS_PER_YEAR = 4


def fd_current_value(
    principal: float, annual_rate_pct: float, start_date: str, today: date | None = None
) -> float:
    """Compound-interest value of a fixed deposit today — no network call,
    always exact, always available. `start_date` is "YYYY-MM-DD". Returns
    `principal` unchanged (0 elapsed time or a malformed/future start_date)
    rather than raising — an FD just opened, or one with a not-yet-valid
    date, is honestly worth exactly its principal so far.
    """
    today = today or date.today()
    try:
        start = date.fromisoformat(start_date)
    except (ValueError, TypeError):
        return principal
    elapsed_days = (today - start).days
    if elapsed_days <= 0:
        return principal
    elapsed_years = elapsed_days / 365.25
    rate = annual_rate_pct / 100
    return principal * (1 + rate / _FD_COMPOUNDS_PER_YEAR) ** (_FD_COMPOUNDS_PER_YEAR * elapsed_years)


def fetch_mf_nav(scheme_code: str) -> tuple[float | None, str | None]:
    """Returns (nav, error) — exactly one is None. A real live HTTP call
    (mfapi.in, see module docstring), so this can genuinely fail: an
    invalid scheme code, the service being unreachable, or a response
    shape that doesn't parse. Every failure mode returns a clear error
    string rather than raising, so one goal's bad scheme code can't break
    the whole valuation request for every other goal in it.
    """
    try:
        response = httpx.get(f"{_MFAPI_BASE_URL}/{scheme_code}/latest", timeout=_MFAPI_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return None, "Couldn't reach the mutual fund price service — try again shortly."

    if response.status_code != 200:
        return None, f"Price service returned an unexpected status ({response.status_code})."

    try:
        payload = response.json()
        nav_str = payload["data"][0]["nav"]
        return float(nav_str), None
    except (KeyError, IndexError, TypeError, ValueError):
        return None, f"No NAV data found for scheme code {scheme_code!r} — check the code is correct."


def mf_current_value(scheme_code: str, units_held: float) -> tuple[float | None, str | None]:
    """units_held x current NAV. Same (value, error) shape as
    fetch_mf_nav — a units-held count of 0 or less is treated as a real
    input error (a goal can't hold negative/zero units) rather than
    silently returning 0.0, which would look identical to "the fund is
    worthless" instead of "this input doesn't make sense."""
    if units_held <= 0:
        return None, "Units held must be a positive number."
    nav, error = fetch_mf_nav(scheme_code)
    if error is not None:
        return None, error
    return nav * units_held, None
