import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                              QVBoxLayout, QWidget)

from regime import compute_macro_regime, compute_macro_regime_history
from widgets import COLORS, CorrelationHeatmap, MetricCard, RegimeCard, fs, regime_color

_CHART_OPTIONS = [
    "10Y Treasury", "Yield Curve", "DXY", "Gold", "Oil",
    "HYG Credit", "STLFSI4", "MOVE Index", "HY Spread",
    "5Y Breakeven", "10Y Real Yield",
]

_CHART_COLORS = {
    "10Y Treasury":   "#58a6ff",
    "Yield Curve":    "#d29922",
    "DXY":            "#e07b39",
    "Gold":           "#ffd700",
    "Oil":            "#7cb342",
    "HYG Credit":     "#f85149",
    "STLFSI4":        "#bc8cff",
    "MOVE Index":     "#ff6b6b",
    "HY Spread":      "#e07b39",
    "5Y Breakeven":   "#4ecdc4",
    "10Y Real Yield": "#45b7d1",
}


def _spread_color(v: float) -> str:
    if v > 1.5:  return COLORS["risk_on"]
    if v < 0:    return COLORS["risk_off"]
    return COLORS["neutral"]


def _yield_color(v: float) -> str:
    if v > 5.0:  return COLORS["risk_off"]
    if v < 3.5:  return COLORS["risk_on"]
    return COLORS["neutral"]


def _dxy_color(above: bool) -> str:
    return COLORS["risk_off"] if above else COLORS["risk_on"]


def _move_color(v: float) -> str:
    if v > 130: return COLORS["risk_off"]
    if v < 80:  return COLORS["risk_on"]
    return COLORS["neutral"]


def _hy_spread_color(v: float) -> str:
    if v > 5.0: return COLORS["risk_off"]
    if v < 3.0: return COLORS["risk_on"]
    return COLORS["neutral"]


class MacroTab(QWidget):
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
        root.addLayout(self._build_cards_row_2())
        root.addLayout(self._build_forward_risk_row())
        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(self._build_chart_panel(), stretch=2)
        mid.addWidget(self._build_corr_panel(), stretch=1)
        root.addLayout(mid, stretch=1)

    def _build_corr_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        hdr = QLabel("CROSS-ASSET CORRELATION  ·  60D")
        hdr.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; font-weight: bold; border: none;")
        lay.addWidget(hdr)
        self._corr_heatmap = CorrelationHeatmap()
        lay.addWidget(self._corr_heatmap, stretch=1)
        return frame

    def _build_forward_risk_row(self) -> QHBoxLayout:
        from widgets import TOKENS as _T
        row = QHBoxLayout()
        row.setSpacing(8)

        self.card_ny_fed = MetricCard("RECESSION  ·  NY FED 12M")
        self.card_stl    = MetricCard("RECESSION  ·  STL SMOOTH")
        self.card_nfci   = MetricCard("FIN CONDITIONS  ·  NFCI")
        self.card_anfci  = MetricCard("ADJ FIN COND  ·  ANFCI")

        for c in (self.card_ny_fed, self.card_stl, self.card_nfci, self.card_anfci):
            row.addWidget(c)
        return row

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.regime_card = RegimeCard()
        row.addWidget(self.regime_card, stretch=1)
        row.addWidget(self._build_stats_panel(), stretch=2)
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

        self.lbl_spread    = _lbl("Yield Curve: —")
        self.lbl_yield10   = _lbl("10Y Yield: —")
        self.lbl_yield3m   = _lbl("3M Yield: —")
        self.lbl_dxy       = _lbl("DXY vs 200MA: —")
        self.lbl_oil       = _lbl("Oil vs 200MA: —")
        self.lbl_gold      = _lbl("Gold vs 200MA: —")
        self.lbl_hyg       = _lbl("HYG vs 200MA: —")
        self.lbl_stlfsi    = _lbl("Financial Stress: —")
        self.lbl_move      = _lbl("MOVE Index: —")
        self.lbl_hy_spread = _lbl("HY Credit Spread: —")
        self.lbl_breakeven = _lbl("5Y Breakeven: —")
        self.lbl_real_yld  = _lbl("10Y Real Yield: —")

        for l in (self.lbl_spread, self.lbl_yield10, self.lbl_yield3m,
                  self.lbl_dxy, self.lbl_oil, self.lbl_gold, self.lbl_hyg,
                  self.lbl_stlfsi, self.lbl_move, self.lbl_hy_spread,
                  self.lbl_breakeven, self.lbl_real_yld):
            lay.addWidget(l)
        lay.addStretch()
        return frame

    def _build_cards_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.card_yield10 = MetricCard("10Y YIELD")
        self.card_yield3m = MetricCard("3M YIELD")
        self.card_spread  = MetricCard("SPREAD")
        self.card_dxy     = MetricCard("DXY")
        self.card_gold    = MetricCard("GOLD")
        self.card_oil     = MetricCard("OIL")

        for c in (self.card_yield10, self.card_yield3m, self.card_spread,
                  self.card_dxy, self.card_gold, self.card_oil):
            row.addWidget(c)
        return row

    def _build_cards_row_2(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.card_hyg      = MetricCard("HYG CREDIT")
        self.card_stlfsi   = MetricCard("FIN STRESS")
        self.card_move     = MetricCard("MOVE")
        self.card_hy_sprd  = MetricCard("HY SPREAD")
        self.card_be5y     = MetricCard("5Y BKEVN")
        self.card_real_yld = MetricCard("REAL YLD")

        for c in (self.card_hyg, self.card_stlfsi, self.card_move,
                  self.card_hy_sprd, self.card_be5y, self.card_real_yld):
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

    def update_data(self, data: dict) -> None:
        self._data = data
        # Merge forward-risk fields if they were stashed earlier
        if hasattr(self, "_fwd_data") and self._fwd_data:
            for k, v in self._fwd_data.items():
                self._data.setdefault(k, v)
        regime = compute_macro_regime(self._data)
        self.regime_card.set_regime(regime["regime"], regime["score"], regime["color"])
        if regime.get("factors"):
            self.regime_card.setToolTip("<br>".join(regime["factors"]))

        self._update_labels(self._data)
        self._update_cards(self._data)
        self._update_forward_risk(self._data)
        self._store_chart_series(self._data)
        self._regime_hist = compute_macro_regime_history(self._data)
        self._render_chart()
        self._render_correlation()

    def _render_correlation(self) -> None:
        # Use whatever histories are available among cross-asset proxies
        candidates = [
            ("SPX", self._data.get("spx_hist")),
            ("BTC", self._data.get("btc_hist")),
            ("DXY", self._data.get("dxy_hist")),
            ("HYG", self._data.get("hyg_hist")),
        ]
        series = []
        labels = []
        for lab, s in candidates:
            if s is None:
                continue
            try:
                ss = pd.Series(s).dropna()
            except Exception:
                continue
            if len(ss) < 30:
                continue
            labels.append(lab)
            series.append(ss)
        if len(series) < 2:
            return
        # Align on common index, take last 60 returns
        df = pd.concat(series, axis=1, join="inner")
        df.columns = labels
        rets = df.pct_change().dropna().tail(60)
        if len(rets) < 10:
            return
        corr = rets.corr().values.tolist()
        self._corr_heatmap.set_matrix(labels, corr)

    def update_forward_risk(self, data: dict) -> None:
        """Apply forward-risk metrics independently of the main macro fetch."""
        self._fwd_data = dict(data)
        self._data.update(data)
        self._update_forward_risk(self._data)
        # Re-evaluate regime so NFCI / NY-Fed-prob factor in
        regime = compute_macro_regime(self._data)
        self.regime_card.set_regime(regime["regime"], regime["score"], regime["color"])
        if regime.get("factors"):
            self.regime_card.setToolTip("<br>".join(regime["factors"]))

    def _update_forward_risk(self, d: dict) -> None:
        ny = d.get("ny_fed_recession_pct")
        if ny is not None:
            c = (COLORS["risk_off"] if ny > 60 else
                 COLORS["neutral"]  if ny > 30 else
                 COLORS["risk_on"])
            sub = f"spread {d.get('ny_fed_spread_pct', 0):+.2f}%"
            self.card_ny_fed.set_value(f"{ny:.0f}%", sub, c)
            if d.get("ny_fed_hist") is not None:
                self.card_ny_fed.set_sparkline(list(d["ny_fed_hist"].tail(60).values))

        stl = d.get("stl_recession_pct")
        if stl is not None:
            c = (COLORS["risk_off"] if stl > 30 else
                 COLORS["neutral"]  if stl > 10 else
                 COLORS["risk_on"])
            self.card_stl.set_value(f"{stl:.1f}%", "12m smoothed", c)
            if d.get("stl_recession_hist") is not None:
                self.card_stl.set_sparkline(list(d["stl_recession_hist"].tail(24).values))

        nfci = d.get("nfci")
        if nfci is not None:
            c = (COLORS["risk_off"] if nfci > 0.5 else
                 COLORS["risk_on"]  if nfci < -0.5 else
                 COLORS["neutral"])
            chg = d.get("nfci_12w")
            sub = f"12w Δ {chg:+.2f}" if chg is not None else "weekly z-score"
            self.card_nfci.set_value(f"{nfci:+.2f}", sub, c)
            if d.get("nfci_hist") is not None:
                self.card_nfci.set_sparkline(list(d["nfci_hist"].tail(60).values))

        anfci = d.get("anfci")
        if anfci is not None:
            c = (COLORS["risk_off"] if anfci > 0.5 else
                 COLORS["risk_on"]  if anfci < -0.5 else
                 COLORS["neutral"])
            self.card_anfci.set_value(f"{anfci:+.2f}", "credit/risk-only", c)
            if d.get("anfci_hist") is not None:
                self.card_anfci.set_sparkline(list(d["anfci_hist"].tail(60).values))

    def _update_labels(self, d: dict) -> None:
        spread = d.get("yield_spread")
        if spread is not None:
            c = _spread_color(spread)
            self.lbl_spread.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            if spread < 0:     desc = "inverted"
            elif spread < 0.5: desc = "flat"
            elif spread < 1.5: desc = "normal"
            else:              desc = "steep"
            self.lbl_spread.setText(f"Yield Curve: {spread:+.2f}% ({desc})")

        y10 = d.get("yield_10y")
        if y10 is not None:
            c = _yield_color(y10)
            self.lbl_yield10.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_yield10.setText(f"10Y Yield: {y10:.3f}%")

        y3m = d.get("yield_3m")
        if y3m is not None:
            self.lbl_yield3m.setText(f"3M Yield: {y3m:.3f}%")

        dxy_above = d.get("dxy_above_200ma")
        dxy_pct   = d.get("dxy_pct_from_200ma")
        if dxy_above is not None and dxy_pct is not None:
            c = _dxy_color(dxy_above)
            self.lbl_dxy.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_dxy.setText(
                f"DXY vs 200MA: {'ABOVE' if dxy_above else 'BELOW'} ({dxy_pct:+.1f}%)"
            )

        oil_above = d.get("oil_above_200ma")
        oil_pct   = d.get("oil_pct_from_200ma")
        if oil_above is not None and oil_pct is not None:
            c = regime_color(oil_above)
            self.lbl_oil.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_oil.setText(
                f"Oil vs 200MA: {'ABOVE' if oil_above else 'BELOW'} ({oil_pct:+.1f}%)"
            )

        gold_above = d.get("gold_above_200ma")
        gold_pct   = d.get("gold_pct_from_200ma")
        if gold_above is not None and gold_pct is not None:
            self.lbl_gold.setText(
                f"Gold vs 200MA: {'ABOVE' if gold_above else 'BELOW'} ({gold_pct:+.1f}%)"
            )

        hyg_above = d.get("hyg_above_200ma")
        hyg_pct   = d.get("hyg_pct_from_200ma")
        if hyg_above is not None and hyg_pct is not None:
            c = COLORS["risk_on"] if hyg_above else COLORS["risk_off"]
            self.lbl_hyg.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_hyg.setText(
                f"HYG vs 200MA: {'ABOVE' if hyg_above else 'BELOW'} ({hyg_pct:+.1f}%)"
            )

        stlfsi = d.get("stlfsi")
        if stlfsi is not None:
            if stlfsi > 1.0:   c = COLORS["risk_off"]
            elif stlfsi > 0:   c = COLORS["neutral"]
            elif stlfsi < -0.5: c = COLORS["risk_on"]
            else:               c = COLORS["text_primary"]
            self.lbl_stlfsi.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_stlfsi.setText(f"Financial Stress: {stlfsi:+.3f}")

        move = d.get("move")
        if move is not None:
            c = _move_color(move)
            self.lbl_move.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_move.setText(f"MOVE Index: {move:.0f}")

        hy_spread = d.get("hy_spread")
        if hy_spread is not None:
            c = _hy_spread_color(hy_spread)
            self.lbl_hy_spread.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_hy_spread.setText(f"HY Credit Spread: {hy_spread:.2f}%")

        be5y = d.get("breakeven_5y")
        if be5y is not None:
            c = COLORS["risk_off"] if be5y > 3.0 else (COLORS["risk_on"] if be5y < 2.0 else COLORS["text_primary"])
            self.lbl_breakeven.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_breakeven.setText(f"5Y Breakeven: {be5y:.2f}%")

        real_yld = d.get("real_yield_10y")
        if real_yld is not None:
            c = COLORS["risk_off"] if real_yld > 2.5 else (COLORS["risk_on"] if real_yld < 1.0 else COLORS["text_primary"])
            self.lbl_real_yld.setStyleSheet(f"color: {c}; font-size: {fs(14)}px; border: none;")
            self.lbl_real_yld.setText(f"10Y Real Yield: {real_yld:.2f}%")

    def _update_cards(self, d: dict) -> None:
        y10 = d.get("yield_10y")
        if y10 is not None:
            self.card_yield10.set_value(f"{y10:.3f}%", "10-year", _yield_color(y10))

        y3m = d.get("yield_3m")
        if y3m is not None:
            self.card_yield3m.set_value(f"{y3m:.3f}%", "3-month", COLORS["text_primary"])

        spread = d.get("yield_spread")
        if spread is not None:
            self.card_spread.set_value(f"{spread:+.3f}%", "10Y − 3M", _spread_color(spread))

        dxy = d.get("dxy")
        if dxy is not None:
            above = d.get("dxy_above_200ma")
            ma    = d.get("dxy_ma200", 0)
            c     = _dxy_color(above) if above is not None else COLORS["text_primary"]
            self.card_dxy.set_value(f"{dxy:.1f}", f"ma200 {ma:.1f}", c)

        gold = d.get("gold")
        if gold is not None:
            ma = d.get("gold_ma200", 0)
            self.card_gold.set_value(f"${gold:,.0f}", f"ma200 ${ma:,.0f}", COLORS["text_primary"])

        oil = d.get("oil")
        if oil is not None:
            above = d.get("oil_above_200ma")
            ma    = d.get("oil_ma200", 0)
            self.card_oil.set_value(f"${oil:.1f}", f"ma200 ${ma:.1f}", regime_color(above))

        hyg = d.get("hyg")
        if hyg is not None:
            above = d.get("hyg_above_200ma")
            ma    = d.get("hyg_ma200", 0)
            c = COLORS["risk_on"] if above else COLORS["risk_off"]
            self.card_hyg.set_value(f"${hyg:.2f}", f"ma200 ${ma:.2f}", c)

        stlfsi = d.get("stlfsi")
        if stlfsi is not None:
            if stlfsi > 1.0:    c = COLORS["risk_off"]
            elif stlfsi > 0:    c = COLORS["neutral"]
            elif stlfsi < -0.5: c = COLORS["risk_on"]
            else:               c = COLORS["text_primary"]
            desc = "high stress" if stlfsi > 1 else ("elevated" if stlfsi > 0 else ("relaxed" if stlfsi < -0.5 else "normal"))
            self.card_stlfsi.set_value(f"{stlfsi:+.2f}", desc, c)

        move = d.get("move")
        if move is not None:
            self.card_move.set_value(f"{move:.0f}", "bond vol", _move_color(move))

        hy_spread = d.get("hy_spread")
        if hy_spread is not None:
            self.card_hy_sprd.set_value(f"{hy_spread:.2f}%", "HY OAS", _hy_spread_color(hy_spread))

        be5y = d.get("breakeven_5y")
        if be5y is not None:
            c = COLORS["risk_off"] if be5y > 3.0 else (COLORS["risk_on"] if be5y < 2.0 else COLORS["text_primary"])
            self.card_be5y.set_value(f"{be5y:.2f}%", "inflation exp", c)

        real_yld = d.get("real_yield_10y")
        if real_yld is not None:
            c = COLORS["risk_off"] if real_yld > 2.5 else (COLORS["risk_on"] if real_yld < 1.0 else COLORS["text_primary"])
            self.card_real_yld.set_value(f"{real_yld:.2f}%", "TIPS yield", c)

    def _store_chart_series(self, d: dict) -> None:
        self._chart_series = {
            "10Y Treasury":   d.get("yield_10y_hist"),
            "Yield Curve":    d.get("yield_spread_hist"),
            "DXY":            d.get("dxy_hist"),
            "Gold":           d.get("gold_hist"),
            "Oil":            d.get("oil_hist"),
            "HYG Credit":     d.get("hyg_hist"),
            "STLFSI4":        d.get("stlfsi_hist"),
            "MOVE Index":     d.get("move_hist"),
            "HY Spread":      d.get("hy_spread_hist"),
            "5Y Breakeven":   d.get("breakeven_5y_hist"),
            "10Y Real Yield": d.get("real_yield_10y_hist"),
        }

    # ── Chart rendering ────────────────────────────────────────────────────────

    def _render_chart(self) -> None:
        self.plot.clear()
        key    = self.chart_selector.currentText()
        series = self._chart_series.get(key)

        if series is None or series.empty:
            self.plot.setTitle(f"{key} — no data", color=COLORS["text_secondary"], size="9pt")
            return

        series = series.dropna()
        if series.empty:
            self.plot.setTitle(f"{key} — no data", color=COLORS["text_secondary"], size="9pt")
            return

        x = np.array([ts.timestamp() for ts in series.index])
        y = series.to_numpy(dtype=float)

        self._add_regime_overlay(series)
        self.plot.plot(x, y, pen=pg.mkPen(color=_CHART_COLORS.get(key, "#58a6ff"), width=1.5))

        if key == "Yield Curve":
            self.plot.addItem(pg.InfiniteLine(
                pos=0, angle=0,
                pen=pg.mkPen(color=COLORS["risk_off"], width=1, style=Qt.PenStyle.DashLine)
            ))
            for level in (0.5, 1.5):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "10Y Treasury":
            for level, color in ((3.5, COLORS["risk_on"]), (5.0, COLORS["risk_off"])):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "STLFSI4":
            for level, color in ((0, COLORS["neutral"]), (1, COLORS["risk_off"])):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "MOVE Index":
            for level, color in ((80, COLORS["risk_on"]), (130, COLORS["risk_off"])):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key == "HY Spread":
            for level, color in ((3.0, COLORS["risk_on"]), (5.0, COLORS["risk_off"])):
                self.plot.addItem(pg.InfiniteLine(
                    pos=level, angle=0,
                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
                ))
        elif key in ("DXY", "Gold", "Oil", "HYG Credit"):
            ma_key = {"DXY": "dxy_ma200", "Gold": "gold_ma200",
                      "Oil": "oil_ma200", "HYG Credit": "hyg_ma200"}[key]
            ma_val = self._data.get(ma_key)
            if ma_val:
                self.plot.addItem(pg.InfiniteLine(
                    pos=ma_val, angle=0,
                    pen=pg.mkPen(color=COLORS["neutral"], width=1, style=Qt.PenStyle.DashLine)
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
