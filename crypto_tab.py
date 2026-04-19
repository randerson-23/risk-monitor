from datetime import datetime

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                              QVBoxLayout, QWidget)

from forecast_panel import VolForecastPanel
from regime import compute_crypto_regime, compute_crypto_regime_history
from widgets import COLORS, RiskSentimentWidget, MetricCard, RegimeCard, TearOffFrame, fs, regime_color

_CHART_OPTIONS = ["BTC Price", "30d Realized Vol", "Hash Rate", "Funding Rate", "Open Interest",
                  "MVRV", "Net Liquidity", "US M2", "BTC Dominance", "Rainbow Chart"]

_CHART_COLORS = {
    "BTC Price":        "#f7931a",
    "30d Realized Vol": "#f85149",
    "Hash Rate":        "#58a6ff",
    "Funding Rate":     "#d29922",
    "Open Interest":    "#bc8cff",
    "MVRV":             "#58a6ff",
    "Net Liquidity":    "#3fb950",
    "US M2":            "#79c0ff",
    "BTC Dominance":    "#f7931a",
    "Rainbow Chart":    "#f7931a",
}

_RAINBOW_BANDS = [
    ("Maximum Bubble",   +1.2,  "#7d0000"),
    ("Sell Seriously",   +0.8,  "#c0392b"),
    ("FOMO",             +0.45, "#e74c3c"),
    ("Is This a Bubble", +0.15, "#f39c12"),
    ("HODL",             -0.10, "#f1c40f"),
    ("Still Cheap",      -0.40, "#2ecc71"),
    ("Buy",              -0.70, "#27ae60"),
    ("Fire Sale",        -1.00, "#145a32"),
]


def _fg_color(v: float) -> str:
    if v >= 55:  return COLORS["risk_on"]
    if v <= 45:  return COLORS["risk_off"]
    return COLORS["neutral"]


def _rv_color(v: float) -> str:
    if v > 80:  return COLORS["risk_off"]
    if v < 40:  return COLORS["risk_on"]
    return COLORS["neutral"]


def _dom_color(v: float) -> str:
    if v > 58:  return COLORS["neutral"]
    if v < 45:  return COLORS["accent"]
    return COLORS["text_primary"]


class CryptoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = {}
        self._chart_series: dict = {}
        self._regime_hist: pd.Series | None = None
        self._setup_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']}; color: {COLORS['text_primary']};")
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        root.addLayout(self._build_top_row())
        root.addLayout(self._build_cards_row())
        root.addLayout(self._build_onchain_row())

        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(TearOffFrame("crypto.chart", self._build_chart_panel(),
                                    "Bitcoin Chart"), stretch=3)
        self.vol_panel = VolForecastPanel("BTC Vol Forecast (GARCH)")
        mid.addWidget(TearOffFrame("crypto.vol", self.vol_panel,
                                    "BTC Vol Forecast"), stretch=2)
        root.addLayout(mid, stretch=1)

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.regime_card = RegimeCard()
        row.addWidget(self.regime_card, stretch=1)

        self.gauge = RiskSentimentWidget("Crypto Fear & Greed")
        row.addWidget(self.gauge, stretch=2)

        row.addWidget(self._build_stats_panel(), stretch=1)
        return row

    def _build_stats_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setSpacing(5)
        lay.setContentsMargins(12, 10, 12, 10)

        hdr = QLabel("INDICATORS")
        hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; font-weight: bold; border: none;"
        )
        lay.addWidget(hdr)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; border: none;")
            return l

        self.lbl_btc_ma  = _lbl("BTC vs 200MA: —")
        self.lbl_btc_wma = _lbl("BTC vs 200WMA: —")
        self.lbl_ath     = _lbl("ATH Distance: —")
        self.lbl_pi      = _lbl("Pi Cycle: —")
        self.lbl_mom90   = _lbl("90d Momentum: —")
        self.lbl_dom     = _lbl("BTC Dominance: —")
        self.lbl_rv      = _lbl("30d Realized Vol: —")
        self.lbl_mvrv    = _lbl("MVRV: —")

        for l in (self.lbl_btc_ma, self.lbl_btc_wma, self.lbl_ath,
                  self.lbl_pi, self.lbl_mom90, self.lbl_dom, self.lbl_rv,
                  self.lbl_mvrv):
            lay.addWidget(l)
        lay.addStretch()
        return frame

    def _build_cards_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.card_btc    = MetricCard("BTC PRICE")
        self.card_fg     = MetricCard("FEAR & GREED")
        self.card_dom    = MetricCard("BTC DOM")
        self.card_rv     = MetricCard("REALIZED VOL")

        for c in (self.card_btc, self.card_fg, self.card_dom, self.card_rv):
            row.addWidget(c)
        return row

    def _build_onchain_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._build_network_health_panel(), stretch=1)
        row.addWidget(self._build_derivatives_panel(), stretch=1)
        return row

    def _build_network_health_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setSpacing(4)
        lay.setContentsMargins(12, 10, 12, 10)

        hdr = QLabel("NETWORK HEALTH")
        hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; font-weight: bold; border: none;"
        )
        lay.addWidget(hdr)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; border: none;")
            return l

        self.lbl_hash_rate       = _lbl("Hash Rate: —")
        self.lbl_hash_rate_trend = _lbl("30d Trend: —")
        self.lbl_difficulty      = _lbl("Diff Adj: —")
        self.lbl_active_addr     = _lbl("Active Addrs: —")
        self.lbl_net_liq         = _lbl("Net Liquidity: —")
        self.lbl_m2              = _lbl("US M2: —")

        for l in (self.lbl_hash_rate, self.lbl_hash_rate_trend,
                  self.lbl_difficulty, self.lbl_active_addr,
                  self.lbl_net_liq, self.lbl_m2):
            lay.addWidget(l)
        lay.addStretch()
        return frame

    def _build_derivatives_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setSpacing(4)
        lay.setContentsMargins(12, 10, 12, 10)

        hdr = QLabel("DERIVATIVES")
        hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; font-weight: bold; border: none;"
        )
        lay.addWidget(hdr)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; border: none;")
            return l

        self.lbl_funding_cur   = _lbl("Funding (current): —")
        self.lbl_funding_avg   = _lbl("Funding (24h avg): —")
        self.lbl_ls_ratio      = _lbl("Long/Short Ratio: —")
        self.lbl_open_interest = _lbl("Open Interest: —")
        self.lbl_oi_trend      = _lbl("OI 30d Change: —")

        for l in (self.lbl_funding_cur, self.lbl_funding_avg,
                  self.lbl_ls_ratio, self.lbl_open_interest, self.lbl_oi_trend):
            lay.addWidget(l)
        lay.addStretch()
        return frame

    def _build_chart_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        ctrl = QHBoxLayout()
        lbl = QLabel("Chart:")
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; border: none;")
        ctrl.addWidget(lbl)

        self.chart_selector = QComboBox()
        self.chart_selector.setStyleSheet(
            f"QComboBox {{ background: {COLORS['bg']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 4px; "
            f"padding: 2px 6px; font-size: {fs(13)}px; }}"
        )
        self.chart_selector.addItems(_CHART_OPTIONS)
        self.chart_selector.currentIndexChanged.connect(self._render_chart)
        ctrl.addWidget(self.chart_selector)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        date_axis = pg.DateAxisItem(orientation="bottom")
        self.plot = pg.PlotWidget(axisItems={"bottom": date_axis})
        self.plot.setMinimumHeight(180)
        self.plot.showGrid(x=False, y=True, alpha=0.15)
        self.plot.getPlotItem().getAxis("left").setPen(pg.mkPen(color="#30363d"))
        self.plot.getPlotItem().getAxis("bottom").setPen(pg.mkPen(color="#30363d"))
        self.plot.getPlotItem().getAxis("left").setTextPen(pg.mkPen(color="#8b949e"))
        self.plot.getPlotItem().getAxis("bottom").setTextPen(pg.mkPen(color="#8b949e"))
        lay.addWidget(self.plot)
        return frame

    # ── Data update ────────────────────────────────────────────────────────────

    def update_forecast(self, fc: dict) -> None:
        self.vol_panel.update_forecast(fc, price_history=self._data.get("btc_hist"))

    def update_data(self, data: dict) -> None:
        self._data = data
        regime = compute_crypto_regime(data)
        self.regime_card.set_regime(regime["regime"], regime["score"], regime["color"])
        if regime.get("factors"):
            self.regime_card.setToolTip("<br>".join(regime["factors"]))

        self._update_gauge(data)
        self._update_labels(data)
        self._update_cards(data)
        self._update_network_labels(data)
        self._update_derivatives_labels(data)
        self._store_chart_series(data)
        self._regime_hist = compute_crypto_regime_history(data)
        self._render_chart()

    def _update_gauge(self, d: dict) -> None:
        fg = d.get("crypto_fear_greed")
        if fg is not None:
            self.gauge.set_value(float(fg), d.get("crypto_fear_greed_rating", ""))

    def _update_labels(self, d: dict) -> None:
        above = d.get("btc_above_200ma")
        pct   = d.get("btc_pct_from_200ma")
        if above is not None and pct is not None:
            c = COLORS["risk_on"] if above else COLORS["risk_off"]
            self.lbl_btc_ma.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_btc_ma.setText(
                f"BTC vs 200MA: {'ABOVE' if above else 'BELOW'} ({pct:+.1f}%)"
            )

        wma_above = d.get("btc_above_wma200")
        wma_pct   = d.get("btc_pct_from_wma200")
        if wma_above is not None and wma_pct is not None:
            c = COLORS["risk_on"] if wma_above else COLORS["risk_off"]
            self.lbl_btc_wma.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_btc_wma.setText(
                f"BTC vs 200WMA: {'ABOVE' if wma_above else 'BELOW'} ({wma_pct:+.1f}%)"
            )

        pct_ath = d.get("btc_pct_from_ath")
        if pct_ath is not None:
            if pct_ath < -60:   c = COLORS["risk_on"]
            elif pct_ath < -35: c = COLORS["neutral"]
            elif pct_ath > -10: c = COLORS["risk_off"]
            else:               c = COLORS["text_primary"]
            self.lbl_ath.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_ath.setText(f"ATH Distance: {pct_ath:.1f}%")

        pi_ratio = d.get("btc_pi_ratio")
        if pi_ratio is not None:
            if pi_ratio >= 0.97:   c = COLORS["risk_off"]
            elif pi_ratio >= 0.90: c = COLORS["neutral"]
            else:                  c = COLORS["risk_on"]
            self.lbl_pi.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_pi.setText(f"Pi Cycle: {pi_ratio:.3f}  (top > 1.0)")

        mom90 = d.get("btc_mom90")
        if mom90 is not None:
            c = COLORS["risk_on"] if mom90 > 20 else (COLORS["risk_off"] if mom90 < -20 else COLORS["neutral"])
            self.lbl_mom90.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_mom90.setText(f"90d Momentum: {mom90:+.1f}%")

        dom = d.get("btc_dominance")
        if dom is not None:
            c = _dom_color(dom)
            self.lbl_dom.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_dom.setText(f"BTC Dominance: {dom:.1f}%")

        rv = d.get("btc_rv30")
        if rv is not None:
            c = _rv_color(rv)
            self.lbl_rv.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_rv.setText(f"30d Realized Vol: {rv:.1f}%")

        mvrv = d.get("mvrv")
        if mvrv is not None:
            if mvrv < 1.0:   c = COLORS["risk_on"]
            elif mvrv < 1.5: c = COLORS["risk_on"]
            elif mvrv < 3.0: c = COLORS["neutral"]
            elif mvrv < 4.0: c = COLORS["risk_off"]
            else:             c = COLORS["risk_off"]
            self.lbl_mvrv.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_mvrv.setText(f"MVRV: {mvrv:.3f}")

    def _update_cards(self, d: dict) -> None:
        btc = d.get("btc_price")
        if btc is not None:
            c   = regime_color(d.get("btc_above_200ma"))
            ma  = d.get("btc_ma200", 0)
            self.card_btc.set_value(f"${btc:,.0f}", f"ma200 ${ma:,.0f}", c)

        fg = d.get("crypto_fear_greed")
        if fg is not None:
            self.card_fg.set_value(
                str(fg), d.get("crypto_fear_greed_rating", ""), _fg_color(float(fg))
            )

        dom = d.get("btc_dominance")
        if dom is not None:
            self.card_dom.set_value(f"{dom:.1f}%", "dominance", _dom_color(dom))

        rv = d.get("btc_rv30")
        if rv is not None:
            self.card_rv.set_value(f"{rv:.1f}%", "annualized", _rv_color(rv))

    def _update_network_labels(self, d: dict) -> None:
        hr = d.get("hash_rate")
        if hr is not None:
            self.lbl_hash_rate.setText(f"Hash Rate: {hr:.1f} EH/s")

        hr_chg = d.get("hash_rate_pct_30d")
        if hr_chg is not None:
            c = COLORS["risk_on"] if hr_chg > 0 else (COLORS["risk_off"] if hr_chg < -10 else COLORS["neutral"])
            self.lbl_hash_rate_trend.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_hash_rate_trend.setText(f"30d Trend: {hr_chg:+.1f}%")

        diff_pct = d.get("difficulty_adj_pct")
        diff_eta = d.get("difficulty_adj_eta_days")
        if diff_pct is not None:
            c = COLORS["risk_on"] if diff_pct > 0 else COLORS["risk_off"]
            self.lbl_difficulty.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            eta_str = f"  (ETA {diff_eta:.0f}d)" if diff_eta is not None else ""
            self.lbl_difficulty.setText(f"Diff Adj: {diff_pct:+.1f}%{eta_str}")

        addr = d.get("active_addresses")
        if addr is not None:
            self.lbl_active_addr.setText(f"Active Addrs: {addr:,}")

        liq = d.get("net_liquidity")
        liq_chg = d.get("net_liquidity_change_30d")
        if liq is not None:
            c = COLORS["risk_on"] if (liq_chg or 0) > 0 else COLORS["risk_off"]
            chg_str = f"  ({liq_chg:+.1f}%)" if liq_chg is not None else ""
            self.lbl_net_liq.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_net_liq.setText(f"Net Liquidity: ${liq:,.0f}B{chg_str}")

        m2 = d.get("m2_usd")
        m2_chg = d.get("m2_change_1y")
        if m2 is not None:
            c = COLORS["risk_on"] if (m2_chg or 0) > 0 else COLORS["neutral"]
            chg_str = f"  ({m2_chg:+.1f}% 1Y)" if m2_chg is not None else ""
            self.lbl_m2.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_m2.setText(f"US M2: ${m2:,.0f}B{chg_str}")

    def _update_derivatives_labels(self, d: dict) -> None:
        def _funding_color(v: float) -> str:
            if v < -0.01:  return COLORS["risk_on"]
            if v > 0.05:   return COLORS["risk_off"]
            return COLORS["neutral"]

        fc = d.get("funding_rate_current")
        if fc is not None:
            c = _funding_color(fc)
            self.lbl_funding_cur.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_funding_cur.setText(f"Funding (current): {fc:+.4f}%")

        fa = d.get("funding_rate_avg24h")
        if fa is not None:
            c = _funding_color(fa)
            self.lbl_funding_avg.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_funding_avg.setText(f"Funding (24h avg): {fa:+.4f}%")

        ls = d.get("ls_ratio")
        if ls is not None:
            c = COLORS["risk_on"] if ls < 0.9 else (COLORS["risk_off"] if ls > 1.2 else COLORS["neutral"])
            self.lbl_ls_ratio.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_ls_ratio.setText(f"Long/Short Ratio: {ls:.3f}")

        oi = d.get("open_interest")
        if oi is not None:
            self.lbl_open_interest.setText(f"Open Interest: ${oi:.2f}B")

        oi_chg = d.get("oi_pct_change_30d")
        if oi_chg is not None:
            c = COLORS["risk_on"] if oi_chg > 0 else COLORS["risk_off"]
            self.lbl_oi_trend.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_oi_trend.setText(f"OI 30d Change: {oi_chg:+.1f}%")

    def _store_chart_series(self, d: dict) -> None:
        self._chart_series = {
            "BTC Price":        d.get("btc_hist"),
            "30d Realized Vol": d.get("rv30_hist"),
            "Hash Rate":        d.get("hash_rate_hist"),
            "Funding Rate":     d.get("funding_rate_hist"),
            "Open Interest":    d.get("oi_hist"),
            "MVRV":             d.get("mvrv_hist"),
            "Net Liquidity":    d.get("net_liquidity_hist"),
            "US M2":            d.get("m2_hist"),
            "BTC Dominance":    d.get("btc_dom_hist"),
            "Rainbow Chart":    d.get("btc_hist_max"),
        }

    # ── Chart rendering ────────────────────────────────────────────────────────

    def _render_chart(self) -> None:
        self.plot.clear()
        self.plot.setLogMode(y=False)
        self.plot.getPlotItem().getAxis("left").setTicks(None)  # reset custom ticks
        key    = self.chart_selector.currentText()

        if key == "Rainbow Chart":
            self._render_rainbow()
            return

        series = self._chart_series.get(key)
        if series is None or series.empty:
            return
        series = series.dropna()
        if series.empty:
            return

        x = np.array([ts.timestamp() for ts in series.index])
        y = series.to_numpy(dtype=float)

        self._add_regime_overlay(series)
        self.plot.plot(x, y, pen=pg.mkPen(color=_CHART_COLORS.get(key, "#58a6ff"), width=1.5))

        if key == "BTC Price":
            ma200 = self._data.get("btc_ma200")
            if ma200:
                self.plot.addItem(pg.InfiniteLine(
                    pos=ma200, angle=0,
                    pen=pg.mkPen(color=COLORS["neutral"], width=1, style=Qt.PenStyle.DashLine)
                ))
            wma200 = self._data.get("btc_wma200")
            if wma200:
                self.plot.addItem(pg.InfiniteLine(
                    pos=wma200, angle=0,
                    pen=pg.mkPen(color=COLORS["risk_on"], width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "30d Realized Vol":
            for level in (40, 80):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "Funding Rate":
            self.plot.addItem(pg.InfiniteLine(
                pos=0, angle=0,
                pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
            ))
        elif key == "MVRV":
            for level, label_color in ((1.0, COLORS["risk_on"]), (3.5, COLORS["risk_off"])):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=label_color, width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "Net Liquidity":
            # Add a simple 13-week (≈3 month) moving average overlay
            if series is not None and len(series) >= 13:
                ma = series.rolling(13).mean().dropna()
                xm = np.array([ts.timestamp() for ts in ma.index])
                self.plot.plot(xm, ma.to_numpy(dtype=float),
                               pen=pg.mkPen(color=COLORS["neutral"], width=1,
                                            style=Qt.PenStyle.DashLine))

        self.plot.setTitle(key, color=COLORS["text_secondary"], size="10pt")

    def _render_rainbow(self) -> None:
        coeffs = self._data.get("rainbow_coeffs")
        hist   = self._data.get("btc_hist_max")
        if not coeffs or hist is None or hist.empty:
            self.plot.setTitle("Rainbow Chart (no data)", color=COLORS["text_secondary"], size="10pt")
            return

        a, b = coeffs
        genesis = datetime(2009, 1, 3)

        # Build arrays; all points are valid (yfinance starts 2014, well after genesis)
        x_ts     = np.array([pd.Timestamp(ts).timestamp() for ts in hist.index])
        days_arr = np.array(
            [(pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None) - genesis).days
             for ts in hist.index],
            dtype=float,
        )
        # Filter any edge-case negatives (shouldn't occur with 2014+ data)
        valid    = days_arr > 0
        x_ts     = x_ts[valid]
        days_v   = days_arr[valid]
        prices_v = hist.values[valid]

        # ── Plot everything in log10(price) space so FillBetweenItem works ──
        # Regression in natural log → convert to log10: log10(x) = ln(x)/ln(10)
        LN10 = np.log(10)

        band_curves = []
        band_colors = []
        for _name, offset, color in _RAINBOW_BANDS:
            # log10 of band price at each date
            log10_band = (a + b * np.log(days_v) + offset) / LN10
            curve = self.plot.plot(x_ts, log10_band,
                                   pen=pg.mkPen(color=color, width=1))
            band_curves.append(curve)
            band_colors.append(color)

        # Fill between adjacent band pairs (works correctly in linear log10 space)
        for i in range(len(band_curves) - 1):
            c = QColor(band_colors[i])
            c.setAlpha(90)
            fill = pg.FillBetweenItem(band_curves[i], band_curves[i + 1],
                                      brush=QBrush(c))
            self.plot.addItem(fill)

        # BTC price in log10 — white line on top
        self.plot.plot(x_ts, np.log10(prices_v),
                       pen=pg.mkPen(color="#ffffff", width=2))

        # Y-axis tick labels: convert log10 values back to dollar amounts
        price_levels = [100, 1_000, 10_000, 100_000, 1_000_000]
        ticks = [(np.log10(p), f"${p:,}") for p in price_levels]
        self.plot.getPlotItem().getAxis("left").setTicks([ticks])

        self.plot.setTitle("Rainbow Chart  (log regression · log10 scale)",
                           color=COLORS["text_secondary"], size="10pt")

    def _add_regime_overlay(self, series: pd.Series) -> None:
        if self._regime_hist is None or self._regime_hist.empty:
            return

        idx = pd.to_datetime(series.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        idx = idx.normalize()

        aligned = self._regime_hist.reindex(idx, method="ffill")
        x_ts = np.array([ts.timestamp() for ts in series.index])

        color_map = {
            "RISK-ON":  QColor(63, 185, 80, 60),
            "NEUTRAL":  QColor(210, 153, 34, 60),
            "RISK-OFF": QColor(248, 81, 73, 60),
        }

        prev = None
        start_x = None

        for i, label in enumerate(aligned):
            if pd.isna(label) or label is None:
                if prev is not None:
                    self._draw_regime_region(start_x, x_ts[i - 1], prev, color_map)
                    prev = None
                continue
            if label != prev:
                if prev is not None:
                    self._draw_regime_region(start_x, x_ts[i], prev, color_map)
                prev = label
                start_x = x_ts[i]

        if prev is not None and start_x is not None:
            self._draw_regime_region(start_x, x_ts[-1], prev, color_map)

    def _draw_regime_region(self, x0, x1, label, color_map):
        item = pg.LinearRegionItem(
            values=[x0, x1],
            orientation="vertical",
            brush=QBrush(color_map.get(label, QColor(0, 0, 0, 0))),
            pen=pg.mkPen(None),
            movable=False,
        )
        item.setZValue(-10)
        self.plot.addItem(item)
