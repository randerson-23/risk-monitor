# Risk Monitor

A PyQt6 desktop dashboard for monitoring market risk sentiment across equities, crypto, and macro — designed to guide personal portfolio allocation across three strategies.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.5%2B-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Overview

Risk Monitor aggregates publicly available fear/greed scores, volatility indices, trend signals, credit conditions, and macro indicators into a single dark-themed dashboard. All data is fetched in background threads so the UI stays responsive, and everything refreshes automatically every 5 minutes.

The Portfolio tab provides actionable allocation recommendations for three strategy sleeves:

1. **Passive ETFs (40% of NW)** — Equity + Macro regime drives deployed vs cash percentage
2. **Bitcoin / IBIT (40% of NW)** — Crypto regime + halving cycle drives exposure; includes premium overlay for CCs and CSPs
3. **SPX / ES Premium Selling (20% of NW)** — VIX conditions, directional lean, and strategy guide for 1DTE / 30DTE / 45DTE

---

## Features

- **Regime classification** — each tab scores multiple indicators and outputs a single Risk-On / Neutral / Risk-Off verdict
- **Fear & Greed gauge** — semicircular visual gauge for both equity (CNN) and crypto (Alternative.me) sentiment scores
- **Metric cards** — colour-coded tiles for every individual indicator, updating on each refresh
- **Toggleable chart** — pyqtgraph chart with regime overlays, switchable between data series
- **Equity/Bond split recommendation** — suggests Betterment target allocation based on regime scores, MOVE, credit spreads, real yields, and yield curve
- **IBIT premium overlay** — covered call (0.15∆) and cash-secured put (0.20∆) recommendations sized by crypto regime
- **SPX directional lean** — naked put vs call recommendation based on equity regime direction
- **Cash yield context** — shows what idle cash earns across sleeves (T-bill / SGOV proxy)
- **Toast notifications** — persistent in-app notification bar + system tray alerts when regimes flip or allocations shift ≥10pp; requires manual dismissal
- **FRED API integration** — MOVE index, HY credit spread (BAMLH0A0HYM2), breakeven inflation, real yields, and financial stress via FRED API key in `.env`
- **Non-blocking data fetching** — all network calls run in `QThread` workers
- **Auto-refresh** — data reloads every 5 minutes; manual refresh button also available

---

## Setup

### FRED API Key

The macro tab pulls several series from FRED. Create a `.env` file in the project root:

```
FRED_API_KEY=your_key_here
```

Get a free key at [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)

### Installation

**Requirements:** Python 3.10+

```bash
git clone https://github.com/randerson-23/risk-monitor.git
cd risk-monitor
pip install -r requirements.txt
python main.py
```

---

## Tabs

### Equities

| Metric | Source | Notes |
|---|---|---|
| CNN Fear & Greed | CNN (unofficial endpoint) | 0–100 gauge |
| VIX | Yahoo Finance `^VIX` | CBOE Volatility Index |
| SKEW Index | Yahoo Finance `^SKEW` | Tail-risk gauge |
| Put/Call Ratio | Yahoo Finance (SPY options chain) | Nearest-expiry volume ratio |
| Market Breadth | Yahoo Finance (25-stock basket) | % of large-caps above 200-day MA |
| S&P 500 vs 200 MA | Yahoo Finance `^GSPC` | Trend regime signal |

### Crypto

| Metric | Source | Notes |
|---|---|---|
| Crypto Fear & Greed | Alternative.me API | 0–100 gauge |
| BTC Price vs 200 MA | Yahoo Finance `BTC-USD` | Trend regime signal |
| BTC vs 200-Week MA | Computed | Long-cycle floor signal |
| BTC Dominance | CoinGecko API | Capital rotation indicator |
| 30d Realized Volatility | Computed | Annualized rolling window |
| ATH Distance | Computed | Cycle valuation context |
| Pi Cycle Top | Computed | 111 MA vs 2×350 MA ratio |
| 90d Momentum | Computed | Trend strength |
| 4-Year Halving Cycle | Date-based | Phase + action recommendation |
| IBIT Price & IV | Yahoo Finance `IBIT` | Premium overlay context |

### Macro

| Metric | Source | Notes |
|---|---|---|
| 10Y Treasury Yield | Yahoo Finance `^TNX` | Rate environment |
| 3M T-Bill Yield | Yahoo Finance `^IRX` | Short-term rate / cash yield |
| Yield Curve (10Y−3M) | Computed | Recession signal |
| DXY vs 200 MA | Yahoo Finance | Dollar strength |
| Gold vs 200 MA | Yahoo Finance `GC=F` | Safe haven demand |
| Oil vs 200 MA | Yahoo Finance `CL=F` | Growth signal |
| HYG vs 200 MA | Yahoo Finance `HYG` | Credit stress proxy |
| STLFSI4 | FRED API | St. Louis Fed Financial Stress |
| **MOVE Index** | FRED API | Bond market volatility |
| **HY Credit Spread** | FRED API (BAMLH0A0HYM2) | High-yield OAS |
| **5Y Breakeven Inflation** | FRED API (T5YIE) | Market inflation expectations |
| **10Y Real Yield** | FRED API (DFII10) | TIPS yield — bond attractiveness |
| **1M T-Bill** | FRED API (DGS1MO) | Cash yield context |

### Portfolio

| Section | Purpose |
|---|---|
| **Passive ETFs** | Deployed % based on equity + macro regime, with VIX percentile trim |
| **Betterment Target** | Equity/Bond split recommendation (40–95% equity) driven by regime scores, MOVE, HY spread, yield curve, real yields |
| **Bitcoin / IBIT** | Deployed % based on crypto regime + halving cycle |
| **IBIT Premium Overlay** | CC (0.15∆) and CSP (0.20∆) sizing and strategy by crypto regime |
| **SPX Premium Selling** | Directional lean (naked put vs call), VIX conditions, sizing, expected moves, strategy guide by tenor |
| **Cash Yield** | What idle cash earns in T-bills / SGOV |

---

## Regime Scoring

### Equity (−8 to +8)

| Indicator | Condition | Points |
|---|---|---|
| VIX | < 15 → +2, 15–20 → +1, 20–25 → −1, 25–30 → −1, > 30 → −2 | −2 to +2 |
| SPX vs 200 MA | Above → +1, Below → −1 | ±1 |
| Put/Call | < 0.7 → +1, > 1.0 → −1 | ±1 |
| Breadth | > 60% → +1, < 40% → −1 | ±1 |
| CNN F&G | > 65 → +1, < 35 → −1 | ±1 |
| SKEW | > 145 → −1, < 120 → +1 | ±1 |

**Verdict:** ≥ +3 Risk-On | ≤ −2 Risk-Off | else Neutral

### Crypto (−14 to +12)

Includes Fear & Greed (±2), BTC vs 200MA (±1), dominance (±1), RV30 (±1), 200WMA (±1), ATH distance (−1 to +2), Pi Cycle (0 to −2), 90d momentum (±1), and 4-year cycle (−2 to +2).

**Verdict:** ≥ +2 Risk-On | ≤ −2 Risk-Off | else Neutral

### Macro (−9 to +8)

Includes yield curve (−2 to +2), 10Y yield (±1), DXY (±1), oil (±1), HYG (±1), STLFSI (−2 to +1), **MOVE** (±1), and **HY credit spread** (±1).

**Verdict:** ≥ +2 Risk-On | ≤ −2 Risk-Off | else Neutral

---

## Equity/Bond Split Logic

The Betterment target recommendation starts from an 80/20 base and adjusts:

| Factor | Effect |
|---|---|
| Equity regime score | ±15pp proportional to score |
| Macro regime score | ±10pp proportional to score |
| MOVE > 130 | +5pp equity (bond vol too high) |
| MOVE < 80 | −5pp equity (bonds attractive) |
| HY Spread > 5% | −10pp equity (credit stress) |
| HY Spread < 3% | +5pp equity (risk appetite) |
| Yield curve deeply inverted | −5pp equity |
| Real yield > 2% | −5pp equity (bonds offer real return) |

Clamped to 40–95% equity.

---

## Notifications

The dashboard fires persistent notifications when:
- Any regime flips (e.g., Equity NEUTRAL → RISK-OFF)
- Any allocation recommendation shifts ≥ 10 percentage points

Notifications appear as:
1. **In-app toast bar** between the header and tabs — requires clicking "Dismiss"
2. **System tray notification** (when available) — persistent until clicked

---

## Project Structure

```
risk-monitor/
├── main.py              # Entry point
├── main_window.py       # Main window, tabs, header, refresh, notification wiring
├── equity_tab.py        # Equity tab layout and data → UI
├── crypto_tab.py        # Crypto tab layout and data → UI
├── macro_tab.py         # Macro tab with MOVE, HY spread, breakevens, real yields
├── portfolio_tab.py     # Portfolio: ETF/BTC/premium + equity-bond split + IBIT overlay
├── widgets.py           # GaugeWidget, RegimeCard, MetricCard, CycleClockWidget
├── regime.py            # Regime scoring (pure functions, no Qt)
├── data_fetch.py        # All network/data calls (yfinance, CNN, FRED, CoinGecko)
├── workers.py           # QThread wrappers for non-blocking fetches
├── notifications.py     # Toast + system tray notification system
├── requirements.txt
├── .env                 # FRED_API_KEY (not committed)
└── .gitignore
```

---

## Data Sources

| Source | Data |
|---|---|
| [Yahoo Finance](https://finance.yahoo.com) via `yfinance` | VIX, SKEW, SPX, BTC, IBIT, SPY options |
| [CNN Fear & Greed](https://www.cnn.com/markets/fear-and-greed) | Equity sentiment + history |
| [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/) | Crypto Fear & Greed |
| [CoinGecko](https://www.coingecko.com) | BTC dominance |
| [FRED](https://fred.stlouisfed.org) | STLFSI4, MOVE, BAMLH0A0HYM2, T5YIE, T10YIE, DFII10, DGS1MO |

---

## Dependencies

```
PyQt6>=6.5.0
pyqtgraph>=0.13.3
yfinance>=0.2.36
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
pandas-datareader>=0.10.0
python-dotenv>=1.0.0
```
