import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                              QVBoxLayout, QWidget)

from regime import compute_crypto_regime
from widgets import COLORS, GaugeWidget, MetricCard, RegimeCard, regime_color

_CHART_OPTIONS = ["BTC Price", "30d Realized Vol", "ETH/BTC Ratio"]

_CHART_COLORS = {
    "BTC Price":      "#f7931a",
    "30d Realized Vol": "#f85149",
    "ETH/BTC Ratio":  "#58a6ff",
}


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
        self._setup_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']}; color: {COLORS['text_primary']};")
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        root.addLayout(self._build_top_row())
        root.addLayout(self._build_cards_row())
        root.addWidget(self._build_chart_panel(), stretch=1)

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.regime_card = RegimeCard()
        row.addWidget(self.regime_card, stretch=1)

        self.gauge = GaugeWidget("Crypto Fear & Greed")
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
            f"color: {COLORS['text_secondary']}; font-size: 9px; font-weight: bold; border: none;"
        )
        lay.addWidget(hdr)

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px; border: none;")
            return l

        self.lbl_btc_ma  = _lbl("BTC vs 200MA: —")
        self.lbl_dom     = _lbl("BTC Dominance: —")
        self.lbl_rv      = _lbl("30d Realized Vol: —")
        self.lbl_ethbtc  = _lbl("ETH/BTC: —")

        for l in (self.lbl_btc_ma, self.lbl_dom, self.lbl_rv, self.lbl_ethbtc):
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
        self.card_eth    = MetricCard("ETH PRICE")
        self.card_ebtc   = MetricCard("ETH/BTC")

        for c in (self.card_btc, self.card_fg, self.card_dom,
                  self.card_rv, self.card_eth, self.card_ebtc):
            row.addWidget(c)
        return row

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
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px; border: none;")
        ctrl.addWidget(lbl)

        self.chart_selector = QComboBox()
        self.chart_selector.setStyleSheet(
            f"QComboBox {{ background: {COLORS['bg']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 4px; "
            f"padding: 2px 6px; font-size: 10px; }}"
        )
        self.chart_selector.addItems(_CHART_OPTIONS)
        self.chart_selector.currentIndexChanged.connect(self._render_chart)
        ctrl.addWidget(self.chart_selector)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(180)
        self.plot.showGrid(x=False, y=True, alpha=0.15)
        self.plot.getPlotItem().getAxis("left").setPen(pg.mkPen(color="#30363d"))
        self.plot.getPlotItem().getAxis("bottom").setPen(pg.mkPen(color="#30363d"))
        self.plot.getPlotItem().getAxis("left").setTextPen(pg.mkPen(color="#8b949e"))
        self.plot.getPlotItem().getAxis("bottom").setTextPen(pg.mkPen(color="#8b949e"))
        lay.addWidget(self.plot)
        return frame

    # ── Data update ────────────────────────────────────────────────────────────

    def update_data(self, data: dict) -> None:
        self._data = data
        regime = compute_crypto_regime(data)
        self.regime_card.set_regime(regime["regime"], regime["score"], regime["color"])

        self._update_gauge(data)
        self._update_labels(data)
        self._update_cards(data)
        self._store_chart_series(data)
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
            self.lbl_btc_ma.setStyleSheet(f"color: {c}; font-size: 11px; border: none;")
            self.lbl_btc_ma.setText(
                f"BTC vs 200MA: {'ABOVE' if above else 'BELOW'} ({pct:+.1f}%)"
            )

        dom = d.get("btc_dominance")
        if dom is not None:
            c = _dom_color(dom)
            self.lbl_dom.setStyleSheet(f"color: {c}; font-size: 11px; border: none;")
            self.lbl_dom.setText(f"BTC Dominance: {dom:.1f}%")

        rv = d.get("btc_rv30")
        if rv is not None:
            c = _rv_color(rv)
            self.lbl_rv.setStyleSheet(f"color: {c}; font-size: 11px; border: none;")
            self.lbl_rv.setText(f"30d Realized Vol: {rv:.1f}%")

        ebtc = d.get("eth_btc_ratio")
        if ebtc is not None:
            self.lbl_ethbtc.setText(f"ETH/BTC: {ebtc:.5f}")

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

        eth = d.get("eth_price")
        if eth is not None:
            self.card_eth.set_value(f"${eth:,.0f}", "ETH-USD", COLORS["text_primary"])

        ebtc = d.get("eth_btc_ratio")
        if ebtc is not None:
            self.card_ebtc.set_value(f"{ebtc:.5f}", "risk appetite", COLORS["accent"])

    def _store_chart_series(self, d: dict) -> None:
        self._chart_series = {
            "BTC Price":        d.get("btc_hist"),
            "30d Realized Vol": d.get("rv30_hist"),
            "ETH/BTC Ratio":    d.get("eth_btc_hist"),
        }

    # ── Chart rendering ────────────────────────────────────────────────────────

    def _render_chart(self) -> None:
        self.plot.clear()
        key    = self.chart_selector.currentText()
        series = self._chart_series.get(key)

        if series is None or series.empty:
            return

        series = series.dropna()
        if series.empty:
            return

        x = np.arange(len(series))
        y = series.to_numpy(dtype=float)

        self.plot.plot(x, y, pen=pg.mkPen(color=_CHART_COLORS.get(key, "#58a6ff"), width=1.5))

        if key == "BTC Price":
            ma200 = self._data.get("btc_ma200")
            if ma200:
                self.plot.addItem(pg.InfiniteLine(
                    pos=ma200, angle=0,
                    pen=pg.mkPen(color=COLORS["neutral"], width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "30d Realized Vol":
            for level in (40, 80):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
                ))

        self.plot.setTitle(key, color=COLORS["text_secondary"], size="10pt")
