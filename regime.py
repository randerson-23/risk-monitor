"""
Regime classification logic for equity and crypto markets.

Scoring ranges:
  Equity: -8 to +8  →  >= +3 Risk-On, <= -2 Risk-Off, else Neutral
  Crypto: -6 to +6  →  >= +2 Risk-On, <= -2 Risk-Off, else Neutral
"""

RISK_ON = "RISK-ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK-OFF"

REGIME_COLORS = {
    RISK_ON:  "#3fb950",
    NEUTRAL:  "#d29922",
    RISK_OFF: "#f85149",
}


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

    # Market breadth: % stocks above 200 MA  (-1 to +1)
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
    # High dominance = capital rotating into BTC safety, risk-off for alts
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

    if score >= 2:
        regime = RISK_ON
    elif score <= -2:
        regime = RISK_OFF
    else:
        regime = NEUTRAL

    return {"regime": regime, "score": score, "color": REGIME_COLORS[regime], "factors": factors}
