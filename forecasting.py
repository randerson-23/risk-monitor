"""
Forward-looking risk models. Pure functions, no Qt.

Currently provides:
  • GARCH(1,1) volatility forecast with simulation-based prediction intervals
  • NY Fed yield-curve recession probability (probit on 10Y–3M spread)

All inputs are pandas Series of close prices or spreads. All return values
are plain dicts so they pickle cleanly across QThread boundaries.
"""

from __future__ import annotations

import math
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

# arch is heavyweight; import lazily so the dashboard still starts if it's
# missing (the user just won't see the vol cone).
try:
    from arch import arch_model  # type: ignore
    _ARCH_OK = True
except Exception:
    _ARCH_OK = False


# ── GARCH vol forecast ────────────────────────────────────────────────────────

def log_returns(prices: pd.Series) -> pd.Series:
    s = pd.Series(prices).dropna().astype(float)
    if len(s) < 2:
        return pd.Series(dtype=float)
    return np.log(s / s.shift(1)).dropna()


def garch_vol_forecast(
    prices: pd.Series,
    horizon: int = 20,
    p: int = 1,
    q: int = 1,
    dist: str = "t",
    reps: int = 2000,
) -> dict:
    """Fit GARCH(p, q) on percent log-returns; produce both:

      • Vol path: analytic conditional σ_t per step, annualized (%).
        This is the deterministic mean-reverting GARCH vol forecast.
      • Price cone: p5/p25/p75/p95 of simulated cumulative returns,
        expressed as a multiplier of last price. The standard trader
        "cone of uncertainty" — widens with horizon.

    Returns a dict with:
        ok                              : bool
        history_dates / history_vol     : last 90d trailing 21d realized vol (%)
        forecast_dates                  : next `horizon` business days
        vol_median                      : list[float]  (annualized %)
        last_price                      : float
        cone_p5, cone_p25, cone_p75,
        cone_p95, cone_median           : list[float]  (price levels)
        h1, h5, h20                     : float annualized vol forecasts
    """
    if not _ARCH_OK:
        return {"ok": False, "error": "arch package not installed"}

    rets = log_returns(prices)
    if len(rets) < 250:
        return {"ok": False, "error": f"need >=250 returns, have {len(rets)}"}

    pct = rets * 100.0  # arch wants percent returns
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            am = arch_model(pct, mean="Zero", vol="GARCH", p=p, q=q, dist=dist)
            res = am.fit(disp="off", show_warning=False)
            fcast = res.forecast(
                horizon=horizon, method="simulation", simulations=reps
            )
    except Exception as exc:
        return {"ok": False, "error": f"GARCH fit failed: {exc}"}

    ann = math.sqrt(252)

    # Analytic conditional variance forecast → vol path (annualized %)
    var_path = fcast.variance.values[-1]              # (horizon,) in %^2
    vol_path = np.sqrt(var_path) * ann                # (horizon,) in %

    # Simulated paths → cumulative returns → price cone
    sims = fcast.simulations.values[-1]               # (reps, horizon) percent
    cum_log = (sims / 100.0).cumsum(axis=1)           # (reps, horizon)
    price_paths = np.exp(cum_log)                     # multipliers
    last_price = float(prices.dropna().iloc[-1])
    price_paths_abs = price_paths * last_price

    pcts = {q_: np.percentile(price_paths_abs, q_, axis=0) for q_ in (5, 25, 50, 75, 95)}

    last_date = pd.Timestamp(rets.index[-1])
    fdates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=horizon)

    realized = (rets.rolling(21).std() * ann * 100).dropna().tail(90)

    return {
        "ok": True,
        "history_dates": list(realized.index),
        "history_vol":   list(realized.values),
        "forecast_dates": list(fdates),
        "vol_median":  list(vol_path),
        "last_price":  last_price,
        "cone_median": list(pcts[50]),
        "cone_p5":     list(pcts[5]),
        "cone_p25":    list(pcts[25]),
        "cone_p75":    list(pcts[75]),
        "cone_p95":    list(pcts[95]),
        "h1":  float(vol_path[0]),
        "h5":  float(vol_path[min(4, horizon - 1)]),
        "h20": float(vol_path[min(19, horizon - 1)]),
        "fitted_at": datetime.now(),
    }


# ── NY Fed yield-curve recession probability ──────────────────────────────────
#
# Estrella & Mishkin (1998); coefficients re-estimated by the NY Fed monthly.
# Closed-form 12-month-ahead probit with the 10Y minus 3M spread (in %):
#
#     P = Φ( -0.5333  -  0.6330 × spread )
#
# (Coefficients are stable to ~3 decimals across publications. We surface the
# spread used so the UI can show e.g. "12-mo prob: 28%  (spread = 0.42%)").

_NY_FED_INTERCEPT = -0.5333
_NY_FED_SLOPE     = -0.6330


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def ny_fed_recession_prob(spread_pct: float) -> float:
    """12-month-ahead recession probability from 10Y–3M spread (in percentage points)."""
    z = _NY_FED_INTERCEPT + _NY_FED_SLOPE * spread_pct
    return _norm_cdf(z)


def ny_fed_recession_history(spread_series: pd.Series) -> pd.Series:
    """Apply the probit to a series of historical spreads."""
    s = pd.Series(spread_series).dropna().astype(float)
    return s.apply(ny_fed_recession_prob)
