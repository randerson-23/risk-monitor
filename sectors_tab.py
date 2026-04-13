import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                              QProgressBar, QScrollArea, QSizePolicy,
                              QVBoxLayout, QWidget)

from data_fetch import SECTOR_NAMES
from regime import compute_sector_rotation_regime
from widgets import COLORS

_SECTOR_TICKERS = list(SECTOR_NAMES.keys())

_QUADRANT_COLORS = {
    "Leading":   COLORS["risk_on"],    # green
    "Improving": COLORS["accent"],     # blue
    "Weakening": COLORS["neutral"],    # amber
    "Lagging":   COLORS["risk_off"],   # red
}

_ROTATION_DISPLAY = {
    "OFFENSIVE": ("OFFENSIVE", COLORS["risk_on"]),
    "DEFENSIVE": ("DEFENSIVE", COLORS["risk_off"]),
    "MIXED":     ("MIXED",     COLORS["neutral"]),
}

_SORT_KEYS = {
    "RS Score": "rs_score",
    "1D %":     "pct_1d",
    "5D %":     "pct_5d",
    "1M %":     "pct_1m",
    "3M %":     "pct_3m",
    "YTD %":    "ytd",
}


def _fmt(v, pct=True):
    if v is None:
        return "—"
    return f"{v:+.1f}%" if pct else str(v)


class _SectorSummaryCard(QFrame):
    """Top-row card showing best or worst sector."""

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)

        hdr = QLabel(title)
        hdr.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; font-weight: bold; border: none;")
        lay.addWidget(hdr)

        self.lbl_ticker = QLabel("—")
        self.lbl_ticker.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold; border: none;")
        lay.addWidget(self.lbl_ticker)

        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        lay.addWidget(self.lbl_name)

        row = QHBoxLayout()
        self.lbl_rs = QLabel("")
        self.lbl_rs.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold; border: none;")
        row.addWidget(self.lbl_rs)
        self.lbl_1d = QLabel("")
        self.lbl_1d.setStyleSheet(f"color: {color}; font-size: 13px; border: none;")
        row.addWidget(self.lbl_1d)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()

    def set_sector(self, ticker: str, d: dict) -> None:
        self.lbl_ticker.setText(ticker)
        self.lbl_name.setText(d.get("name", ""))
        self.lbl_rs.setText(f"RS {d.get('rs_score', 0)}")
        v1d = d.get("pct_1d")
        self.lbl_1d.setText(_fmt(v1d))


class _RotationCard(QFrame):
    """Rotation regime card for top-row left slot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = COLORS["na"]
        self.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {self._color}; border-radius: 8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        hdr = QLabel("SECTOR ROTATION")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; font-weight: bold; border: none;")
        lay.addWidget(hdr)

        self.lbl_regime = QLabel("—")
        self.lbl_regime.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_regime.setStyleSheet(f"color: {COLORS['na']}; font-size: 20px; font-weight: bold; border: none;")
        lay.addWidget(self.lbl_regime)

        self.lbl_top = QLabel("")
        self.lbl_top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_top.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        self.lbl_top.setWordWrap(True)
        lay.addWidget(self.lbl_top)

        self.lbl_weak = QLabel("")
        self.lbl_weak.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_weak.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        self.lbl_weak.setWordWrap(True)
        lay.addWidget(self.lbl_weak)
        lay.addStretch()

    def set_data(self, regime_info: dict, data: dict) -> None:
        color = regime_info.get("color", COLORS["na"])
        self._color = color
        self.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 2px solid {color}; border-radius: 8px;"
        )
        self.lbl_regime.setText(regime_info.get("regime", "—"))
        self.lbl_regime.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold; border: none;")

        sorted_t = data.get("sorted_by_rs", [])
        if len(sorted_t) >= 3:
            self.lbl_top.setText(f"↑ {' · '.join(sorted_t[:3])}")
            self.lbl_top.setStyleSheet(f"color: {COLORS['risk_on']}; font-size: 12px; border: none;")
        if len(sorted_t) >= 3:
            self.lbl_weak.setText(f"↓ {' · '.join(list(reversed(sorted_t[-3:])))}")
            self.lbl_weak.setStyleSheet(f"color: {COLORS['risk_off']}; font-size: 12px; border: none;")


class _SectorRow(QFrame):
    """Single row in the rankings panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet(
            f"background: transparent; border: none; "
            f"border-bottom: 1px solid {COLORS['card_border']};"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        self._dot.setStyleSheet(f"color: {COLORS['na']}; font-size: 10px; border: none;")
        lay.addWidget(self._dot)

        self._lbl_ticker = QLabel("")
        self._lbl_ticker.setFixedWidth(46)
        self._lbl_ticker.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold; border: none;")
        lay.addWidget(self._lbl_ticker)

        self._lbl_name = QLabel("")
        self._lbl_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._lbl_name.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;")
        lay.addWidget(self._lbl_name, stretch=1)

        self._lbl_metric = QLabel("")
        self._lbl_metric.setFixedWidth(60)
        self._lbl_metric.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_metric.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold; border: none;")
        lay.addWidget(self._lbl_metric)

        self._bar = QProgressBar()
        self._bar.setFixedSize(80, 8)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100)
        lay.addWidget(self._bar)

    def update(self, ticker: str, d: dict, sort_key: str) -> None:
        quad = d.get("quadrant", "Lagging")
        color = _QUADRANT_COLORS.get(quad, COLORS["na"])

        self._dot.setStyleSheet(f"color: {color}; font-size: 10px; border: none;")
        self._lbl_ticker.setText(ticker)
        self._lbl_name.setText(d.get("name", ""))

        raw = d.get(sort_key)
        if sort_key == "rs_score":
            display = str(int(raw)) if raw is not None else "—"
            bar_val = int(raw) if raw is not None else 0
            bar_color = COLORS["risk_on"] if bar_val >= 50 else COLORS["risk_off"]
        else:
            display = _fmt(raw)
            v = raw if raw is not None else 0
            # Map [-5%, +5%] → [0, 100]; clamp
            bar_val = max(0, min(100, int((v + 5) / 10 * 100)))
            bar_color = COLORS["risk_on"] if v >= 0 else COLORS["risk_off"]

        self._lbl_metric.setText(display)
        self._bar.setValue(bar_val)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {COLORS['card_border']};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {bar_color};
                border-radius: 3px;
            }}
        """)


class SectorsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = {}
        self._sector_rows: dict[str, _SectorRow] = {}
        self._rrg_bg: list = []
        self._rrg_corner_labels: list = []
        self._setup_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']}; color: {COLORS['text_primary']};")
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        root.addLayout(self._build_top_row())
        root.addLayout(self._build_middle_row(), stretch=2)
        root.addWidget(self._build_chart_panel(), stretch=1)

    def _build_top_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._rotation_card = _RotationCard()
        row.addWidget(self._rotation_card, stretch=2)

        self._top_cards = [
            _SectorSummaryCard("TOP SECTOR #1", COLORS["risk_on"]),
            _SectorSummaryCard("TOP SECTOR #2", COLORS["risk_on"]),
        ]
        self._bot_cards = [
            _SectorSummaryCard("WEAKEST SECTOR #1", COLORS["risk_off"]),
            _SectorSummaryCard("WEAKEST SECTOR #2", COLORS["risk_off"]),
        ]
        for c in self._top_cards + self._bot_cards:
            row.addWidget(c, stretch=1)
        return row

    def _build_middle_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._build_rrg_panel(), stretch=1)
        row.addWidget(self._build_rankings_panel(), stretch=1)
        return row

    def _build_rrg_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        hdr = QLabel("RELATIVE ROTATION GRAPH")
        hdr.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; font-weight: bold; border: none;")
        lay.addWidget(hdr)

        self._rrg_plot = pg.PlotWidget(background=COLORS["card_bg"])
        self._rrg_plot.setMinimumHeight(180)
        self._rrg_plot.showGrid(x=False, y=False)

        ax_l = self._rrg_plot.getPlotItem().getAxis("left")
        ax_b = self._rrg_plot.getPlotItem().getAxis("bottom")
        for ax in (ax_l, ax_b):
            ax.setPen(pg.mkPen(color=COLORS["card_border"]))
            ax.setTextPen(pg.mkPen(color=COLORS["text_secondary"]))

        self._rrg_plot.setLabel("bottom", "RS RATIO", color=COLORS["text_secondary"])
        self._rrg_plot.setLabel("left", "RS MOMENTUM", color=COLORS["text_secondary"])

        # Axis dividers at RS=100, momentum=0
        self._rrg_plot.addItem(pg.InfiniteLine(
            pos=100, angle=90,
            pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
        ))
        self._rrg_plot.addItem(pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen(color=COLORS["card_border"], width=1, style=Qt.PenStyle.DashLine)
        ))

        # Scatter item for sector dots
        self._rrg_scatter = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None))
        self._rrg_plot.addItem(self._rrg_scatter)

        # Per-sector text labels
        self._rrg_labels: dict[str, pg.TextItem] = {}
        for ticker in _SECTOR_TICKERS:
            lbl = pg.TextItem(ticker, color=COLORS["text_primary"], anchor=(0, 1))
            lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            self._rrg_plot.addItem(lbl)
            self._rrg_labels[ticker] = lbl

        # Corner quadrant labels (positioned dynamically after data loads)
        corner_specs = [
            ("LEADING",   (1, 1),  COLORS["risk_on"]),
            ("WEAKENING", (0, 1),  COLORS["neutral"]),
            ("LAGGING",   (0, 0),  COLORS["risk_off"]),
            ("IMPROVING", (1, 0),  COLORS["accent"]),
        ]
        for text, anchor, color in corner_specs:
            lbl = pg.TextItem(text, color=color, anchor=anchor)
            lbl.setFont(QFont("Segoe UI", 9))
            self._rrg_plot.addItem(lbl)
            self._rrg_corner_labels.append(lbl)

        lay.addWidget(self._rrg_plot)
        return frame

    def _build_rankings_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        ctrl = QHBoxLayout()
        hdr = QLabel("SECTOR RANKINGS")
        hdr.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; font-weight: bold; border: none;")
        ctrl.addWidget(hdr)
        ctrl.addStretch()

        self._sort_combo = QComboBox()
        self._sort_combo.setStyleSheet(
            f"QComboBox {{ background: {COLORS['bg']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 4px; "
            f"padding: 2px 6px; font-size: 13px; }}"
        )
        self._sort_combo.addItems(list(_SORT_KEYS.keys()))
        self._sort_combo.currentIndexChanged.connect(self._reorder_rows)
        ctrl.addWidget(self._sort_combo)
        lay.addLayout(ctrl)

        # Scrollable sector rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['card_bg']}; }}"
            f"QScrollBar:vertical {{ background: {COLORS['card_bg']}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['card_border']}; border-radius: 3px; }}"
        )
        inner = QWidget()
        inner.setStyleSheet(f"background: {COLORS['card_bg']};")
        self._rankings_layout = QVBoxLayout(inner)
        self._rankings_layout.setContentsMargins(0, 0, 0, 0)
        self._rankings_layout.setSpacing(0)

        for ticker in _SECTOR_TICKERS:
            row = _SectorRow()
            row.mousePressEvent = lambda _e, t=ticker: self._on_row_click(t)
            self._sector_rows[ticker] = row
            self._rankings_layout.addWidget(row)

        self._rankings_layout.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll, stretch=1)
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
        lbl = QLabel("Sector:")
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; border: none;")
        ctrl.addWidget(lbl)

        self._chart_combo = QComboBox()
        self._chart_combo.setStyleSheet(
            f"QComboBox {{ background: {COLORS['bg']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 4px; "
            f"padding: 2px 6px; font-size: 13px; }}"
        )
        for ticker in _SECTOR_TICKERS:
            self._chart_combo.addItem(f"{ticker} — {SECTOR_NAMES[ticker]}", ticker)
        self._chart_combo.currentIndexChanged.connect(self._render_chart)
        ctrl.addWidget(self._chart_combo)

        self._lbl_quadrant = QLabel("")
        self._lbl_quadrant.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; border: none;")
        ctrl.addWidget(self._lbl_quadrant)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        date_axis = pg.DateAxisItem(orientation="bottom")
        self._chart_plot = pg.PlotWidget(axisItems={"bottom": date_axis}, background=COLORS["card_bg"])
        self._chart_plot.setMinimumHeight(140)
        self._chart_plot.showGrid(x=False, y=True, alpha=0.15)
        for axis_name in ("left", "bottom"):
            ax = self._chart_plot.getPlotItem().getAxis(axis_name)
            ax.setPen(pg.mkPen(color=COLORS["card_border"]))
            ax.setTextPen(pg.mkPen(color=COLORS["text_secondary"]))
        lay.addWidget(self._chart_plot)
        return frame

    # ── Data update ────────────────────────────────────────────────────────────

    def update_data(self, data: dict) -> None:
        self._data = data
        if not data.get("sectors"):
            return

        regime_info = compute_sector_rotation_regime(data)
        self._rotation_card.set_data(regime_info, data)

        sorted_t = data.get("sorted_by_rs", [])
        sectors  = data.get("sectors", {})

        # Top / bottom summary cards
        for i, card in enumerate(self._top_cards):
            if i < len(sorted_t) and sorted_t[i] in sectors:
                card.set_sector(sorted_t[i], sectors[sorted_t[i]])
        for i, card in enumerate(self._bot_cards):
            idx = -(i + 1)
            if abs(idx) <= len(sorted_t):
                t = sorted_t[idx]
                if t in sectors:
                    card.set_sector(t, sectors[t])

        self._reorder_rows()
        self._render_rrg()

        # Default chart to top-ranked sector
        if sorted_t:
            ticker = sorted_t[0]
            for i in range(self._chart_combo.count()):
                if self._chart_combo.itemData(i) == ticker:
                    self._chart_combo.setCurrentIndex(i)
                    break
            else:
                self._render_chart()
        else:
            self._render_chart()

    # ── Rankings ───────────────────────────────────────────────────────────────

    def _reorder_rows(self) -> None:
        sectors = self._data.get("sectors", {})
        if not sectors:
            return

        sort_label = self._sort_combo.currentText()
        sort_key   = _SORT_KEYS.get(sort_label, "rs_score")

        def _sort_val(t):
            v = sectors.get(t, {}).get(sort_key)
            return v if v is not None else -999

        sorted_tickers = sorted(sectors.keys(), key=_sort_val, reverse=True)

        # Re-order widgets in layout
        for ticker in sorted_tickers:
            row = self._sector_rows.get(ticker)
            if row:
                self._rankings_layout.removeWidget(row)
                self._rankings_layout.insertWidget(
                    sorted_tickers.index(ticker), row
                )
                row.update(ticker, sectors[ticker], sort_key)

    def _on_row_click(self, ticker: str) -> None:
        for i in range(self._chart_combo.count()):
            if self._chart_combo.itemData(i) == ticker:
                self._chart_combo.setCurrentIndex(i)
                break

    # ── RRG rendering ──────────────────────────────────────────────────────────

    def _render_rrg(self) -> None:
        sectors = self._data.get("sectors", {})
        if not sectors:
            return

        # Remove old background region items
        for item in self._rrg_bg:
            self._rrg_plot.removeItem(item)
        self._rrg_bg.clear()

        xs = [d["rs_ratio"] for d in sectors.values()]
        ys = [d["rs_mom"]   for d in sectors.values()]
        if not xs:
            return

        pad_x = max((max(xs) - min(xs)) * 0.2, 2.0)
        pad_y = max((max(ys) - min(ys)) * 0.2, 0.5)
        x_min = min(xs) - pad_x
        x_max = max(xs) + pad_x
        y_min = min(ys) - pad_y
        y_max = max(ys) + pad_y

        # Quadrant background fills
        # Left (lagging/improving): faint red tint
        lr_left = pg.LinearRegionItem(
            [x_min - 100, 100], orientation="vertical",
            brush=QBrush(QColor(248, 81, 73, 20)), pen=pg.mkPen(None), movable=False
        )
        # Right (leading/weakening): faint green tint
        lr_right = pg.LinearRegionItem(
            [100, x_max + 100], orientation="vertical",
            brush=QBrush(QColor(63, 185, 80, 20)), pen=pg.mkPen(None), movable=False
        )
        # Bottom half: slightly darker overlay
        lr_bottom = pg.LinearRegionItem(
            [y_min - 10, 0], orientation="horizontal",
            brush=QBrush(QColor(0, 0, 0, 30)), pen=pg.mkPen(None), movable=False
        )
        for item in (lr_left, lr_right, lr_bottom):
            item.setZValue(-10)
            self._rrg_plot.addItem(item)
            self._rrg_bg.append(item)

        # Scatter spots
        spots = []
        for ticker, d in sectors.items():
            spots.append({
                "pos":   (d["rs_ratio"], d["rs_mom"]),
                "brush": pg.mkBrush(_QUADRANT_COLORS.get(d.get("quadrant", "Lagging"), COLORS["na"])),
                "size":  12,
            })
        self._rrg_scatter.setData(spots)

        # Position ticker labels
        for ticker, d in sectors.items():
            if ticker in self._rrg_labels:
                self._rrg_labels[ticker].setPos(d["rs_ratio"], d["rs_mom"])

        # Set manual range so corner labels have stable coordinates
        self._rrg_plot.setXRange(x_min, x_max, padding=0)
        self._rrg_plot.setYRange(y_min, y_max, padding=0)

        # Reposition corner labels
        corners = [
            (x_max, y_max),   # LEADING   top-right
            (x_min, y_max),   # WEAKENING top-left
            (x_min, y_min),   # LAGGING   bottom-left
            (x_max, y_min),   # IMPROVING bottom-right
        ]
        for lbl, (cx, cy) in zip(self._rrg_corner_labels, corners):
            lbl.setPos(cx, cy)

    # ── Chart rendering ────────────────────────────────────────────────────────

    def _render_chart(self) -> None:
        self._chart_plot.clear()
        sectors = self._data.get("sectors", {})
        spy_hist = self._data.get("spy_hist")
        if not sectors:
            return

        ticker = self._chart_combo.currentData()
        if ticker is None or ticker not in sectors:
            return

        d = sectors[ticker]
        hist = d.get("hist")
        if hist is None or hist.empty:
            return

        quad  = d.get("quadrant", "Lagging")
        color = _QUADRANT_COLORS.get(quad, COLORS["accent"])

        self._lbl_quadrant.setText(f"[ {quad.upper()} ]")
        self._lbl_quadrant.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; border: none;")

        x = np.array([ts.timestamp() for ts in hist.index])
        y = hist.to_numpy(dtype=float)
        self._chart_plot.plot(x, y, pen=pg.mkPen(color=color, width=1.5), name=ticker)

        # SPY overlay (normalized to same starting value for comparison)
        if spy_hist is not None and not spy_hist.empty:
            spy_aligned = spy_hist.reindex(hist.index, method="ffill").dropna()
            if not spy_aligned.empty and len(spy_aligned) > 1:
                # Normalize both to starting value = 100 for % comparison
                spy_norm  = spy_aligned / float(spy_aligned.iloc[0]) * float(y[0])
                xs = np.array([ts.timestamp() for ts in spy_norm.index])
                self._chart_plot.plot(
                    xs, spy_norm.to_numpy(dtype=float),
                    pen=pg.mkPen(color=COLORS["text_secondary"], width=1,
                                 style=Qt.PenStyle.DashLine),
                    name="SPY"
                )

        self._chart_plot.setTitle(
            f"{ticker}  ({SECTOR_NAMES.get(ticker, '')})  vs  SPY",
            color=COLORS["text_secondary"], size="10pt"
        )
