"""
VolForecastPanel — pyqtgraph widget showing trailing realized vol + a
forward GARCH price-cone (5/25/50/75/95) over the next ~20 business days.

Two stacked plots:
  • Top: 90-day trailing 21-day realized vol (annualized %), with three
    forecast σ tiles (1d / 5d / 20d) on the right.
  • Bottom: price + forward cone (filled bands).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from theme import TOKENS, numeric_font, ui_font


def _to_ts(dates: Iterable) -> np.ndarray:
    return np.array([pd.Timestamp(d).timestamp() for d in dates], dtype=float)


class _VolTile(QFrame):
    """Compact tile for a single horizon vol number."""

    def __init__(self, horizon: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {TOKENS['surface_alt']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 4px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(0)
        self._h = QLabel(horizon)
        self._h.setFont(ui_font(9))
        self._h.setStyleSheet(f"color: {TOKENS['text_secondary']}; border: none;")
        self._h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._v = QLabel("—")
        self._v.setFont(numeric_font(14, bold=True))
        self._v.setStyleSheet(f"color: {TOKENS['text_primary']}; border: none;")
        self._v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._h)
        lay.addWidget(self._v)

    def set_value(self, vol_pct: float | None) -> None:
        self._v.setText("—" if vol_pct is None else f"{vol_pct:.1f}%")


class VolForecastPanel(QFrame):
    """Top: realized-vol line. Bottom: price cone."""

    def __init__(self, title: str = "Vol Forecast (GARCH)", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {TOKENS['surface']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 6px;"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # Header row: title + 3 horizon tiles
        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        title_lbl = QLabel(title.upper())
        title_lbl.setFont(ui_font(10, bold=True))
        title_lbl.setStyleSheet(f"color: {TOKENS['text_secondary']}; border: none;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()
        self.tile_h1  = _VolTile("σ  1D")
        self.tile_h5  = _VolTile("σ  5D")
        self.tile_h20 = _VolTile("σ 20D")
        for t in (self.tile_h1, self.tile_h5, self.tile_h20):
            hdr.addWidget(t)
        root.addLayout(hdr)

        # Vol plot
        ax_vol = pg.DateAxisItem(orientation="bottom")
        self.vol_plot = pg.PlotWidget(axisItems={"bottom": ax_vol})
        self.vol_plot.setMinimumHeight(110)
        self.vol_plot.showGrid(x=False, y=True, alpha=0.12)
        self.vol_plot.setLabel("left", "Realized Vol %", color=TOKENS["text_secondary"])
        self._style_axes(self.vol_plot)
        root.addWidget(self.vol_plot, stretch=1)

        # Price cone plot
        ax_p = pg.DateAxisItem(orientation="bottom")
        self.cone_plot = pg.PlotWidget(axisItems={"bottom": ax_p})
        self.cone_plot.setMinimumHeight(140)
        self.cone_plot.showGrid(x=False, y=True, alpha=0.12)
        self.cone_plot.setLabel("left", "Price (cone p5/25/75/95)", color=TOKENS["text_secondary"])
        self._style_axes(self.cone_plot)
        root.addWidget(self.cone_plot, stretch=1)

        self._status = QLabel("")
        self._status.setFont(ui_font(9))
        self._status.setStyleSheet(f"color: {TOKENS['text_muted']}; border: none;")
        root.addWidget(self._status)

    @staticmethod
    def _style_axes(p: pg.PlotWidget) -> None:
        for side in ("left", "bottom"):
            ax = p.getPlotItem().getAxis(side)
            ax.setPen(pg.mkPen(color=TOKENS["border"]))
            ax.setTextPen(pg.mkPen(color=TOKENS["text_secondary"]))

    def clear(self) -> None:
        self.vol_plot.clear()
        self.cone_plot.clear()
        self.tile_h1.set_value(None)
        self.tile_h5.set_value(None)
        self.tile_h20.set_value(None)

    def set_error(self, msg: str) -> None:
        self.clear()
        self._status.setText(f"⚠ {msg}")

    def update_forecast(self, fc: dict, price_history: pd.Series | None = None) -> None:
        self.vol_plot.clear()
        self.cone_plot.clear()

        if not fc.get("ok"):
            self.set_error(fc.get("error", "forecast unavailable"))
            return

        self._status.setText(
            f"Fitted {fc.get('fitted_at', datetime.now()).strftime('%H:%M:%S')}  ·  "
            f"horizon {len(fc['forecast_dates'])} bdays"
        )

        # ── Vol plot: realized + forecast median ──────────────────────────
        if fc["history_dates"]:
            hx = _to_ts(fc["history_dates"])
            hy = np.array(fc["history_vol"], dtype=float)
            self.vol_plot.plot(hx, hy, pen=pg.mkPen(color=TOKENS["text_secondary"], width=1.4))
        fx = _to_ts(fc["forecast_dates"])
        fy = np.array(fc["vol_median"], dtype=float)
        self.vol_plot.plot(fx, fy, pen=pg.mkPen(
            color=TOKENS["accent_amber"], width=1.8, style=Qt.PenStyle.DashLine))

        self.tile_h1.set_value(fc["h1"])
        self.tile_h5.set_value(fc["h5"])
        self.tile_h20.set_value(fc["h20"])

        # ── Price cone ───────────────────────────────────────────────────
        if price_history is not None and len(price_history) > 0:
            tail = price_history.dropna().tail(90)
            px = np.array([pd.Timestamp(t).timestamp() for t in tail.index])
            py = tail.values.astype(float)
            self.cone_plot.plot(px, py, pen=pg.mkPen(color=TOKENS["text_secondary"], width=1.4))

        x = fx
        p5  = np.array(fc["cone_p5"],     dtype=float)
        p25 = np.array(fc["cone_p25"],    dtype=float)
        med = np.array(fc["cone_median"], dtype=float)
        p75 = np.array(fc["cone_p75"],    dtype=float)
        p95 = np.array(fc["cone_p95"],    dtype=float)

        amber = QColor(TOKENS["accent_amber"])
        outer = QColor(amber); outer.setAlpha(38)
        inner = QColor(amber); inner.setAlpha(76)

        self._fill_band(self.cone_plot, x, p5, p95, outer)
        self._fill_band(self.cone_plot, x, p25, p75, inner)
        self.cone_plot.plot(x, med, pen=pg.mkPen(color=TOKENS["accent_amber"], width=1.6))

    @staticmethod
    def _fill_band(plot: pg.PlotWidget, x, lo, hi, color: QColor) -> None:
        upper = pg.PlotDataItem(x, hi, pen=pg.mkPen(None))
        lower = pg.PlotDataItem(x, lo, pen=pg.mkPen(None))
        fill = pg.FillBetweenItem(upper, lower, brush=color)
        plot.addItem(upper)
        plot.addItem(lower)
        plot.addItem(fill)
