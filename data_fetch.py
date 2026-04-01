"""
Data fetching for all risk metrics.
All functions return dicts; missing data fields are omitted (not None-filled)
so callers should use .get() with a default.
"""

import numpy as np
import requests
import yfinance as yf
from datetime import datetime


# ── Helpers ──────────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0 (risk-monitor/1.0)"}


def _pct_from_ma(series, window=200):
    """Return (current_value, ma_value, pct_diff, is_above_ma)."""
    ma = series.rolling(window).mean().iloc[-1]
    cur = series.iloc[-1]
    return cur, ma, round((cur - ma) / ma * 100, 2), bool(cur > ma)


# ── External APIs ─────────────────────────────────────────────────────────────

def fetch_cnn_fear_greed() -> dict:
    """CNN Fear & Greed Index — current score + 90-day history."""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        payload = r.json()

        current = payload["fear_and_greed"]
        score = round(float(current["score"]), 1)
        rating = current.get("rating", "").replace("_", " ").title()

        # Historical series (list of {x: epoch_ms, y: score})
        hist_raw = payload.get("fear_and_greed_historical", {}).get("data", [])
        if hist_raw:
            import pandas as pd
            hist = pd.Series(
                {datetime.fromtimestamp(pt["x"] / 1000): pt["y"] for pt in hist_raw}
            ).sort_index()
        else:
            hist = None

        return {"score": score, "rating": rating, "history": hist}
    except Exception as exc:
        return {"error": str(exc)}


def fetch_crypto_fear_greed() -> dict:
    """Alternative.me Crypto Fear & Greed."""
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        r.raise_for_status()
        entry = r.json()["data"][0]
        return {
            "score": int(entry["value"]),
            "rating": entry["value_classification"],
        }
    except Exception as exc:
        return {"error": str(exc)}


def fetch_btc_dominance() -> dict:
    """CoinGecko global market data for BTC dominance."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/global",
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        gdata = r.json()["data"]
        return {
            "btc_dominance": round(gdata["market_cap_percentage"]["btc"], 2),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Equity ────────────────────────────────────────────────────────────────────

def fetch_equity_data() -> dict:
    result: dict = {}

    # VIX
    try:
        hist = yf.Ticker("^VIX").history(period="6mo")["Close"].dropna()
        if not hist.empty:
            result["vix"] = round(hist.iloc[-1], 2)
            result["vix_prev"] = round(hist.iloc[-2], 2) if len(hist) > 1 else result["vix"]
            result["vix_hist"] = hist
    except Exception:
        pass

    # S&P 500
    try:
        hist = yf.Ticker("^GSPC").history(period="1y")["Close"].dropna()
        if not hist.empty:
            cur, ma, pct, above = _pct_from_ma(hist)
            result["spx"] = round(cur, 2)
            result["spx_ma200"] = round(ma, 2)
            result["spx_above_200ma"] = above
            result["spx_pct_from_200ma"] = pct
            result["spx_hist"] = hist
    except Exception:
        pass

    # SKEW
    try:
        hist = yf.Ticker("^SKEW").history(period="6mo")["Close"].dropna()
        if not hist.empty:
            result["skew"] = round(hist.iloc[-1], 2)
            result["skew_hist"] = hist
    except Exception:
        pass

    # Market breadth: % NYSE stocks above 200 MA
    # ^NY200R is the NYSE percentage above 200MA index
    for ticker in ("^NY200R", "MMTH"):
        try:
            hist = yf.Ticker(ticker).history(period="6mo")["Close"].dropna()
            if not hist.empty:
                result["breadth_pct"] = round(hist.iloc[-1], 2)
                result["breadth_hist"] = hist
                break
        except Exception:
            continue

    # Put/Call ratio derived from SPY nearest-expiry options
    try:
        spy = yf.Ticker("SPY")
        exps = spy.options
        if exps:
            chain = spy.option_chain(exps[0])
            put_vol = chain.puts["volume"].dropna().sum()
            call_vol = chain.calls["volume"].dropna().sum()
            if call_vol > 0:
                result["put_call_ratio"] = round(float(put_vol) / float(call_vol), 3)
    except Exception:
        pass

    # CNN Fear & Greed
    cnn = fetch_cnn_fear_greed()
    if "score" in cnn:
        result["cnn_fear_greed"] = cnn["score"]
        result["cnn_fear_greed_rating"] = cnn["rating"]
    if "history" in cnn and cnn["history"] is not None:
        result["cnn_fg_hist"] = cnn["history"]

    result["timestamp"] = datetime.now()
    return result


# ── Crypto ────────────────────────────────────────────────────────────────────

def fetch_crypto_data() -> dict:
    result: dict = {}

    # BTC
    try:
        hist = yf.Ticker("BTC-USD").history(period="1y")["Close"].dropna()
        if not hist.empty:
            cur, ma, pct, above = _pct_from_ma(hist)
            result["btc_price"] = round(cur, 2)
            result["btc_ma200"] = round(ma, 2)
            result["btc_above_200ma"] = above
            result["btc_pct_from_200ma"] = pct
            result["btc_hist"] = hist

            daily_ret = hist.pct_change().dropna()
            rv30 = float(daily_ret.tail(30).std() * np.sqrt(365) * 100)
            result["btc_rv30"] = round(rv30, 2)
            result["rv30_hist"] = (
                daily_ret.rolling(30).std() * np.sqrt(365) * 100
            ).dropna()
    except Exception:
        pass

    # ETH + ETH/BTC ratio
    try:
        eth_hist = yf.Ticker("ETH-USD").history(period="6mo")["Close"].dropna()
        if not eth_hist.empty:
            result["eth_price"] = round(eth_hist.iloc[-1], 2)

        btc_hist_short = yf.Ticker("BTC-USD").history(period="6mo")["Close"].dropna()
        if not eth_hist.empty and not btc_hist_short.empty:
            ratio = eth_hist / btc_hist_short
            ratio = ratio.dropna()
            result["eth_btc_ratio"] = round(float(ratio.iloc[-1]), 6)
            result["eth_btc_hist"] = ratio
    except Exception:
        pass

    # BTC Dominance (CoinGecko)
    dom_data = fetch_btc_dominance()
    if "btc_dominance" in dom_data:
        result["btc_dominance"] = dom_data["btc_dominance"]

    # Crypto Fear & Greed (Alternative.me)
    cfg = fetch_crypto_fear_greed()
    if "score" in cfg:
        result["crypto_fear_greed"] = cfg["score"]
        result["crypto_fear_greed_rating"] = cfg["rating"]

    result["timestamp"] = datetime.now()
    return result
