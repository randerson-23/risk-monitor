"""
SQLite logger for regime states and allocation recommendations.

Stores a snapshot on every refresh so you can review how signals
performed over time. Database file: risk_monitor_history.db
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parent / "risk_monitor_history.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            -- Regimes
            eq_regime   TEXT,
            eq_score    INTEGER,
            cr_regime   TEXT,
            cr_score    INTEGER,
            mc_regime   TEXT,
            mc_score    INTEGER,
            overall     TEXT,
            -- Allocations
            betterment_eq_pct   INTEGER,
            betterment_bond_pct INTEGER,
            btc_exposure_pct    INTEGER,
            -- Key metrics
            vix         REAL,
            vix_pctile  REAL,
            spx         REAL,
            btc_price   REAL,
            move        REAL,
            hy_spread   REAL,
            yield_10y   REAL,
            yield_spread REAL,
            real_yield_10y REAL,
            btc_rv30    REAL,
            cnn_fg      REAL,
            crypto_fg   INTEGER,
            -- Premium selling
            spx_sizing  REAL,
            spx_lean    TEXT,
            ibit_sizing REAL,
            -- Factors (JSON)
            eq_factors  TEXT,
            cr_factors  TEXT,
            mc_factors  TEXT,
            bet_drivers TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vol_forecasts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    NOT NULL,
            ticker    TEXT    NOT NULL,
            horizon   INTEGER NOT NULL,
            p5        REAL,
            p25       REAL,
            median    REAL,
            p75       REAL,
            p95       REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_forward (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT    NOT NULL,
            ny_fed_prob  REAL,
            stl_prob     REAL,
            nfci         REAL,
            anfci        REAL
        )
    """)
    conn.commit()
    return conn


def log_vol_forecast(ticker: str, forecast: dict) -> None:
    """Log per-horizon price-cone percentiles from a GARCH forecast result."""
    if not forecast or not forecast.get("ok"):
        return
    try:
        conn = _connect()
        ts = datetime.now().isoformat()
        cone_dates = forecast.get("forecast_dates") or []
        p5 = forecast.get("cone_p5") or []
        p25 = forecast.get("cone_p25") or []
        med = forecast.get("cone_median") or []
        p75 = forecast.get("cone_p75") or []
        p95 = forecast.get("cone_p95") or []
        n = min(len(cone_dates), len(p5), len(p25), len(med), len(p75), len(p95))
        rows = []
        for h in range(n):
            rows.append((ts, ticker, h + 1, p5[h], p25[h], med[h], p75[h], p95[h]))
        conn.executemany("""
            INSERT INTO vol_forecasts (timestamp, ticker, horizon, p5, p25, median, p75, p95)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[history_db] vol_forecast write error: {exc}")


def log_macro_forward(data: dict) -> None:
    """Log recession probs + FCI from a forward-risk fetch."""
    if not data:
        return
    try:
        conn = _connect()
        conn.execute("""
            INSERT INTO macro_forward (timestamp, ny_fed_prob, stl_prob, nfci, anfci)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            data.get("ny_fed_recession_pct"),
            data.get("stl_recession_pct"),
            data.get("nfci"),
            data.get("anfci"),
        ))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[history_db] macro_forward write error: {exc}")


def log_snapshot(
    eq_regime: dict,
    cr_regime: dict,
    mc_regime: dict,
    overall: str,
    betterment_eq_pct: int,
    betterment_bond_pct: int,
    btc_exposure_pct: int,
    equity_data: dict,
    crypto_data: dict,
    macro_data: dict,
    spx_sizing: float = 0,
    spx_lean: str = "",
    ibit_sizing: float = 0,
    bet_drivers: list | None = None,
) -> None:
    """Write one snapshot row. Called after every successful refresh."""
    try:
        conn = _connect()
        conn.execute("""
            INSERT INTO snapshots (
                timestamp,
                eq_regime, eq_score, cr_regime, cr_score, mc_regime, mc_score, overall,
                betterment_eq_pct, betterment_bond_pct, btc_exposure_pct,
                vix, vix_pctile, spx, btc_price, move, hy_spread,
                yield_10y, yield_spread, real_yield_10y, btc_rv30,
                cnn_fg, crypto_fg,
                spx_sizing, spx_lean, ibit_sizing,
                eq_factors, cr_factors, mc_factors, bet_drivers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            eq_regime.get("regime"), eq_regime.get("score"),
            cr_regime.get("regime"), cr_regime.get("score"),
            mc_regime.get("regime"), mc_regime.get("score"),
            overall,
            betterment_eq_pct, betterment_bond_pct, btc_exposure_pct,
            equity_data.get("vix"),
            _vix_pctile(equity_data),
            equity_data.get("spx"),
            crypto_data.get("btc_price"),
            macro_data.get("move"),
            macro_data.get("hy_spread"),
            macro_data.get("yield_10y"),
            macro_data.get("yield_spread"),
            macro_data.get("real_yield_10y"),
            crypto_data.get("btc_rv30"),
            equity_data.get("cnn_fear_greed"),
            crypto_data.get("crypto_fear_greed"),
            spx_sizing, spx_lean, ibit_sizing,
            json.dumps(eq_regime.get("factors", [])),
            json.dumps(cr_regime.get("factors", [])),
            json.dumps(mc_regime.get("factors", [])),
            json.dumps(bet_drivers or []),
        ))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[history_db] write error: {exc}")


def _vix_pctile(equity_data: dict) -> float | None:
    vix = equity_data.get("vix")
    hist = equity_data.get("vix_hist")
    if vix is None or hist is None or hist.empty:
        return None
    import numpy as np
    arr = hist.dropna().to_numpy()
    return round(float((arr < vix).mean() * 100), 1)


def get_recent_snapshots(limit: int = 500) -> list[dict]:
    """Return the most recent snapshots as a list of dicts."""
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM snapshots ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def get_regime_transitions(limit: int = 100) -> list[dict]:
    """Return rows where any regime changed vs the previous row."""
    snapshots = get_recent_snapshots(limit * 3)
    transitions = []
    prev = None
    for s in snapshots:
        if prev is not None:
            changed = []
            for key, label in (("eq_regime", "Equity"), ("cr_regime", "Crypto"), ("mc_regime", "Macro")):
                if s.get(key) != prev.get(key):
                    changed.append(f"{label}: {prev.get(key)} → {s.get(key)}")
            if changed:
                s["_changes"] = changed
                transitions.append(s)
        prev = s
    return transitions[-limit:]
