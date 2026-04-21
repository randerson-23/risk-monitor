"""
AI analysis module — calls Anthropic API with current dashboard state
and returns a market assessment with actionable recommendations.

Reads ANTHROPIC_API_KEY from .env.  Uses web search tool for upcoming events.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from history_db import get_recent_snapshots, get_regime_transitions

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 2048
_DB_PATH = Path(__file__).parent / "risk_monitor_history.db"


def _ensure_analysis_table():
    """Create the ai_analyses table if it doesn't exist."""
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_analyses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                prompt_hash TEXT,
                response    TEXT NOT NULL,
                snapshot_id INTEGER
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _save_analysis(response_text: str, snapshot_summary: str):
    """Persist the AI response to SQLite."""
    try:
        _ensure_analysis_table()
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute(
            "INSERT INTO ai_analyses (timestamp, prompt_hash, response) VALUES (?, ?, ?)",
            (datetime.now().isoformat(), str(hash(snapshot_summary))[:16], response_text),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[ai_analysis] save error: {exc}")


def _build_snapshot_context(snapshot: dict, equity_data: dict,
                             crypto_data: dict, macro_data: dict) -> str:
    """Build a concise text summary of the current dashboard state."""
    lines = []
    lines.append(f"=== RISK MONITOR SNAPSHOT — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    # Regimes
    eq = snapshot.get("eq", {})
    cr = snapshot.get("cr", {})
    mc = snapshot.get("mc", {})
    lines.append(f"OVERALL REGIME: {snapshot.get('overall', '?')}")
    lines.append(f"  Equity: {eq.get('regime','?')} (score {eq.get('score','?')}/8)")
    lines.append(f"  Crypto: {cr.get('regime','?')} (score {cr.get('score','?')})")
    lines.append(f"  Macro:  {mc.get('regime','?')} (score {mc.get('score','?')}/7)")

    # Allocations
    lines.append(f"\nALLOCATIONS:")
    lines.append(f"  Equity/Bond sleeve: EQ {snapshot.get('eq_pct', snapshot.get('betterment_eq_pct', '?'))}% / BOND {snapshot.get('bond_pct', snapshot.get('betterment_bond_pct', '?'))}%")
    lines.append(f"  BTC/IBIT deployed: {snapshot.get('btc_exposure','?')}%")
    lines.append(f"  SPX premium sizing: {snapshot.get('spx_sizing','?')}×")
    lines.append(f"  SPX directional lean: {snapshot.get('spx_lean','?')}")
    lines.append(f"  IBIT premium sizing: {snapshot.get('ibit_sizing','?')}×")

    # Equity/Bond allocation drivers
    drivers = snapshot.get("alloc_drivers", snapshot.get("bet_drivers", []))
    if drivers:
        lines.append(f"\nEQUITY/BOND ALLOCATION DRIVERS:")
        for d in drivers:
            lines.append(f"  • {d}")

    # Key metrics
    lines.append(f"\nKEY METRICS:")
    vix = equity_data.get("vix")
    if vix: lines.append(f"  VIX: {vix}")
    spx = equity_data.get("spx")
    if spx: lines.append(f"  S&P 500: {spx:,.0f}")
    cnn = equity_data.get("cnn_fear_greed")
    if cnn: lines.append(f"  CNN Fear & Greed: {cnn} ({equity_data.get('cnn_fear_greed_rating','')})")
    skew = equity_data.get("skew")
    if skew: lines.append(f"  SKEW: {skew}")
    pc = equity_data.get("put_call_ratio")
    if pc: lines.append(f"  Put/Call Ratio: {pc}")
    breadth = equity_data.get("breadth_pct")
    if breadth: lines.append(f"  Market Breadth: {breadth}%")

    btc = crypto_data.get("btc_price")
    if btc: lines.append(f"  BTC Price: ${btc:,.0f}")
    cfg = crypto_data.get("crypto_fear_greed")
    if cfg: lines.append(f"  Crypto Fear & Greed: {cfg}")
    rv30 = crypto_data.get("btc_rv30")
    if rv30: lines.append(f"  BTC 30d Realized Vol: {rv30}%")
    dom = crypto_data.get("btc_dominance")
    if dom: lines.append(f"  BTC Dominance: {dom}%")
    ath_pct = crypto_data.get("btc_pct_from_ath")
    if ath_pct is not None: lines.append(f"  BTC Distance from ATH: {ath_pct:.1f}%")
    ibit_iv = crypto_data.get("ibit_iv")
    if ibit_iv: lines.append(f"  IBIT IV: {ibit_iv}%")

    funding_avg = crypto_data.get("funding_rate_avg24h")
    if funding_avg is not None: lines.append(f"  BTC Funding (24h avg): {funding_avg:+.4f}%")
    ls = crypto_data.get("ls_ratio")
    if ls is not None: lines.append(f"  Long/Short Ratio: {ls:.3f}")
    oi = crypto_data.get("open_interest")
    if oi is not None: lines.append(f"  Open Interest (OKX): ${oi:.3f}B")
    oi_chg = crypto_data.get("oi_pct_change_30d")
    if oi_chg is not None: lines.append(f"  OI 30d Change: {oi_chg:+.1f}%")
    hr = crypto_data.get("hash_rate")
    if hr is not None: lines.append(f"  Hash Rate: {hr:.1f} EH/s")
    hr_chg = crypto_data.get("hash_rate_pct_30d")
    if hr_chg is not None: lines.append(f"  Hash Rate 30d: {hr_chg:+.1f}%")
    diff_pct = crypto_data.get("difficulty_adj_pct")
    if diff_pct is not None: lines.append(f"  Next Difficulty Adj: {diff_pct:+.1f}%")
    addr = crypto_data.get("active_addresses")
    if addr is not None: lines.append(f"  Active Addresses (24h): {addr:,}")
    mvrv = crypto_data.get("mvrv")
    if mvrv is not None: lines.append(f"  MVRV: {mvrv:.3f}")
    net_liq = crypto_data.get("net_liquidity")
    liq_chg = crypto_data.get("net_liquidity_change_30d")
    if net_liq is not None:
        chg_str = f"  ({liq_chg:+.1f}% 30d)" if liq_chg is not None else ""
        lines.append(f"  Fed Net Liquidity: ${net_liq:,.0f}B{chg_str}")
    m2 = crypto_data.get("m2_usd")
    m2_chg = crypto_data.get("m2_change_1y")
    if m2 is not None:
        chg_str = f"  ({m2_chg:+.1f}% 1Y)" if m2_chg is not None else ""
        lines.append(f"  US M2: ${m2:,.0f}B{chg_str}")

    move = macro_data.get("move")
    if move: lines.append(f"  MOVE Index: {move}")
    hy = macro_data.get("hy_spread")
    if hy: lines.append(f"  HY Credit Spread: {hy}%")
    y10 = macro_data.get("yield_10y")
    if y10: lines.append(f"  10Y Yield: {y10}%")
    y3m = macro_data.get("yield_3m")
    if y3m: lines.append(f"  3M Yield: {y3m}%")
    spread = macro_data.get("yield_spread")
    if spread is not None: lines.append(f"  Yield Curve (10Y-3M): {spread:+.3f}%")
    real_y = macro_data.get("real_yield_10y")
    if real_y is not None: lines.append(f"  10Y Real Yield: {real_y}%")
    be5 = macro_data.get("breakeven_5y")
    if be5: lines.append(f"  5Y Breakeven: {be5}%")
    stlfsi = macro_data.get("stlfsi")
    if stlfsi is not None: lines.append(f"  STLFSI: {stlfsi:+.3f}")

    # Regime factors
    lines.append(f"\nEQUITY FACTORS:")
    for f in eq.get("factors", []): lines.append(f"  {f}")
    lines.append(f"\nCRYPTO FACTORS:")
    for f in cr.get("factors", []): lines.append(f"  {f}")
    lines.append(f"\nMACRO FACTORS:")
    for f in mc.get("factors", []): lines.append(f"  {f}")

    # Sector rotation
    sector_data = snapshot.get("sector_data")
    if sector_data and sector_data.get("sectors"):
        lines.append(f"\nSECTOR ROTATION: {sector_data.get('rotation_regime', '?')}")
        top3 = sector_data.get("sorted_by_rs", [])[:3]
        bot3 = list(reversed(sector_data.get("sorted_by_rs", [])[-3:]))
        if top3: lines.append(f"  Top sectors (RS): {', '.join(top3)}")
        if bot3: lines.append(f"  Weak sectors (RS): {', '.join(bot3)}")
        improving = [t for t, d in sector_data["sectors"].items() if d.get("quadrant") == "Improving"]
        if improving: lines.append(f"  Entering IMPROVING (watch): {', '.join(improving)}")

    # Recent regime transitions from history
    transitions = get_regime_transitions(10)
    if transitions:
        lines.append(f"\nRECENT REGIME TRANSITIONS (last {len(transitions)}):")
        for t in transitions[-5:]:
            changes = t.get("_changes", [])
            lines.append(f"  {t.get('timestamp', '?')[:16]}: {', '.join(changes)}")

    return "\n".join(lines)


def _build_system_prompt() -> str:
    return """You are a senior risk analyst assistant embedded in a personal portfolio dashboard. The user runs 3 strategies:

1. EQUITY / BOND CORE PORTFOLIO (40% of NW) — Global equity/bond split. You are advising on the equity vs bond target percentage.
2. BITCOIN / IBIT (40% of NW) — Pure BTC exposure via IBIT ETF, with a premium overlay: covered calls at 0.15 delta (goal: not get called) and cash-secured puts at 0.20 delta (goal: accumulation). Cash held in SGOV.
3. SPX/ES PREMIUM SELLING (20% of NW) — Sells premium on SPX, /MES, /ES. Comfortable selling naked on the leaning side. 1DTE, 30DTE, 45DTE tenors. Cash in treasuries.

The user is an active, experienced investor comfortable with advanced strategies and allocation changes.

Your job on each analysis request:
1. MARKET ASSESSMENT — 2-3 sentence overall read of current conditions.
2. SLEEVE-BY-SLEEVE RECOMMENDATIONS — For each of the 3 sleeves, confirm or challenge the dashboard's current recommendation with brief reasoning. Be specific (e.g. "I'd widen the CC delta to 0.10 given momentum" not just "be careful").
3. HIGH-IMPACT EVENTS (NEXT 3 DAYS) — Check for FOMC decisions, CPI/PPI/NFP releases, PCE, earnings from mega-caps, options expiration (monthly/quarterly OPEX), ECB/BOJ meetings, or any major geopolitical developments that could move markets. List each with date and expected impact.
4. DO-NOT-TRADE ASSESSMENT — Explicitly state whether current conditions warrant a "do not trade" posture due to excessive uncertainty (e.g. pre-FOMC blackout, unclear macro regime, extreme cross-asset divergence). If yes, specify which sleeves should pause and for how long.
5. KEY RISKS — 2-3 specific risks to watch that could change the regime in the next week.

Be concise, direct, and actionable. No fluff. Use the data provided — don't make up numbers."""


def run_analysis(snapshot: dict, equity_data: dict,
                 crypto_data: dict, macro_data: dict,
                 user_context: str = "", sector_data: dict | None = None) -> str:
    """
    Call Anthropic API with current dashboard state.
    Returns the analysis text or an error message.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_anthropic_key_here":
        return ("⚠ ANTHROPIC_API_KEY not configured.\n\n"
                "Add your key to the .env file:\n"
                "ANTHROPIC_API_KEY=sk-ant-...")

    if sector_data:
        snapshot = dict(snapshot)
        snapshot["sector_data"] = sector_data
    context = _build_snapshot_context(snapshot, equity_data, crypto_data, macro_data)

    if user_context:
        extra = f"\n\nADDITIONAL CONTEXT / QUESTIONS FROM USER:\n{user_context}\n"
    else:
        extra = ""

    user_message = (
        f"{context}{extra}\n\n"
        "Please provide your analysis following the 5-section format: "
        "Market Assessment, Sleeve-by-Sleeve, High-Impact Events (next 3 days), "
        "Do-Not-Trade Assessment, and Key Risks."
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": _MAX_TOKENS,
                "system": _build_system_prompt(),
                "tools": [
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                    }
                ],
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract text from content blocks
        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])

        result = "\n".join(text_parts) if text_parts else "No response received."

        # Save to SQLite
        _save_analysis(result, context[:200])

        return result

    except requests.exceptions.Timeout:
        return "⚠ Request timed out. The API may be under heavy load. Try again in a moment."
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response else "?"
        body = exc.response.text[:300] if exc.response else ""
        return f"⚠ API error (HTTP {status}):\n{body}"
    except Exception as exc:
        return f"⚠ Analysis failed: {exc}"


def get_recent_analyses(limit: int = 20) -> list[dict]:
    """Return recent AI analyses from the database."""
    try:
        _ensure_analysis_table()
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM ai_analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


# ── Consumer Sentiment Analysis ───────────────────────────────────────────────

def _ensure_sentiment_table():
    """Create the consumer_sentiment_analyses table if it doesn't exist."""
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consumer_sentiment_analyses (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL,
                response        TEXT NOT NULL,
                sentiment_score TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _save_sentiment_analysis(response_text: str, sentiment_score: str):
    """Persist a consumer sentiment analysis to SQLite."""
    try:
        _ensure_sentiment_table()
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute(
            "INSERT INTO consumer_sentiment_analyses (timestamp, response, sentiment_score) "
            "VALUES (?, ?, ?)",
            (datetime.now().isoformat(), response_text, sentiment_score),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[ai_analysis] sentiment save error: {exc}")


def _build_sentiment_system_prompt() -> str:
    return """You are a macro risk analyst specializing in consumer and public sentiment analysis.
Your role is to search recent news and synthesize how consumer fears and confidence are shaping economic risk.

Focus areas:
1. ECONOMY — consumer confidence, retail sales, housing, credit stress
2. AI & JOB DISPLACEMENT — news about AI-driven layoffs, automation fears, white-collar job anxiety
3. INFLATION — price pressures, cost-of-living, consumer purchasing power
4. EMPLOYMENT — layoffs, hiring freezes, unemployment fears, gig economy stress

After analyzing each area, provide:
- OVERALL SENTIMENT SCORE: one of BEARISH, NEUTRAL, or BULLISH (from a risk perspective — BEARISH means elevated consumer fear which is risk-negative)
- A concise 2-3 sentence summary per area
- Key data points or headlines supporting each assessment

End your response with a line exactly like this (no other text on that line):
SENTIMENT_SCORE: BEARISH
(or NEUTRAL or BULLISH)

Be concise and data-driven. Cite specific headlines or statistics where available."""


def run_sentiment_analysis() -> dict:
    """
    Call Anthropic API with web search to compile consumer sentiment.
    Returns dict with keys: response (str), sentiment_score (str), timestamp (str).
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_anthropic_key_here":
        return {
            "response": ("⚠ ANTHROPIC_API_KEY not configured.\n\n"
                         "Add your key to the .env file:\nANTHROPIC_API_KEY=sk-ant-..."),
            "sentiment_score": "NEUTRAL",
            "timestamp": datetime.now().isoformat(),
        }

    user_message = (
        f"Today is {datetime.now().strftime('%Y-%m-%d')}. "
        "Please search for the latest news and data on consumer sentiment across these four areas: "
        "(1) broader economic conditions and consumer confidence, "
        "(2) AI fears and job displacement concerns, "
        "(3) inflation and cost-of-living pressures, "
        "(4) job loss and unemployment fears. "
        "Provide a structured analysis with an overall BEARISH/NEUTRAL/BULLISH score."
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 2048,
                "system": _build_sentiment_system_prompt(),
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()

        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
        result = "\n".join(text_parts) if text_parts else "No response received."

        # Extract sentiment score from response
        score = "NEUTRAL"
        for line in result.splitlines():
            if line.strip().startswith("SENTIMENT_SCORE:"):
                raw = line.split(":", 1)[1].strip().upper()
                if raw in ("BEARISH", "NEUTRAL", "BULLISH"):
                    score = raw
                break

        _save_sentiment_analysis(result, score)

        return {
            "response": result,
            "sentiment_score": score,
            "timestamp": datetime.now().isoformat(),
        }

    except requests.exceptions.Timeout:
        return {
            "response": "⚠ Request timed out. Try again in a moment.",
            "sentiment_score": "NEUTRAL",
            "timestamp": datetime.now().isoformat(),
        }
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response else "?"
        body = exc.response.text[:300] if exc.response else ""
        return {
            "response": f"⚠ API error (HTTP {status}):\n{body}",
            "sentiment_score": "NEUTRAL",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as exc:
        return {
            "response": f"⚠ Sentiment analysis failed: {exc}",
            "sentiment_score": "NEUTRAL",
            "timestamp": datetime.now().isoformat(),
        }


def get_recent_sentiment_analyses(limit: int = 10) -> list[dict]:
    """Return recent consumer sentiment analyses from the database."""
    try:
        _ensure_sentiment_table()
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM consumer_sentiment_analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_latest_sentiment() -> dict | None:
    """Return the most recent consumer sentiment analysis, or None."""
    results = get_recent_sentiment_analyses(limit=1)
    return results[0] if results else None
