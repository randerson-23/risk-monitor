# Risk Monitor

A PyQt6 desktop dashboard for monitoring market risk sentiment across equities and crypto. Designed to give you a clear picture of the current market regime before entering a trade — without being tied to any personal portfolio.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.5%2B-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Overview

Risk Monitor aggregates publicly available fear/greed scores, volatility indices, trend signals, and market breadth indicators into a single dark-themed dashboard. All data is fetched in background threads so the UI stays responsive, and everything refreshes automatically every 5 minutes.

---

## Features

- **Regime classification** — each tab scores multiple indicators and outputs a single Risk-On / Neutral / Risk-Off verdict
- **Fear & Greed gauge** — semicircular visual gauge for both equity (CNN) and crypto (Alternative.me) sentiment scores
- **Metric cards** — colour-coded tiles for every individual indicator, updating on each refresh
- **Toggleable chart** — a pyqtgraph chart at the bottom of each tab that can be switched between different data series
- **Non-blocking data fetching** — all network calls run in `QThread` workers; the UI never freezes
- **Auto-refresh** — data reloads every 5 minutes; manual refresh button also available

---

## Tabs

### Equities

| Metric | Source | Notes |
|---|---|---|
| CNN Fear & Greed | CNN (unofficial endpoint) | 0–100 gauge |
| VIX | Yahoo Finance `^VIX` | CBOE Volatility Index |
| SKEW Index | Yahoo Finance `^SKEW` | Tail-risk gauge |
| Put/Call Ratio | Yahoo Finance (SPY options chain) | Nearest-expiry volume ratio |
| Market Breadth | Yahoo Finance `^NY200R` / `MMTH` | % of stocks trading above their 200-day MA |
| S&P 500 vs 200 MA | Yahoo Finance `^GSPC` | Trend regime signal |

**Chart options:** VIX, S&P 500, SKEW, Breadth, CNN Fear & Greed

### Crypto

| Metric | Source | Notes |
|---|---|---|
| Crypto Fear & Greed | Alternative.me API | 0–100 gauge |
| BTC Price vs 200 MA | Yahoo Finance `BTC-USD` | Trend regime signal |
| BTC Dominance | CoinGecko API | % of total crypto market cap |
| 30-day Realized Volatility | Computed from Yahoo Finance | Annualized, rolling 30-day window |
| ETH Price | Yahoo Finance `ETH-USD` | |
| ETH/BTC Ratio | Computed | Risk appetite proxy — rising = alt-season sentiment |

**Chart options:** BTC Price, 30d Realized Vol, ETH/BTC Ratio

---

## Regime Scoring

Each tab computes a numeric score by evaluating individual indicators and sums them into a regime verdict.

### Equity scoring

| Indicator | Condition | Points |
|---|---|---|
| VIX | < 15 | +2 |
| VIX | 15–20 | +1 |
| VIX | 20–25 | −1 |
| VIX | 25–30 | −1 |
| VIX | > 30 | −2 |
| SPX vs 200 MA | Above | +1 |
| SPX vs 200 MA | Below | −1 |
| Put/Call Ratio | < 0.7 (complacent) | +1 |
| Put/Call Ratio | > 1.0 (protective) | −1 |
| Breadth | > 60% | +1 |
| Breadth | < 40% | −1 |
| CNN Fear & Greed | > 65 (greed) | +1 |
| CNN Fear & Greed | < 35 (fear) | −1 |
| SKEW | > 145 (elevated tail risk) | −1 |
| SKEW | < 120 (low tail risk) | +1 |

**Verdict:** score ≥ +3 → Risk-On | score ≤ −2 → Risk-Off | else → Neutral

### Crypto scoring

| Indicator | Condition | Points |
|---|---|---|
| Fear & Greed | ≥ 75 (extreme greed) | +2 |
| Fear & Greed | 55–74 (greed) | +1 |
| Fear & Greed | 46–54 (neutral) | 0 |
| Fear & Greed | 26–45 (fear) | −1 |
| Fear & Greed | ≤ 25 (extreme fear) | −2 |
| BTC vs 200 MA | Above | +1 |
| BTC vs 200 MA | Below | −1 |
| BTC Dominance | > 58% (capital rotating to BTC safety) | −1 |
| BTC Dominance | < 45% (alt-season) | +1 |
| 30d Realized Vol | < 40% (calm) | +1 |
| 30d Realized Vol | > 80% (extreme) | −1 |

**Verdict:** score ≥ +2 → Risk-On | score ≤ −2 → Risk-Off | else → Neutral

---

## Installation

**Requirements:** Python 3.10+

```bash
git clone https://github.com/randerson-23/risk-monitor.git
cd risk-monitor
pip install -r requirements.txt
python main.py
```

> On Windows, if `python` resolves to Python 2, use `python3` and `pip3` instead.

---

## Project Structure

```
risk-monitor/
├── main.py            # Entry point — creates QApplication, sets pyqtgraph theme
├── main_window.py     # Main window, tab widget, header bar, refresh timer
├── equity_tab.py      # Equity tab layout and data → UI wiring
├── crypto_tab.py      # Crypto tab layout and data → UI wiring
├── widgets.py         # Custom widgets: GaugeWidget, RegimeCard, MetricCard
├── regime.py          # Regime scoring logic (pure functions, no Qt dependency)
├── data_fetch.py      # All network/data calls (yfinance, CNN, Alternative.me, CoinGecko)
├── workers.py         # QThread wrappers for non-blocking data fetches
└── requirements.txt
```

---

## Data Sources

All data is fetched from free, public sources — no API keys required.

| Source | Data |
|---|---|
| [Yahoo Finance](https://finance.yahoo.com) via `yfinance` | VIX, SKEW, SPX, BTC, ETH, SPY options |
| [CNN Fear & Greed](https://www.cnn.com/markets/fear-and-greed) | Equity sentiment score + history |
| [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/) | Crypto Fear & Greed score |
| [CoinGecko](https://www.coingecko.com) | BTC dominance |

> The CNN endpoint is unofficial and subject to change. If it breaks, the CNN F&G card will display blank rather than erroring out.

---

## Dependencies

```
PyQt6>=6.5.0
pyqtgraph>=0.13.3
yfinance>=0.2.36
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
```
