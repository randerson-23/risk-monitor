import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QPen
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                              QSizePolicy, QVBoxLayout, QWidget)

from forecast_panel import VolForecastPanel
from regime import compute_equity_regime, compute_equity_regime_history
from widgets import COLORS, RiskSentimentWidget, MetricCard, RegimeCard, TearOffFrame, fs, regime_color

# ── Chart metadata ─────────────────────────────────────────────────────────────

_CHART_OPTIONS = ["VIX", "S&P 500", "SKEW", "Breadth (% > 200MA)", "CNN Fear & Greed"]

_CHART_COLORS = {
    "VIX":                 "#f85149",
    "S&P 500":             "#58a6ff",
    "SKEW":                "#d29922",
    "Breadth (% > 200MA)": "#7cb342",
    "CNN Fear & Greed":    "#e07b39",
}


def _vix_color(v: float) -> str:
    if v < 15:  return COLORS["risk_on"]
    if v < 20:  return "#7cb342"
    if v < 25:  return COLORS["neutral"]
    if v < 30:  return "#e07b39"
    return COLORS["risk_off"]


def _fg_color(v: float) -> str:
    if v > 65:  return COLORS["risk_on"]
    if v < 35:  return COLORS["risk_off"]
    return COLORS["neutral"]


def _breadth_color(v: float) -> str:
    if v > 60:  return COLORS["risk_on"]
    if v < 40:  return COLORS["risk_off"]
    return COLORS["neutral"]


def _pc_color(v: float) -> str:
    if v > 1.0:  return COLORS["risk_off"]
    if v < 0.7:  return COLORS["risk_on"]
    return COLORS["neutral"]


# ── Tab ────────────────────────────────────────────────────────────────────────

class EquityTab(QWidget):
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

        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(TearOffFrame("equity.chart", self._build_chart_panel(),
                                    "Equity Chart"), stretch=3)
        self.vol_panel = VolForecastPanel("SPX Vol Forecast (GARCH)")
        mid.addWidget(TearOffFrame("equity.vol", self.vol_panel,
                                    "SPX Vol Forecast"), stretch=2)
        root.addLayout(mid, stretch=1)

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.regime_card = RegimeCard()
        row.addWidget(self.regime_card, stretch=1)

        self.gauge = RiskSentimentWidget("CNN Fear & Greed")
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

        self.lbl_spx_ma   = _lbl("SPX vs 200MA: —")
        self.lbl_vix_reg  = _lbl("VIX Regime: —")
        self.lbl_breadth  = _lbl("Breadth: —")
        self.lbl_pc       = _lbl("Put/Call: —")

        for l in (self.lbl_spx_ma, self.lbl_vix_reg, self.lbl_breadth, self.lbl_pc):
            lay.addWidget(l)
        lay.addStretch()
        return frame

    def _build_cards_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.card_vix     = MetricCard("VIX")
        self.card_skew    = MetricCard("SKEW")
        self.card_pc      = MetricCard("PUT/CALL")
        self.card_breadth = MetricCard("BREADTH")
        self.card_spx     = MetricCard("S&P 500")
        self.card_cnn     = MetricCard("CNN F&G")

        for c in (self.card_vix, self.card_skew, self.card_pc,
                  self.card_breadth, self.card_spx, self.card_cnn):
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
        """Render the GARCH vol/cone result against the cached SPX history."""
        self.vol_panel.update_forecast(fc, price_history=self._data.get("spx_hist"))

    def update_data(self, data: dict) -> None:
        self._data = data
        regime = compute_equity_regime(data)
        self.regime_card.set_regime(regime["regime"], regime["score"], regime["color"])
        if regime.get("factors"):
            self.regime_card.setToolTip("<br>".join(regime["factors"]))

        self._update_gauge(data)
        self._update_labels(data)
        self._update_cards(data)
        self._store_chart_series(data)
        self._regime_hist = compute_equity_regime_history(data)
        self._render_chart()

    def _update_gauge(self, d: dict) -> None:
        fg = d.get("cnn_fear_greed")
        if fg is not None:
            self.gauge.set_value(fg, d.get("cnn_fear_greed_rating", ""))

    def _update_labels(self, d: dict) -> None:
        vix = d.get("vix")
        if vix is not None:
            labels = {(0, 15): "Calm", (15, 20): "Normal",
                      (20, 25): "Elevated", (25, 30): "High", (30, 999): "Extreme Fear"}
            reg = next(v for (lo, hi), v in labels.items() if lo <= vix < hi)
            self.lbl_vix_reg.setText(f"VIX Regime: {reg} ({vix:.1f})")

        above = d.get("spx_above_200ma")
        pct   = d.get("spx_pct_from_200ma")
        if above is not None and pct is not None:
            c = COLORS["risk_on"] if above else COLORS["risk_off"]
            self.lbl_spx_ma.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_spx_ma.setText(f"SPX vs 200MA: {'ABOVE' if above else 'BELOW'} ({pct:+.1f}%)")

        b = d.get("breadth_pct")
        if b is not None:
            c = _breadth_color(b)
            self.lbl_breadth.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_breadth.setText(f"Breadth: {b:.1f}% above 200MA")

        pc = d.get("put_call_ratio")
        if pc is not None:
            c = _pc_color(pc)
            self.lbl_pc.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_pc.setText(f"Put/Call: {pc:.3f}")

    def _update_cards(self, d: dict) -> None:
        def _set_30d_delta(card, hist, fmt="{:+.1f}") -> None:
            """Compute last-vs-30d-ago delta and paint the chip."""
            if hist is None:
                return
            try:
                vals = list(hist.tail(30).values)
                if len(vals) < 2:
                    return
                delta = float(vals[-1]) - float(vals[0])
                color = COLORS["risk_on"] if delta > 0 else COLORS["risk_off"] if delta < 0 else COLORS["neutral"]
                card.set_delta(fmt.format(delta), color)
            except Exception:
                pass

        vix = d.get("vix")
        if vix is not None:
            prev = d.get("vix_prev", vix)
            arrow = "▲" if vix > prev else "▼" if vix < prev else ""
            self.card_vix.set_value(f"{vix:.1f} {arrow}".strip(),
                                    f"prev {prev:.1f}", _vix_color(vix))
            if d.get("vix_hist") is not None:
                self.card_vix.set_sparkline(list(d["vix_hist"].tail(60).values))
            d_vix = vix - prev
            if d_vix != 0:
                dc = COLORS["risk_off"] if d_vix > 0 else COLORS["risk_on"]
                self.card_vix.set_delta(f"{d_vix:+.1f}", dc)

        skew = d.get("skew")
        if skew is not None:
            c = COLORS["risk_off"] if skew > 145 else (COLORS["risk_on"] if skew < 120 else COLORS["neutral"])
            self.card_skew.set_value(f"{skew:.1f}", "tail risk", c)
            if d.get("skew_hist") is not None:
                self.card_skew.set_sparkline(list(d["skew_hist"].tail(60).values))
                _set_30d_delta(self.card_skew, d["skew_hist"])

        pc = d.get("put_call_ratio")
        if pc is not None:
            self.card_pc.set_value(f"{pc:.3f}", "put/call vol", _pc_color(pc))

        b = d.get("breadth_pct")
        if b is not None:
            self.card_breadth.set_value(f"{b:.1f}%", "above 200MA", _breadth_color(b))
            if d.get("breadth_hist") is not None:
                self.card_breadth.set_sparkline(list(d["breadth_hist"].tail(60).values))
                _set_30d_delta(self.card_breadth, d["breadth_hist"], fmt="{:+.0f}pp")

        spx = d.get("spx")
        if spx is not None:
            ma  = d.get("spx_ma200", 0)
            c   = regime_color(d.get("spx_above_200ma"))
            self.card_spx.set_value(f"{spx:,.0f}", f"ma200 {ma:,.0f}", c)
            if d.get("spx_hist") is not None:
                self.card_spx.set_sparkline(list(d["spx_hist"].tail(60).values))
                try:
                    hist = d["spx_hist"].tail(30)
                    pct = (float(hist.iloc[-1]) / float(hist.iloc[0]) - 1.0) * 100
                    dc = COLORS["risk_on"] if pct > 0 else COLORS["risk_off"] if pct < 0 else COLORS["neutral"]
                    self.card_spx.set_delta(f"{pct:+.1f}%", dc)
                except Exception:
                    pass

        fg = d.get("cnn_fear_greed")
        if fg is not None:
            self.card_cnn.set_value(f"{fg:.0f}",
                                    d.get("cnn_fear_greed_rating", ""), _fg_color(fg))
            if d.get("cnn_fg_hist") is not None:
                self.card_cnn.set_sparkline(list(d["cnn_fg_hist"].tail(60).values))
                _set_30d_delta(self.card_cnn, d["cnn_fg_hist"], fmt="{:+.0f}")

    def _store_chart_series(self, d: dict) -> None:
        self._chart_series = {
            "VIX":                 d.get("vix_hist"),
            "S&P 500":             d.get("spx_hist"),
            "SKEW":                d.get("skew_hist"),
            "Breadth (% > 200MA)": d.get("breadth_hist"),
            "CNN Fear & Greed":    d.get("cnn_fg_hist"),
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

        x = np.array([ts.timestamp() for ts in series.index])
        y = series.to_numpy(dtype=float)

        self._add_regime_overlay(series)
        self.plot.plot(x, y, pen=pg.mkPen(color=_CHART_COLORS.get(key, "#58a6ff"), width=1.5))

        # Reference lines
        if key == "VIX":
            for level, color in ((20, COLORS["neutral"]), (30, COLORS["risk_off"])):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "S&P 500":
            ma200 = self._data.get("spx_ma200")
            if ma200:
                self.plot.addItem(pg.InfiniteLine(
                    pos=ma200, angle=0,
                    pen=pg.mkPen(color=COLORS["neutral"], width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "CNN Fear & Greed":
            for level in (25, 75):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
                ))

        self.plot.setTitle(key, color=COLORS["text_secondary"], size="10pt")

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
