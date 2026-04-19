"""
Data fetching for all risk metrics.
All functions return dicts; missing data fields are omitted (not None-filled)
so callers should use .get() with a default.
"""

import math
import os
import numpy as np
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
CMC_API_KEY = os.getenv("CMC_API_KEY", "")

# ── Helpers ──────────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0 (risk-monitor/1.0)"}


def _pct_from_ma(series, window=200):
    """Return (current_value, ma_value, pct_diff, is_above_ma)."""
    ma = series.rolling(window).mean().iloc[-1]
    cur = series.iloc[-1]
    return cur, ma, round((cur - ma) / ma * 100, 2), bool(cur > ma)


def _ewma_vol_forecast(returns: pd.Series, lam: float = 0.94,
                       periods_per_year: int = 252) -> float | None:
    """
    RiskMetrics-style EWMA volatility forecast (annualized %).
    Returns None if insufficient data.
    """
    r = returns.dropna()
    if len(r) < 30:
        return None
    # Seed variance with the sample variance, then apply EWMA recursion
    var = float(r.var())
    for val in r:
        var = lam * var + (1.0 - lam) * float(val) ** 2
    if var <= 0:
        return None
    return float(math.sqrt(var) * math.sqrt(periods_per_year) * 100.0)


def _norm_cdf(z: float) -> float:
    """Standard-normal CDF using math.erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _fetch_fred_series(series_id: str, start: str = "2000-01-01") -> pd.Series:
    """Fetch a FRED time series using the API key from .env."""
    if not FRED_API_KEY:
        return pd.Series(dtype=float)
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "asc",
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        data = {
            pd.Timestamp(o["date"]): float(o["value"])
            for o in obs if o["value"] != "."
        }
        return pd.Series(data).sort_index()
    except Exception:
        return pd.Series(dtype=float)


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

        hist_raw = payload.get("fear_and_greed_historical", {}).get("data", [])
        if hist_raw:
            hist = pd.Series(
                {datetime.fromtimestamp(pt["x"] / 1000): pt["y"] for pt in hist_raw}
            ).sort_index()
        else:
            hist = None

        return {"score": score, "rating": rating, "history": hist}
    except Exception as exc:
        return {"error": str(exc)}


def fetch_crypto_fear_greed() -> dict:
    """CoinMarketCap Crypto Fear & Greed Index."""
    cmc_headers = dict(_HEADERS)
    if CMC_API_KEY:
        cmc_headers["X-CMC_PRO_API_KEY"] = CMC_API_KEY

    try:
        r = requests.get(
            "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest",
            headers=cmc_headers,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        score = int(data.get("value", 0))
        rating = data.get("value_classification", "")
        return {"score": score, "rating": rating}
    except Exception:
        # Fallback: try the historical endpoint with limit=1
        try:
            r = requests.get(
                "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical",
                params={"limit": 1},
                headers=cmc_headers,
                timeout=10,
            )
            r.raise_for_status()
            entries = r.json().get("data", [])
            if entries:
                entry = entries[0]
                return {
                    "score": int(entry.get("value", 0)),
                    "rating": entry.get("value_classification", ""),
                }
        except Exception:
            pass
        # Second fallback: Alternative.me
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

            # SPX vol forecast: EWMA (RiskMetrics λ=0.94), annualized %
            rets = np.log(hist / hist.shift(1)).dropna()
            fcst = _ewma_vol_forecast(rets, lam=0.94, periods_per_year=252)
            if fcst is not None:
                result["spx_vol_forecast"] = round(fcst, 2)
            # 21-day realized vol for context
            if len(rets) >= 21:
                rv21 = float(rets.tail(21).std() * math.sqrt(252) * 100.0)
                result["spx_rv21"] = round(rv21, 2)
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

    # Market breadth: % of representative basket above 200-day MA
    _BREADTH_BASKET = [
        "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "BRK-B", "LLY",
        "AVGO", "JPM", "XOM", "UNH", "TSLA", "V",   "PG",  "MA",  "JNJ",
        "HD",   "MRK",  "ABBV", "CVX",  "KO",  "PEP", "BAC", "WMT",
    ]
    try:
        raw = yf.download(
            _BREADTH_BASKET, period="1y", progress=False, auto_adjust=True
        )["Close"].dropna(how="all")
        if not raw.empty:
            ma200  = raw.rolling(200).mean()
            above  = (raw > ma200).sum(axis=1)
            total  = raw.notna().sum(axis=1)
            breadth = (above / total * 100).dropna()
            if not breadth.empty:
                result["breadth_pct"]  = round(float(breadth.iloc[-1]), 1)
                result["breadth_hist"] = breadth
    except Exception:
        pass

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

    # BTC (5y for 200-week MA)
    try:
        hist = yf.Ticker("BTC-USD").history(period="5y")["Close"].dropna()
        if not hist.empty:
            cur, ma, pct, above = _pct_from_ma(hist)
            result["btc_price"] = round(cur, 2)
            result["btc_ma200"] = round(ma, 2)
            result["btc_above_200ma"] = above
            result["btc_pct_from_200ma"] = pct
            result["btc_hist"] = hist

            # 200-week MA
            weekly = hist.resample("W").last()
            wma200 = weekly.rolling(200).mean()
            if len(wma200.dropna()) > 0:
                wma_val = float(wma200.dropna().iloc[-1])
                result["btc_wma200"] = round(wma_val, 2)
                result["btc_above_wma200"] = bool(cur > wma_val)
                result["btc_pct_from_wma200"] = round((cur - wma_val) / wma_val * 100, 2)

            daily_ret = hist.pct_change().dropna()
            rv30 = float(daily_ret.tail(30).std() * np.sqrt(365) * 100)
            result["btc_rv30"] = round(rv30, 2)
            result["rv30_hist"] = (
                daily_ret.rolling(30).std() * np.sqrt(365) * 100
            ).dropna()

            # BTC vol forecast: EWMA (λ=0.94), annualized % (crypto = 365 days)
            log_ret = np.log(hist / hist.shift(1)).dropna()
            fcst = _ewma_vol_forecast(log_ret, lam=0.94, periods_per_year=365)
            if fcst is not None:
                result["btc_vol_forecast"] = round(fcst, 2)

            # ATH distance
            ath = float(hist.max())
            result["btc_ath"] = round(ath, 2)
            result["btc_pct_from_ath"] = round((cur - ath) / ath * 100, 2)

            # Pi Cycle Top: 111-day MA vs 2 × 350-day MA
            if len(hist) >= 350:
                ma111   = float(hist.rolling(111).mean().iloc[-1])
                ma350x2 = float(hist.rolling(350).mean().iloc[-1]) * 2
                result["btc_pi_ma111"]   = round(ma111, 2)
                result["btc_pi_ma350x2"] = round(ma350x2, 2)
                if ma350x2 > 0:
                    result["btc_pi_ratio"] = round(ma111 / ma350x2, 4)

            # 90-day momentum
            if len(hist) >= 91:
                p90 = float(hist.iloc[-91])
                if p90 > 0:
                    result["btc_mom90"] = round((cur - p90) / p90 * 100, 2)
    except Exception:
        pass

    # IBIT data for premium overlay
    try:
        ibit_hist = yf.Ticker("IBIT").history(period="6mo")["Close"].dropna()
        if not ibit_hist.empty:
            result["ibit_price"] = round(float(ibit_hist.iloc[-1]), 2)
            result["ibit_hist"] = ibit_hist

            # IBIT options data
            ibit_ticker = yf.Ticker("IBIT")
            exps = ibit_ticker.options
            if exps:
                # Get nearest expiry for short-term IV proxy
                chain_near = ibit_ticker.option_chain(exps[0])
                # Compute approximate IV from near-ATM options
                atm_price = result["ibit_price"]
                calls = chain_near.calls
                puts = chain_near.puts
                if not calls.empty and not puts.empty:
                    # Find near-ATM implied vol
                    calls_sorted = calls.iloc[(calls["strike"] - atm_price).abs().argsort()]
                    puts_sorted = puts.iloc[(puts["strike"] - atm_price).abs().argsort()]
                    if "impliedVolatility" in calls_sorted.columns:
                        atm_call_iv = float(calls_sorted.iloc[0]["impliedVolatility"])
                        atm_put_iv = float(puts_sorted.iloc[0]["impliedVolatility"])
                        result["ibit_iv"] = round((atm_call_iv + atm_put_iv) / 2 * 100, 1)

                    # Find 0.15 delta call and 0.20 delta put for recommendations
                    if "delta" in calls.columns:
                        # Not all providers supply greeks; handle gracefully
                        cc_candidates = calls[(calls["delta"] > 0.10) & (calls["delta"] < 0.20)]
                        if not cc_candidates.empty:
                            result["ibit_cc_strike"] = float(cc_candidates.iloc[0]["strike"])
                            result["ibit_cc_premium"] = float(cc_candidates.iloc[0]["lastPrice"])

                    if "delta" in puts.columns:
                        csp_candidates = puts[(puts["delta"].abs() > 0.15) & (puts["delta"].abs() < 0.25)]
                        if not csp_candidates.empty:
                            result["ibit_csp_strike"] = float(csp_candidates.iloc[0]["strike"])
                            result["ibit_csp_premium"] = float(csp_candidates.iloc[0]["lastPrice"])

                # Compute IBIT realized vol for IV/RV comparison
                if len(ibit_hist) >= 22:
                    ibit_rv = float(ibit_hist.pct_change().dropna().tail(21).std() * np.sqrt(252) * 100)
                    result["ibit_rv21"] = round(ibit_rv, 1)
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

    # On-chain + derivatives extra data (Binance, mempool.space, blockchain.com)
    extra = fetch_bitcoin_extra_data()
    result.update(extra)

    result["timestamp"] = datetime.now()
    return result


def fetch_bitcoin_extra_data() -> dict:
    """
    Fetch on-chain, derivatives, and macro-liquidity data for the Bitcoin tab.
    All calls are no-auth / free. Each sub-fetch is independently try/except'd.
    Returns a flat dict merged into fetch_crypto_data().
    """
    result: dict = {}

    # ── OKX: funding rate history (20 × 8h periods ≈ 7 days) ─────────────────
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/public/funding-rate-history",
            params={"instId": "BTC-USD-SWAP", "limit": "20"},
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        entries = r.json().get("data", [])
        if entries:
            # OKX rates are decimal; multiply by 100 for %
            rates = [float(e["fundingRate"]) * 100 for e in entries]
            timestamps = [datetime.fromtimestamp(int(e["fundingTime"]) / 1000) for e in entries]
            result["funding_rate_current"] = round(rates[-1], 5)
            result["funding_rate_avg24h"]  = round(sum(rates[-3:]) / 3, 5)
            result["funding_rate_hist"]    = pd.Series(rates, index=timestamps)
    except Exception:
        pass

    # ── OKX: Long/Short account ratio (hourly, last 24h) ──────────────────────
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio",
            params={"ccy": "BTC", "period": "1H", "limit": "24"},
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        entries = r.json().get("data", [])
        if entries:
            # Each entry: [timestamp_ms, ratio]
            result["ls_ratio"] = round(float(entries[0][1]), 3)
    except Exception:
        pass

    # ── OKX: Open interest history (daily, 30 days) ────────────────────────────
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history",
            params={"ccy": "BTC", "period": "1D", "instType": "SWAP",
                    "instId": "BTC-USD-SWAP", "limit": "30"},
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        entries = r.json().get("data", [])
        if len(entries) >= 2:
            # Each entry: [ts_ms, oi_contracts, oi_coins, oi_usd]
            oi_vals    = [float(e[3]) / 1e9 for e in entries]  # USD → $B
            timestamps = [datetime.fromtimestamp(int(e[0]) / 1000) for e in entries]
            result["open_interest"] = round(oi_vals[0], 3)   # newest first
            result["oi_hist"]       = pd.Series(list(reversed(oi_vals)),
                                                index=list(reversed(timestamps)))
            oldest = oi_vals[-1]
            if oldest > 0:
                result["oi_pct_change_30d"] = round((oi_vals[0] - oldest) / oldest * 100, 1)
    except Exception:
        pass

    # ── Mempool.space: hash rate 3-month series ────────────────────────────────
    try:
        r = requests.get(
            "https://mempool.space/api/v1/mining/hashrate/3m",
            headers=_HEADERS, timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        hashrates = data.get("hashrates", [])
        if hashrates:
            hr_vals = [h["avgHashrate"] / 1e18 for h in hashrates]  # EH/s
            hr_ts   = [datetime.fromtimestamp(h["timestamp"]) for h in hashrates]
            result["hash_rate"]      = round(hr_vals[-1], 1)
            result["hash_rate_hist"] = pd.Series(hr_vals, index=hr_ts)
            # % change vs ~30d ago
            lookback = max(0, len(hr_vals) - 30)
            base = hr_vals[lookback]
            if base > 0:
                result["hash_rate_pct_30d"] = round((hr_vals[-1] - base) / base * 100, 1)
    except Exception:
        pass

    # ── Mempool.space: difficulty adjustment ───────────────────────────────────
    try:
        r = requests.get(
            "https://mempool.space/api/v1/difficulty-adjustment",
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        result["difficulty_adj_pct"]      = round(float(data["difficultyChange"]) * 100, 2)
        result["difficulty_adj_eta_days"] = round(float(data["remainingTime"]) / 86400, 1)
    except Exception:
        pass

    # ── CoinMetrics community: MVRV + active addresses (free, no key) ───────────
    try:
        r = requests.get(
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
            params={"assets": "btc", "metrics": "CapMVRVCur,AdrActCnt",
                    "frequency": "1d", "page_size": 365,
                    "start_time": "2020-01-01"},
            headers=_HEADERS, timeout=15,
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
        if rows:
            mvrv_rows = [(datetime.fromisoformat(row["time"][:10]), float(row["CapMVRVCur"]))
                         for row in rows if row.get("CapMVRVCur")]
            adr_rows  = [(datetime.fromisoformat(row["time"][:10]), int(float(row["AdrActCnt"])))
                         for row in rows if row.get("AdrActCnt")]
            if mvrv_rows:
                ts, vals = zip(*mvrv_rows)
                result["mvrv"]      = round(vals[-1], 3)
                result["mvrv_hist"] = pd.Series(list(vals), index=list(ts))
            if adr_rows:
                result["active_addresses"] = adr_rows[-1][1]
    except Exception:
        pass

    # ── FRED: Fed Net Liquidity = (Balance Sheet - TGA)/1000 - RRP ────────────
    try:
        walcl   = _fetch_fred_series("WALCL")    # $M, weekly
        wtregen = _fetch_fred_series("WTREGEN")  # $M, weekly
        rrp     = _fetch_fred_series("RRPONTSYD") # $B, daily
        if not walcl.empty and not wtregen.empty and not rrp.empty:
            # Align: resample RRP to weekly to match WALCL
            rrp_w = rrp.resample("W-THU").last().reindex(walcl.index, method="ffill")
            net_liq = (walcl - wtregen) / 1000 - rrp_w
            net_liq = net_liq.dropna()
            if not net_liq.empty:
                result["net_liquidity"]      = round(float(net_liq.iloc[-1]), 1)
                result["net_liquidity_hist"] = net_liq
                lookback = max(0, len(net_liq) - 5)   # ~5 weeks ≈ 30d
                base = float(net_liq.iloc[lookback])
                if base != 0:
                    result["net_liquidity_change_30d"] = round(
                        (float(net_liq.iloc[-1]) - base) / abs(base) * 100, 1
                    )
    except Exception:
        pass

    # ── FRED: US M2 money supply (weekly) ──────────────────────────────────────
    try:
        wm2 = _fetch_fred_series("WM2NS")   # $B, weekly
        if not wm2.empty:
            result["m2_usd"]  = round(float(wm2.iloc[-1]), 1)
            result["m2_hist"] = wm2
            # 1Y change
            if len(wm2) >= 52:
                base_y = float(wm2.iloc[-52])
                if base_y > 0:
                    result["m2_change_1y"] = round((float(wm2.iloc[-1]) - base_y) / base_y * 100, 1)
    except Exception:
        pass

    # ── BTC dominance proxy: BTC vs ETH market cap ratio (1y daily) ───────────
    try:
        raw = yf.download(
            ["BTC-USD", "ETH-USD"], period="1y", progress=False, auto_adjust=True
        )["Close"].dropna(how="all")
        if "BTC-USD" in raw.columns and "ETH-USD" in raw.columns:
            btc_mc = raw["BTC-USD"] * 19.85e6   # ~circulating supply
            eth_mc = raw["ETH-USD"] * 120e6
            dom_proxy = (btc_mc / (btc_mc + eth_mc) * 100).dropna()
            result["btc_dom_hist"] = dom_proxy
            if not dom_proxy.empty:
                result["btc_dom_proxy"] = round(float(dom_proxy.iloc[-1]), 1)
    except Exception:
        pass

    # ── Rainbow Chart: max BTC history + log regression ───────────────────────
    try:
        hist_max = yf.Ticker("BTC-USD").history(period="max")["Close"].dropna()
        if not hist_max.empty:
            genesis = datetime(2009, 1, 3)
            days_arr = np.array(
                [(ts.to_pydatetime().replace(tzinfo=None) - genesis).days
                 for ts in hist_max.index],
                dtype=float,
            )
            valid = days_arr > 0
            d_valid = days_arr[valid]
            p_valid = hist_max.values[valid]
            if len(d_valid) > 10:
                b_coef, a_coef = np.polyfit(np.log(d_valid), np.log(p_valid), 1)
                result["rainbow_coeffs"] = (float(a_coef), float(b_coef))
            result["btc_hist_max"] = hist_max
    except Exception:
        pass

    return result


# ── Macro ─────────────────────────────────────────────────────────────────────

def fetch_macro_data() -> dict:
    result: dict = {}

    # 10Y Treasury yield
    try:
        hist = yf.Ticker("^TNX").history(period="1y")["Close"].dropna()
        if not hist.empty:
            result["yield_10y"] = round(hist.iloc[-1], 3)
            result["yield_10y_hist"] = hist
    except Exception:
        pass

    # 3-month T-bill
    try:
        hist = yf.Ticker("^IRX").history(period="1y")["Close"].dropna()
        if not hist.empty:
            result["yield_3m"] = round(hist.iloc[-1], 3)
            result["yield_3m_hist"] = hist
    except Exception:
        pass

    # Yield curve spread (10Y − 3M)
    if "yield_10y" in result and "yield_3m" in result:
        result["yield_spread"] = round(result["yield_10y"] - result["yield_3m"], 3)
    if "yield_10y_hist" in result and "yield_3m_hist" in result:
        h10 = result["yield_10y_hist"].copy()
        h3m = result["yield_3m_hist"].copy()
        if h10.index.tz is not None:
            h10.index = h10.index.tz_localize(None)
        if h3m.index.tz is not None:
            h3m.index = h3m.index.tz_localize(None)
        h10.index = h10.index.normalize()
        h3m.index = h3m.index.normalize()
        spread = (h10 - h3m).dropna()
        if not spread.empty:
            result["yield_spread_hist"] = spread

    # DXY (US Dollar Index)
    for dxy_ticker in ("DX=F", "DX-Y.NYB", "UUP"):
        try:
            hist = yf.Ticker(dxy_ticker).history(period="1y")["Close"].dropna()
            if not hist.empty:
                cur, ma, pct, above = _pct_from_ma(hist)
                result["dxy"] = round(cur, 2)
                result["dxy_ma200"] = round(ma, 2)
                result["dxy_above_200ma"] = above
                result["dxy_pct_from_200ma"] = pct
                result["dxy_hist"] = hist
                break
        except Exception:
            continue

    # Gold futures
    try:
        hist = yf.Ticker("GC=F").history(period="1y")["Close"].dropna()
        if not hist.empty:
            cur, ma, pct, above = _pct_from_ma(hist)
            result["gold"] = round(cur, 2)
            result["gold_ma200"] = round(ma, 2)
            result["gold_above_200ma"] = above
            result["gold_pct_from_200ma"] = pct
            result["gold_hist"] = hist
    except Exception:
        pass

    # WTI crude oil futures
    try:
        hist = yf.Ticker("CL=F").history(period="1y")["Close"].dropna()
        if not hist.empty:
            cur, ma, pct, above = _pct_from_ma(hist)
            result["oil"] = round(cur, 2)
            result["oil_ma200"] = round(ma, 2)
            result["oil_above_200ma"] = above
            result["oil_pct_from_200ma"] = pct
            result["oil_hist"] = hist
    except Exception:
        pass

    # HYG (high-yield credit proxy)
    try:
        hist = yf.Ticker("HYG").history(period="1y")["Close"].dropna()
        if not hist.empty:
            cur, ma, pct, above = _pct_from_ma(hist)
            result["hyg"] = round(cur, 2)
            result["hyg_ma200"] = round(ma, 2)
            result["hyg_above_200ma"] = above
            result["hyg_pct_from_200ma"] = pct
            result["hyg_hist"] = hist
    except Exception:
        pass

    # ── FRED Series ───────────────────────────────────────────────────────────

    # STLFSI4 — St. Louis Fed Financial Stress Index
    stlfsi = _fetch_fred_series("STLFSI4")
    if not stlfsi.empty:
        result["stlfsi"] = round(float(stlfsi.iloc[-1]), 3)
        result["stlfsi_hist"] = stlfsi

    # MOVE Index — ICE BofA MOVE Index (bond volatility) via Yahoo Finance
    try:
        move_hist = yf.Ticker("^MOVE").history(period="1y")["Close"].dropna()
        if not move_hist.empty:
            result["move"] = round(float(move_hist.iloc[-1]), 2)
            result["move_hist"] = move_hist
    except Exception:
        pass

    # HY Credit Spread — BofA US High Yield OAS (BAMLH0A0HYM2)
    hy_spread = _fetch_fred_series("BAMLH0A0HYM2")
    if not hy_spread.empty:
        result["hy_spread"] = round(float(hy_spread.iloc[-1]), 2)
        result["hy_spread_hist"] = hy_spread

    # 5Y Breakeven Inflation (T5YIE)
    be5y = _fetch_fred_series("T5YIE")
    if not be5y.empty:
        result["breakeven_5y"] = round(float(be5y.iloc[-1]), 2)
        result["breakeven_5y_hist"] = be5y

    # 10Y Breakeven Inflation (T10YIE)
    be10y = _fetch_fred_series("T10YIE")
    if not be10y.empty:
        result["breakeven_10y"] = round(float(be10y.iloc[-1]), 2)
        result["breakeven_10y_hist"] = be10y

    # 10Y Real Yield (DFII10) — TIPS yield
    real10y = _fetch_fred_series("DFII10")
    if not real10y.empty:
        result["real_yield_10y"] = round(float(real10y.iloc[-1]), 2)
        result["real_yield_10y_hist"] = real10y

    # SGOV / short-term treasury yield proxy (3-month already captured as yield_3m)
    # We also fetch the 1-month T-bill for cash yield context
    tbill_1m = _fetch_fred_series("DGS1MO")
    if not tbill_1m.empty:
        result["yield_1m"] = round(float(tbill_1m.iloc[-1]), 3)

    result["timestamp"] = datetime.now()
    return result


# ── Macro: forward-risk (recession prob + financial conditions) ───────────────

def fetch_forward_risk_data() -> dict:
    """FRED-driven forward-looking macro: NY Fed yield-curve recession prob,
    St Louis Fed smoothed recession prob, Chicago Fed NFCI / ANFCI."""
    from forecasting import ny_fed_recession_history

    result: dict = {"timestamp": datetime.now()}

    # NY Fed: derive from 10Y-3M spread series (DGS10 - DGS3MO).
    try:
        t10 = _fetch_fred_series("DGS10",  start="2000-01-01")
        t3m = _fetch_fred_series("DGS3MO", start="2000-01-01")
        if not t10.empty and not t3m.empty:
            spread = (t10 - t3m).dropna()
            prob_hist = ny_fed_recession_history(spread) * 100  # %
            result["ny_fed_spread_pct"]   = round(float(spread.iloc[-1]), 3)
            result["ny_fed_recession_pct"] = round(float(prob_hist.iloc[-1]), 1)
            # Last 24 months as sparkline / chart
            result["ny_fed_hist"] = prob_hist.tail(24 * 30)
    except Exception as exc:
        result["ny_fed_error"] = str(exc)

    # St Louis Fed smoothed recession probability (monthly, %)
    try:
        rp = _fetch_fred_series("RECPROUSM156N", start="2000-01-01")
        if not rp.empty:
            result["stl_recession_pct"] = round(float(rp.iloc[-1]), 1)
            result["stl_recession_hist"] = rp.tail(24)
    except Exception as exc:
        result["stl_error"] = str(exc)

    # Chicago Fed Financial Conditions Index (weekly, z-score)
    try:
        nfci  = _fetch_fred_series("NFCI",  start="2010-01-01")
        anfci = _fetch_fred_series("ANFCI", start="2010-01-01")
        if not nfci.empty:
            result["nfci"]      = round(float(nfci.iloc[-1]), 3)
            result["nfci_12w"]  = (round(float(nfci.iloc[-1] - nfci.iloc[-12]), 3)
                                   if len(nfci) >= 12 else None)
            result["nfci_hist"] = nfci.tail(52 * 2)  # ~2y weekly
        if not anfci.empty:
            result["anfci"]      = round(float(anfci.iloc[-1]), 3)
            result["anfci_hist"] = anfci.tail(52 * 2)
    except Exception as exc:
        result["nfci_error"] = str(exc)

    return result


# ── Sectors ───────────────────────────────────────────────────────────────────

SECTOR_NAMES = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Health Care",
    "XLI":  "Industrials",
    "XLC":  "Comm Services",
    "XLY":  "Cons Discret.",
    "XLP":  "Cons Staples",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
    "XLU":  "Utilities",
}

_OFFENSIVE_SECTORS = {"XLK", "XLY", "XLI", "XLC", "XLF"}
_DEFENSIVE_SECTORS = {"XLP", "XLV", "XLRE", "XLU"}
_SECTOR_TICKERS = list(SECTOR_NAMES.keys())


def _safe_pct(series: pd.Series, n: int) -> float | None:
    s = series.dropna()
    if len(s) > n:
        base = float(s.iloc[-1 - n])
        if base != 0:
            return round((float(s.iloc[-1]) - base) / base * 100, 2)
    return None


def fetch_sector_data() -> dict:
    all_tickers = _SECTOR_TICKERS + ["SPY"]
    try:
        df = yf.download(
            all_tickers, period="1y", auto_adjust=True, progress=False
        )["Close"].dropna(how="all")
    except Exception as exc:
        return {"error": str(exc), "sectors": {}, "sorted_by_rs": [],
                "rotation_regime": "MIXED", "timestamp": datetime.now()}

    spy = df["SPY"].dropna() if "SPY" in df.columns else pd.Series(dtype=float)

    # Compute SPY returns for IBD-style excess return baseline
    def spy_ret(n):
        if len(spy) > n:
            base = float(spy.iloc[-1 - n])
            return (float(spy.iloc[-1]) - base) / base * 100 if base else 0.0
        return 0.0

    spy_3m  = spy_ret(63)
    spy_6m  = spy_ret(126)
    spy_9m  = spy_ret(189)
    spy_12m = spy_ret(252)

    raw_scores: dict[str, float] = {}
    sectors: dict = {}

    for ticker in _SECTOR_TICKERS:
        if ticker not in df.columns:
            continue
        try:
            s = df[ticker].dropna()
            if s.empty:
                continue

            price = round(float(s.iloc[-1]), 2)

            # Performance returns
            pct_1d = _safe_pct(s, 1)
            pct_5d = _safe_pct(s, 5)
            pct_1m = _safe_pct(s, 21)
            pct_3m = _safe_pct(s, 63)

            # YTD
            ytd = None
            yr_start = pd.Timestamp(f"{s.index[-1].year}-01-01")
            ytd_idx = int(s.index.searchsorted(yr_start))
            if ytd_idx < len(s):
                ytd_base = float(s.iloc[ytd_idx])
                if ytd_base:
                    ytd = round((price - ytd_base) / ytd_base * 100, 2)

            # RS Ratio (JdK): normalize sector/spy to rolling mean=100
            if not spy.empty:
                ratio = (s / spy.reindex(s.index)).dropna()
                rs_ratio_series = (ratio / ratio.rolling(50, min_periods=20).mean() * 100).dropna()
                rs_ratio = float(rs_ratio_series.iloc[-1]) if not rs_ratio_series.empty else 100.0
                mom_n = min(20, len(rs_ratio_series) - 1)
                rs_mom = float(rs_ratio_series.iloc[-1] - rs_ratio_series.iloc[-1 - mom_n]) if mom_n > 0 else 0.0
            else:
                rs_ratio = 100.0
                rs_mom   = 0.0

            # Quadrant
            if rs_ratio >= 100 and rs_mom >= 0:
                quadrant = "Leading"
            elif rs_ratio >= 100 and rs_mom < 0:
                quadrant = "Weakening"
            elif rs_ratio < 100 and rs_mom >= 0:
                quadrant = "Improving"
            else:
                quadrant = "Lagging"

            # IBD RS raw score
            def ret(n, _s=s, _p=price):
                if len(_s) > n:
                    b = float(_s.iloc[-1 - n])
                    return (_p - b) / b * 100 if b else 0.0
                return 0.0

            raw_scores[ticker] = (
                0.40 * (ret(63)  - spy_3m)  +
                0.20 * (ret(126) - spy_6m)  +
                0.20 * (ret(189) - spy_9m)  +
                0.20 * (ret(252) - spy_12m)
            )

            sectors[ticker] = {
                "name":     SECTOR_NAMES[ticker],
                "price":    price,
                "pct_1d":   pct_1d,
                "pct_5d":   pct_5d,
                "pct_1m":   pct_1m,
                "pct_3m":   pct_3m,
                "ytd":      ytd,
                "rs_ratio": round(rs_ratio, 2),
                "rs_mom":   round(rs_mom, 4),
                "quadrant": quadrant,
                "hist":     s,
                "rs_score": 0,   # filled below
            }
        except Exception:
            continue

    # Assign percentile RS scores (0–100)
    if len(raw_scores) > 1:
        all_raw = list(raw_scores.values())
        for ticker, raw in raw_scores.items():
            if ticker in sectors:
                rank = sum(1 for v in all_raw if v < raw)
                sectors[ticker]["rs_score"] = round(rank / (len(all_raw) - 1) * 100)
    elif len(raw_scores) == 1:
        for ticker in raw_scores:
            if ticker in sectors:
                sectors[ticker]["rs_score"] = 50

    sorted_by_rs = sorted(sectors.keys(), key=lambda t: sectors[t]["rs_score"], reverse=True)

    # Rotation regime based on character of top-3 sectors
    top3 = sorted_by_rs[:3]
    off_count = sum(1 for t in top3 if t in _OFFENSIVE_SECTORS)
    def_count = sum(1 for t in top3 if t in _DEFENSIVE_SECTORS)
    if off_count >= 2:
        rotation_regime = "OFFENSIVE"
    elif def_count >= 2:
        rotation_regime = "DEFENSIVE"
    else:
        rotation_regime = "MIXED"

    return {
        "sectors":         sectors,
        "sorted_by_rs":    sorted_by_rs,
        "rotation_regime": rotation_regime,
        "spy_hist":        spy,
        "timestamp":       datetime.now(),
    }
