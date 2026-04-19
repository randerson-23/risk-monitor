"""
Regime classification logic for equity, crypto, and macro markets.

Scoring ranges:
  Equity: -8 to +8  →  >= +3 Risk-On, <= -2 Risk-Off, else Neutral
  Crypto: -6 to +6  →  >= +2 Risk-On, <= -2 Risk-Off, else Neutral
  Macro:  -7 to +7  →  >= +2 Risk-On, <= -2 Risk-Off, else Neutral
"""

from datetime import datetime

import numpy as np
import pandas as pd

RISK_ON = "RISK-ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK-OFF"

REGIME_COLORS = {
    RISK_ON:  "#3fb950",
    NEUTRAL:  "#d29922",
    RISK_OFF: "#f85149",
}


_HALVINGS = [
    datetime(2012, 11, 28), datetime(2016, 7,  9),
    datetime(2020, 5,  11), datetime(2024, 4, 19),
    datetime(2028, 4,  15),   # estimated
]

def _btc_cycle() -> tuple[int, str, float]:
    """Return (score, phase_name, progress_0_to_1) from 4-year halving cycle."""
    now  = datetime.now()
    past   = [h for h in _HALVINGS if h <= now]
    future = [h for h in _HALVINGS if h > now]
    if not past or not future:
        return 0, "UNKNOWN", 0.0
    last, nxt = past[-1], future[0]
    progress  = min(1.0, (now - last).days / (nxt - last).days)
    if   progress < 0.08: return +2, "POST-HALVING", progress
    elif progress < 0.38: return +1, "BULL RUN",     progress
    elif progress < 0.48: return -1, "PEAK ZONE",    progress
    elif progress < 0.87: return -2, "BEAR MARKET",  progress
    else:                 return +1, "PRE-HALVING",  progress


def compute_equity_regime(data: dict) -> dict:
    score = 0
    factors = []

    # VIX  (-2 to +2)
    vix = data.get("vix")
    if vix is not None:
        if vix < 15:
            score += 2; factors.append(f"VIX {vix:.1f} — calm (+2)")
        elif vix < 20:
            score += 1; factors.append(f"VIX {vix:.1f} — normal (+1)")
        elif vix < 25:
            score -= 1; factors.append(f"VIX {vix:.1f} — elevated (−1)")
        elif vix < 30:
            score -= 1; factors.append(f"VIX {vix:.1f} — high (−1)")
        else:
            score -= 2; factors.append(f"VIX {vix:.1f} — extreme fear (−2)")

    # SPX vs 200 MA  (-1 to +1)
    spx_above = data.get("spx_above_200ma")
    if spx_above is not None:
        if spx_above:
            score += 1; factors.append("SPX above 200 MA (+1)")
        else:
            score -= 1; factors.append("SPX below 200 MA (−1)")

    # Put/Call ratio  (-1 to +1)
    pc = data.get("put_call_ratio")
    if pc is not None:
        if pc < 0.7:
            score += 1; factors.append(f"P/C {pc:.2f} — complacent (+1)")
        elif pc > 1.0:
            score -= 1; factors.append(f"P/C {pc:.2f} — protective (−1)")
        else:
            factors.append(f"P/C {pc:.2f} — neutral (0)")

    # Market breadth  (-1 to +1)
    breadth = data.get("breadth_pct")
    if breadth is not None:
        if breadth > 60:
            score += 1; factors.append(f"Breadth {breadth:.1f}% (+1)")
        elif breadth < 40:
            score -= 1; factors.append(f"Breadth {breadth:.1f}% (−1)")
        else:
            factors.append(f"Breadth {breadth:.1f}% (0)")

    # CNN Fear & Greed  (-1 to +1)
    fg = data.get("cnn_fear_greed")
    if fg is not None:
        if fg > 65:
            score += 1; factors.append(f"CNN F&G {fg:.0f} — greed (+1)")
        elif fg < 35:
            score -= 1; factors.append(f"CNN F&G {fg:.0f} — fear (−1)")
        else:
            factors.append(f"CNN F&G {fg:.0f} — neutral (0)")

    # SKEW  (-1 to +1)
    skew = data.get("skew")
    if skew is not None:
        if skew > 145:
            score -= 1; factors.append(f"SKEW {skew:.1f} — elevated tail risk (−1)")
        elif skew < 120:
            score += 1; factors.append(f"SKEW {skew:.1f} — low tail risk (+1)")
        else:
            factors.append(f"SKEW {skew:.1f} — normal (0)")

    if score >= 3:
        regime = RISK_ON
    elif score <= -2:
        regime = RISK_OFF
    else:
        regime = NEUTRAL

    return {"regime": regime, "score": score, "color": REGIME_COLORS[regime], "factors": factors}


def compute_crypto_regime(data: dict) -> dict:
    score = 0
    factors = []

    # Crypto Fear & Greed  (-2 to +2)
    fg = data.get("crypto_fear_greed")
    if fg is not None:
        if fg >= 75:
            score += 2; factors.append(f"F&G {fg} — extreme greed (+2)")
        elif fg >= 55:
            score += 1; factors.append(f"F&G {fg} — greed (+1)")
        elif fg <= 25:
            score -= 2; factors.append(f"F&G {fg} — extreme fear (−2)")
        elif fg <= 45:
            score -= 1; factors.append(f"F&G {fg} — fear (−1)")
        else:
            factors.append(f"F&G {fg} — neutral (0)")

    # BTC vs 200 MA  (-1 to +1)
    btc_above = data.get("btc_above_200ma")
    if btc_above is not None:
        if btc_above:
            score += 1; factors.append("BTC above 200 MA (+1)")
        else:
            score -= 1; factors.append("BTC below 200 MA (−1)")

    # BTC Dominance  (-1 to +1)
    dom = data.get("btc_dominance")
    if dom is not None:
        if dom > 58:
            score -= 1; factors.append(f"BTC Dom {dom:.1f}% — high, risk-off alts (−1)")
        elif dom < 45:
            score += 1; factors.append(f"BTC Dom {dom:.1f}% — low, alt season (+1)")
        else:
            factors.append(f"BTC Dom {dom:.1f}% — neutral (0)")

    # 30-day Realized Volatility  (-1 to +1)
    rv = data.get("btc_rv30")
    if rv is not None:
        if rv > 80:
            score -= 1; factors.append(f"RV30 {rv:.1f}% — extreme (−1)")
        elif rv < 40:
            score += 1; factors.append(f"RV30 {rv:.1f}% — calm (+1)")
        else:
            factors.append(f"RV30 {rv:.1f}% — normal (0)")

    # BTC 200-week MA  (-1 to +1)
    btc_above_wma = data.get("btc_above_wma200")
    if btc_above_wma is not None:
        if btc_above_wma:
            score += 1; factors.append("BTC above 200-week MA (+1)")
        else:
            score -= 1; factors.append("BTC below 200-week MA (−1)")

    # ATH distance  (−2 to +2)
    pct_ath = data.get("btc_pct_from_ath")
    if pct_ath is not None:
        if pct_ath < -60:
            score += 2; factors.append(f"BTC {pct_ath:.0f}% from ATH — deep value (+2)")
        elif pct_ath < -35:
            score += 1; factors.append(f"BTC {pct_ath:.0f}% from ATH — undervalued (+1)")
        elif pct_ath > -10:
            score -= 1; factors.append(f"BTC {pct_ath:.0f}% from ATH — near top (−1)")
        else:
            factors.append(f"BTC {pct_ath:.0f}% from ATH (0)")

    # Pi Cycle Top  (0 to −2)
    pi_ratio = data.get("btc_pi_ratio")
    if pi_ratio is not None:
        if pi_ratio >= 0.97:
            score -= 2; factors.append(f"Pi Cycle {pi_ratio:.3f} — top warning (−2)")
        elif pi_ratio >= 0.90:
            score -= 1; factors.append(f"Pi Cycle {pi_ratio:.3f} — approaching top (−1)")
        else:
            factors.append(f"Pi Cycle {pi_ratio:.3f} — safe (0)")

    # 90-day momentum  (−1 to +1)
    mom90 = data.get("btc_mom90")
    if mom90 is not None:
        if mom90 > 20:
            score += 1; factors.append(f"90d momentum {mom90:+.0f}% — strong (+1)")
        elif mom90 < -20:
            score -= 1; factors.append(f"90d momentum {mom90:+.0f}% — weak (−1)")
        else:
            factors.append(f"90d momentum {mom90:+.0f}% (0)")

    # 4-year halving cycle  (−2 to +2)
    cyc_score, cyc_phase, _ = _btc_cycle()
    score += cyc_score
    factors.append(f"4Y cycle: {cyc_phase} ({cyc_score:+d})")

    # Funding rate sentiment  (−1 to +1)
    funding_avg = data.get("funding_rate_avg24h")
    if funding_avg is not None:
        if funding_avg < -0.01:
            score += 1; factors.append(f"Funding {funding_avg:.4f}% — bearish positioning (+1)")
        elif funding_avg > 0.05:
            score -= 1; factors.append(f"Funding {funding_avg:.4f}% — overleveraged longs (−1)")
        else:
            factors.append(f"Funding {funding_avg:.4f}% — neutral (0)")

    # Long/Short ratio  (−1 to +1)
    ls = data.get("ls_ratio")
    if ls is not None:
        if ls < 0.9:
            score += 1; factors.append(f"L/S {ls:.2f} — short-heavy (+1)")
        elif ls > 1.2:
            score -= 1; factors.append(f"L/S {ls:.2f} — long-crowded (−1)")
        else:
            factors.append(f"L/S {ls:.2f} — balanced (0)")

    # Open interest trend  (−1 to +1)
    oi_chg = data.get("oi_pct_change_30d")
    if oi_chg is not None and mom90 is not None:
        if oi_chg > 20 and mom90 > 0:
            score += 1; factors.append(f"OI +{oi_chg:.0f}% / price rising — trend strength (+1)")
        elif oi_chg > 20 and mom90 < 0:
            score -= 1; factors.append(f"OI +{oi_chg:.0f}% / price falling — bearish divergence (−1)")
        elif oi_chg < -20:
            score -= 1; factors.append(f"OI {oi_chg:.0f}% — deleveraging (−1)")
        else:
            factors.append(f"OI {oi_chg:+.0f}% — neutral (0)")

    # Hash rate trend  (−1 to +1)
    hr_chg = data.get("hash_rate_pct_30d")
    if hr_chg is not None:
        if hr_chg > 0:
            score += 1; factors.append(f"Hash rate +{hr_chg:.1f}% (30d) — network strength (+1)")
        elif hr_chg < -10:
            score -= 1; factors.append(f"Hash rate {hr_chg:.1f}% (30d) — miner stress (−1)")
        else:
            factors.append(f"Hash rate {hr_chg:.1f}% — stable (0)")

    # MVRV  (−2 to +2)
    mvrv = data.get("mvrv")
    if mvrv is not None:
        if mvrv < 1.0:
            score += 2; factors.append(f"MVRV {mvrv:.2f} — below realized price, deep value (+2)")
        elif mvrv < 1.5:
            score += 1; factors.append(f"MVRV {mvrv:.2f} — fair value (+1)")
        elif mvrv < 3.0:
            factors.append(f"MVRV {mvrv:.2f} — elevated, monitor (0)")
        elif mvrv < 4.0:
            score -= 1; factors.append(f"MVRV {mvrv:.2f} — historically high (−1)")
        else:
            score -= 2; factors.append(f"MVRV {mvrv:.2f} — bubble territory (−2)")

    # Fed Net Liquidity trend  (−1 to +1)
    liq_chg = data.get("net_liquidity_change_30d")
    if liq_chg is not None:
        if liq_chg > 2.0:
            score += 1; factors.append(f"Net Liquidity +{liq_chg:.1f}% (30d) — expanding (+1)")
        elif liq_chg < -2.0:
            score -= 1; factors.append(f"Net Liquidity {liq_chg:.1f}% (30d) — contracting (−1)")
        else:
            factors.append(f"Net Liquidity {liq_chg:+.1f}% — stable (0)")

    if score >= 2:
        regime = RISK_ON
    elif score <= -2:
        regime = RISK_OFF
    else:
        regime = NEUTRAL

    return {"regime": regime, "score": score, "color": REGIME_COLORS[regime], "factors": factors}


def compute_macro_regime(data: dict) -> dict:
    score = 0
    factors = []

    # Yield curve (10Y − 3M)  (−2 to +2)
    spread = data.get("yield_spread")
    if spread is not None:
        if spread < 0:
            score -= 2; factors.append(f"Yield curve inverted ({spread:+.2f}%) (−2)")
        elif spread < 0.5:
            score -= 1; factors.append(f"Yield curve flat ({spread:+.2f}%) (−1)")
        elif spread > 1.5:
            score += 2; factors.append(f"Yield curve steep ({spread:+.2f}%) (+2)")
        else:
            score += 1; factors.append(f"Yield curve normal ({spread:+.2f}%) (+1)")

    # 10Y yield level  (−1 to +1)
    y10 = data.get("yield_10y")
    if y10 is not None:
        if y10 > 5.0:
            score -= 1; factors.append(f"10Y {y10:.2f}% — tight conditions (−1)")
        elif y10 < 3.5:
            score += 1; factors.append(f"10Y {y10:.2f}% — accommodative (+1)")
        else:
            factors.append(f"10Y {y10:.2f}% — neutral (0)")

    # DXY vs 200MA  (−1 to +1)
    dxy_above = data.get("dxy_above_200ma")
    if dxy_above is not None:
        if dxy_above:
            score -= 1; factors.append("DXY above 200MA — strong dollar (−1)")
        else:
            score += 1; factors.append("DXY below 200MA — weak dollar (+1)")

    # Oil vs 200MA  (−1 to +1)
    oil_above = data.get("oil_above_200ma")
    if oil_above is not None:
        if oil_above:
            score += 1; factors.append("Oil above 200MA — growth signal (+1)")
        else:
            score -= 1; factors.append("Oil below 200MA — demand weakness (−1)")

    # HYG vs 200MA  (−1 to +1)
    hyg_above = data.get("hyg_above_200ma")
    if hyg_above is not None:
        if hyg_above:
            score += 1; factors.append("HYG above 200MA — credit healthy (+1)")
        else:
            score -= 1; factors.append("HYG below 200MA — credit stress (−1)")

    # STLFSI4  (−2 to +1)
    stlfsi = data.get("stlfsi")
    if stlfsi is not None:
        if stlfsi > 1.0:
            score -= 2; factors.append(f"STLFSI {stlfsi:.2f} — high stress (−2)")
        elif stlfsi > 0:
            score -= 1; factors.append(f"STLFSI {stlfsi:.2f} — elevated stress (−1)")
        elif stlfsi < -0.5:
            score += 1; factors.append(f"STLFSI {stlfsi:.2f} — below-avg stress (+1)")
        else:
            factors.append(f"STLFSI {stlfsi:.2f} — normal (0)")

    # MOVE Index  (−1 to +1) — bond market volatility
    move = data.get("move")
    if move is not None:
        if move > 130:
            score -= 1; factors.append(f"MOVE {move:.0f} — high bond vol (−1)")
        elif move < 80:
            score += 1; factors.append(f"MOVE {move:.0f} — calm bond market (+1)")
        else:
            factors.append(f"MOVE {move:.0f} — normal bond vol (0)")

    # HY Credit Spread  (−1 to +1) — BofA US HY OAS
    hy_spread = data.get("hy_spread")
    if hy_spread is not None:
        if hy_spread > 5.0:
            score -= 1; factors.append(f"HY Spread {hy_spread:.2f}% — credit stress (−1)")
        elif hy_spread < 3.0:
            score += 1; factors.append(f"HY Spread {hy_spread:.2f}% — risk appetite (+1)")
        else:
            factors.append(f"HY Spread {hy_spread:.2f}% — normal (0)")

    # Chicago Fed NFCI (forward-looking financial conditions; weekly z-score)
    nfci = data.get("nfci")
    if nfci is not None:
        if nfci > 0.5:
            score -= 1; factors.append(f"NFCI {nfci:+.2f} — tight financial conditions (−1)")
        elif nfci < -0.5:
            score += 1; factors.append(f"NFCI {nfci:+.2f} — loose financial conditions (+1)")
        else:
            factors.append(f"NFCI {nfci:+.2f} — neutral (0)")

    # NY Fed yield-curve recession probability (12-mo ahead, %)
    ny_prob = data.get("ny_fed_recession_pct")
    if ny_prob is not None:
        if ny_prob > 60:
            score -= 2; factors.append(f"NY Fed recession prob {ny_prob:.0f}% — high (−2)")
        elif ny_prob > 40:
            score -= 1; factors.append(f"NY Fed recession prob {ny_prob:.0f}% — elevated (−1)")
        else:
            factors.append(f"NY Fed recession prob {ny_prob:.0f}% — low (0)")

    if score >= 2:
        regime = RISK_ON
    elif score <= -2:
        regime = RISK_OFF
    else:
        regime = NEUTRAL

    return {"regime": regime, "score": score, "color": REGIME_COLORS[regime], "factors": factors}


# ── Historical regime helpers ──────────────────────────────────────────────────

def _normalize_index(series: pd.Series) -> pd.Series:
    """Strip timezone and normalize to midnight so series can be aligned."""
    idx = pd.to_datetime(series.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return series.set_axis(idx.normalize())


def compute_equity_regime_history(data: dict) -> pd.Series:
    """Return a daily Series of regime labels computed from historical equity data."""
    parts = {}

    vix = data.get("vix_hist")
    if vix is not None and not vix.empty:
        parts["vix"] = _normalize_index(vix)

    spx = data.get("spx_hist")
    if spx is not None and not spx.empty:
        s = _normalize_index(spx)
        parts["spx_above"] = (s > s.rolling(200).mean()).astype(float)

    skew = data.get("skew_hist")
    if skew is not None and not skew.empty:
        parts["skew"] = _normalize_index(skew)

    breadth = data.get("breadth_hist")
    if breadth is not None and not breadth.empty:
        parts["breadth"] = _normalize_index(breadth)

    cnn = data.get("cnn_fg_hist")
    if cnn is not None and not cnn.empty:
        parts["cnn_fg"] = _normalize_index(cnn)

    if not parts:
        return pd.Series(dtype=object)

    df = pd.DataFrame(parts)
    labels = []

    for _, row in df.iterrows():
        score = 0
        n = 0

        if "vix" in df.columns and pd.notna(row["vix"]):
            n += 1
            v = row["vix"]
            if v < 15:       score += 2
            elif v < 20:     score += 1
            elif v < 25:     score -= 1
            elif v < 30:     score -= 1
            else:            score -= 2

        if "spx_above" in df.columns and pd.notna(row["spx_above"]):
            n += 1
            score += 1 if row["spx_above"] else -1

        if "skew" in df.columns and pd.notna(row["skew"]):
            n += 1
            s = row["skew"]
            if s > 145:   score -= 1
            elif s < 120: score += 1

        if "breadth" in df.columns and pd.notna(row["breadth"]):
            n += 1
            b = row["breadth"]
            if b > 60:   score += 1
            elif b < 40: score -= 1

        if "cnn_fg" in df.columns and pd.notna(row["cnn_fg"]):
            n += 1
            fg = row["cnn_fg"]
            if fg > 65:   score += 1
            elif fg < 35: score -= 1

        if n == 0:
            labels.append(None)
        elif score >= 3:
            labels.append(RISK_ON)
        elif score <= -2:
            labels.append(RISK_OFF)
        else:
            labels.append(NEUTRAL)

    return pd.Series(labels, index=df.index)


def compute_crypto_regime_history(data: dict) -> pd.Series:
    """Return a daily Series of regime labels computed from historical crypto data."""
    parts = {}

    btc = data.get("btc_hist")
    if btc is not None and not btc.empty:
        s = _normalize_index(btc)
        parts["btc_above"] = (s > s.rolling(200).mean()).astype(float)
        daily_ret = s.pct_change()
        parts["rv30"] = daily_ret.rolling(30).std() * np.sqrt(365) * 100

    if not parts:
        return pd.Series(dtype=object)

    df = pd.DataFrame(parts)
    labels = []

    for _, row in df.iterrows():
        score = 0
        n = 0

        if "btc_above" in df.columns and pd.notna(row["btc_above"]):
            n += 1
            score += 1 if row["btc_above"] else -1

        if "rv30" in df.columns and pd.notna(row["rv30"]):
            n += 1
            rv = row["rv30"]
            if rv > 80:   score -= 1
            elif rv < 40: score += 1

        if n == 0:
            labels.append(None)
        elif score >= 2:
            labels.append(RISK_ON)
        elif score <= -2:
            labels.append(RISK_OFF)
        else:
            labels.append(NEUTRAL)

    return pd.Series(labels, index=df.index)


def compute_macro_regime_history(data: dict) -> pd.Series:
    """Return a daily Series of regime labels computed from historical macro data."""
    parts = {}

    y10_hist = data.get("yield_10y_hist")
    y3m_hist = data.get("yield_3m_hist")
    if y10_hist is not None and not y10_hist.empty and y3m_hist is not None and not y3m_hist.empty:
        y10_n = _normalize_index(y10_hist)
        y3m_n = _normalize_index(y3m_hist)
        parts["spread"] = y10_n - y3m_n
        parts["yield_10y"] = y10_n

    dxy = data.get("dxy_hist")
    if dxy is not None and not dxy.empty:
        s = _normalize_index(dxy)
        parts["dxy_above"] = (s > s.rolling(200).mean()).astype(float)

    oil = data.get("oil_hist")
    if oil is not None and not oil.empty:
        s = _normalize_index(oil)
        parts["oil_above"] = (s > s.rolling(200).mean()).astype(float)

    hyg = data.get("hyg_hist")
    if hyg is not None and not hyg.empty:
        s = _normalize_index(hyg)
        parts["hyg_above"] = (s > s.rolling(200).mean()).astype(float)

    stlfsi = data.get("stlfsi_hist")
    if stlfsi is not None and not stlfsi.empty:
        parts["stlfsi"] = _normalize_index(stlfsi)

    move = data.get("move_hist")
    if move is not None and not move.empty:
        parts["move"] = _normalize_index(move)

    hy_spread = data.get("hy_spread_hist")
    if hy_spread is not None and not hy_spread.empty:
        parts["hy_spread"] = _normalize_index(hy_spread)

    if not parts:
        return pd.Series(dtype=object)

    df = pd.DataFrame(parts)
    labels = []

    for _, row in df.iterrows():
        score = 0
        n = 0

        if "spread" in df.columns and pd.notna(row["spread"]):
            n += 1
            sp = row["spread"]
            if sp < 0:       score -= 2
            elif sp < 0.5:   score -= 1
            elif sp > 1.5:   score += 2
            else:            score += 1

        if "yield_10y" in df.columns and pd.notna(row["yield_10y"]):
            n += 1
            y = row["yield_10y"]
            if y > 5.0:   score -= 1
            elif y < 3.5: score += 1

        if "dxy_above" in df.columns and pd.notna(row["dxy_above"]):
            n += 1
            if row["dxy_above"]: score -= 1
            else:                score += 1

        if "oil_above" in df.columns and pd.notna(row["oil_above"]):
            n += 1
            if row["oil_above"]: score += 1
            else:                score -= 1

        if "hyg_above" in df.columns and pd.notna(row["hyg_above"]):
            n += 1
            if row["hyg_above"]: score += 1
            else:                score -= 1

        if "stlfsi" in df.columns and pd.notna(row["stlfsi"]):
            n += 1
            s = row["stlfsi"]
            if s > 1.0:    score -= 2
            elif s > 0:    score -= 1
            elif s < -0.5: score += 1

        if "move" in df.columns and pd.notna(row["move"]):
            n += 1
            m = row["move"]
            if m > 130:   score -= 1
            elif m < 80:  score += 1

        if "hy_spread" in df.columns and pd.notna(row["hy_spread"]):
            n += 1
            h = row["hy_spread"]
            if h > 5.0:   score -= 1
            elif h < 3.0: score += 1

        if n == 0:
            labels.append(None)
        elif score >= 2:
            labels.append(RISK_ON)
        elif score <= -2:
            labels.append(RISK_OFF)
        else:
            labels.append(NEUTRAL)

    return pd.Series(labels, index=df.index)


def compute_sector_rotation_regime(data: dict) -> dict:
    """Return regime card dict for the sector rotation regime."""
    rot = data.get("rotation_regime", "MIXED")
    color_map = {
        "OFFENSIVE": REGIME_COLORS[RISK_ON],
        "MIXED":     REGIME_COLORS[NEUTRAL],
        "DEFENSIVE": REGIME_COLORS[RISK_OFF],
    }
    score_map = {"OFFENSIVE": +1, "MIXED": 0, "DEFENSIVE": -1}
    sorted_t = data.get("sorted_by_rs", [])
    factors = []
    if sorted_t:
        factors.append(f"Top: {', '.join(sorted_t[:3])}")
        factors.append(f"Weak: {', '.join(list(reversed(sorted_t[-3:])))}")
    improving = [t for t, d in data.get("sectors", {}).items() if d.get("quadrant") == "Improving"]
    if improving:
        factors.append(f"Improving: {', '.join(improving)}")
    return {
        "regime":  rot,
        "color":   color_map.get(rot, REGIME_COLORS[NEUTRAL]),
        "score":   score_map.get(rot, 0),
        "factors": factors,
    }
