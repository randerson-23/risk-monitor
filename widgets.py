"""
Custom PyQt6 widgets:
  GaugeWidget      — semicircular Fear & Greed gauge
  RegimeCard       — coloured regime status card
  MetricCard       — small single-metric tile
  CycleClockWidget — arc showing BTC 4-year halving cycle position
"""

import math
import re
from datetime import datetime

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt6.QtWidgets import QWidget

# ── Colour palette ────────────────────────────────────────────────────────────

COLORS = {
    "bg":             "#0d1117",
    "card_bg":        "#161b22",
    "card_border":    "#30363d",
    "text_primary":   "#e6edf3",
    "text_secondary": "#8b949e",
    "risk_on":        "#3fb950",
    "neutral":        "#d29922",
    "risk_off":       "#f85149",
    "accent":         "#58a6ff",
    "na":             "#8b949e",
}


def regime_color(condition) -> str:
    """Green for True, red for False, grey for None."""
    if condition is None:
        return COLORS["na"]
    return COLORS["risk_on"] if condition else COLORS["risk_off"]


# ── Global font-size scaling ─────────────────────────────────────────────────
# A single adjustable delta (in px/pt) applied to every base font size used by
# tab stylesheets and the custom-painted widgets below. MainWindow mutates this
# via set_font_delta(...) and then asks each tab to refresh its stylesheets.

_FONT_DELTA = 0


def font_delta() -> int:
    return _FONT_DELTA


def set_font_delta(delta: int) -> None:
    global _FONT_DELTA
    _FONT_DELTA = int(delta)


def fs(base_px: int) -> int:
    """Return the scaled pixel size for stylesheet font-size."""
    return max(7, base_px + _FONT_DELTA)


def fpt(base_pt: int) -> int:
    """Return the scaled point size for QFont(..., pt)."""
    return max(6, base_pt + _FONT_DELTA)


_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def apply_font_delta_offset(root, offset: int) -> None:
    """Walk ``root`` and every descendant QWidget, adding ``offset`` to each
    ``font-size: Npx`` value encountered in their stylesheets. Pass the
    *difference* vs. the previously-applied delta; values clamp at ≥7 px.

    Custom painted widgets (MetricCard, GaugeWidget, ...) are triggered to
    repaint via .update() since they read ``font_delta()`` directly.
    """
    if offset == 0:
        return

    def _shift(match: "re.Match[str]") -> str:
        return f"font-size: {max(7, int(match.group(1)) + offset)}px"

    for w in [root] + root.findChildren(QWidget):
        ss = w.styleSheet()
        if ss and "font-size" in ss:
            w.setStyleSheet(_FONT_SIZE_RE.sub(_shift, ss))
        w.update()


# ── GaugeWidget ───────────────────────────────────────────────────────────────

_GAUGE_SEGMENTS = [
    ("#f85149", 180, 36),
    ("#e07b39", 144, 36),
    ("#d29922", 108, 36),
    ("#7cb342",  72, 36),
    ("#3fb950",  36, 36),
]


class GaugeWidget(QWidget):
    def __init__(self, title: str = "Fear & Greed", parent=None):
        super().__init__(parent)
        self.title = title
        self._value: float | None = None
        self._label: str = ""
        self.setMinimumSize(250, 175)

    def set_value(self, value: float, label: str = "") -> None:
        self._value = value
        self._label = label
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx = w / 2
        cy = h * 0.66
        radius = min(w * 0.42, h * 0.75)
        track_w = int(radius * 0.17)
        inner = radius - track_w / 2

        arc_rect = QRectF(cx - inner, cy - inner, inner * 2, inner * 2)

        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setWidth(track_w)
        for color, start, span in _GAUGE_SEGMENTS:
            pen.setColor(QColor(color))
            p.setPen(pen)
            p.drawArc(arc_rect, start * 16, -span * 16)

        if self._value is not None:
            norm = max(0.0, min(1.0, self._value / 100.0))
            angle_rad = math.radians(180 - norm * 180)
            nx = cx + inner * 0.78 * math.cos(angle_rad)
            ny = cy - inner * 0.78 * math.sin(angle_rad)

            p.setPen(QPen(QColor("#e6edf3"), 2))
            p.drawLine(QPointF(cx, cy), QPointF(nx, ny))

            p.setBrush(QBrush(QColor("#e6edf3")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 5, 5)

        p.setPen(QPen(QColor(COLORS["text_primary"])))
        p.setFont(QFont("Segoe UI", fpt(22), QFont.Weight.Bold))
        val_str = f"{int(self._value)}" if self._value is not None else "—"
        p.drawText(QRectF(cx - 50, cy - 14, 100, 30), Qt.AlignmentFlag.AlignCenter, val_str)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", fpt(12)))
        p.drawText(QRectF(cx - 75, cy + 18, 150, 18), Qt.AlignmentFlag.AlignCenter, self._label)

        p.setFont(QFont("Segoe UI", fpt(12)))
        p.drawText(QRectF(0, 6, w, 18), Qt.AlignmentFlag.AlignCenter, self.title)

        p.setFont(QFont("Segoe UI", fpt(11)))
        p.drawText(QRectF(cx - radius - 2, cy - 14, 44, 16), Qt.AlignmentFlag.AlignCenter, "Fear")
        p.drawText(QRectF(cx + radius - 42, cy - 14, 44, 16), Qt.AlignmentFlag.AlignCenter, "Greed")


# ── RegimeCard ────────────────────────────────────────────────────────────────

class RegimeCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._regime = "—"
        self._score: int | None = None
        self._color = COLORS["na"]
        self.setMinimumSize(175, 150)

    def set_regime(self, regime: str, score: int, color: str) -> None:
        self._regime = regime
        self._score = score
        self._color = color
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        p.setBrush(QBrush(QColor(COLORS["card_bg"])))
        p.setPen(QPen(QColor(self._color), 2))
        p.drawRoundedRect(2, 2, w - 4, h - 4, 8, 8)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", fpt(12)))
        p.drawText(QRectF(0, 14, w, 22), Qt.AlignmentFlag.AlignCenter, "REGIME")

        p.setPen(QPen(QColor(self._color)))
        p.setFont(QFont("Segoe UI", fpt(22), QFont.Weight.Bold))
        p.drawText(QRectF(0, 40, w, 40), Qt.AlignmentFlag.AlignCenter, self._regime)

        if self._score is not None:
            p.setPen(QPen(QColor(COLORS["text_secondary"])))
            p.setFont(QFont("Segoe UI", fpt(13)))
            sign = "+" if self._score > 0 else ""
            p.drawText(QRectF(0, 86, w, 24), Qt.AlignmentFlag.AlignCenter,
                       f"Score: {sign}{self._score}")

        p.setBrush(QBrush(QColor(self._color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(10, h - 14, w - 20, 6, 3, 3)


# ── MetricCard ────────────────────────────────────────────────────────────────

class MetricCard(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = "—"
        self._sub = ""
        self._val_color = COLORS["text_primary"]
        self.setMinimumSize(130, 100)
        self.setMaximumHeight(115)

    def set_value(self, value: str, sub: str = "", color: str | None = None) -> None:
        self._value = value
        self._sub = sub
        self._val_color = color or COLORS["text_primary"]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        p.setBrush(QBrush(QColor(COLORS["card_bg"])))
        p.setPen(QPen(QColor(COLORS["card_border"]), 1))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 6, 6)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", fpt(11)))
        p.drawText(QRectF(4, 8, w - 8, 20), Qt.AlignmentFlag.AlignCenter, self._label)

        p.setPen(QPen(QColor(self._val_color)))
        p.setFont(QFont("Segoe UI", fpt(16), QFont.Weight.Bold))
        p.drawText(QRectF(4, 30, w - 8, 30), Qt.AlignmentFlag.AlignCenter, self._value)

        if self._sub:
            p.setPen(QPen(QColor(COLORS["text_secondary"])))
            p.setFont(QFont("Segoe UI", fpt(11)))
            p.drawText(QRectF(4, 64, w - 8, 18), Qt.AlignmentFlag.AlignCenter, self._sub)


# ── CycleClockWidget ──────────────────────────────────────────────────────────

_HALVINGS = [
    datetime(2012, 11, 28), datetime(2016, 7,  9),
    datetime(2020, 5,  11), datetime(2024, 4, 19),
    datetime(2028, 4,  15),
]

_CYCLE_PHASES = [
    (0.08, "POST-HALVING", "#3fb950", "ACCUMULATE",  +2),
    (0.38, "BULL RUN",     "#d29922", "ADD / HOLD",   +1),
    (0.48, "PEAK ZONE",    "#e07b39", "REDUCE",       -1),
    (0.87, "BEAR MARKET",  "#f85149", "HOLD / DCA",   -2),
    (1.00, "PRE-HALVING",  "#58a6ff", "ACCUMULATE",   +1),
]


class CycleClockWidget(QWidget):
    """270° arc clock showing position within the BTC 4-year halving cycle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 230)
        self._progress   = 0.0
        self._phase      = "—"
        self._action     = "—"
        self._color      = COLORS["na"]
        self._days_in    = 0
        self._days_left  = 0
        self._score      = 0
        self._refresh()

    def _refresh(self):
        now  = datetime.now()
        past   = [h for h in _HALVINGS if h <= now]
        future = [h for h in _HALVINGS if h > now]
        if not past or not future:
            return
        last, nxt        = past[-1], future[0]
        total            = (nxt - last).days
        self._days_in    = (now - last).days
        self._days_left  = (nxt - now).days
        self._progress   = min(1.0, self._days_in / total)
        for end_frac, label, color, action, score in _CYCLE_PHASES:
            if self._progress <= end_frac:
                self._phase  = label
                self._color  = color
                self._action = action
                self._score  = score
                break
        self.update()

    def get_score(self) -> int:
        return self._score

    def get_phase(self) -> str:
        return self._phase

    def get_action(self) -> str:
        return self._action

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h    = self.width(), self.height()
        cx      = w / 2
        cy      = h * 0.50
        radius  = min(w * 0.40, h * 0.46)
        track_w = max(14, int(radius * 0.18))
        inner   = radius - track_w / 2
        arc_rect = QRectF(cx - inner, cy - inner, inner * 2, inner * 2)

        ARC_START = 225
        ARC_SWEEP = -270

        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setWidth(track_w)
        prev = 0.0
        for end_frac, _, color, _, _ in _CYCLE_PHASES:
            seg_start = ARC_START + prev * ARC_SWEEP
            seg_span  = (end_frac - prev) * ARC_SWEEP
            pen.setColor(QColor(color))
            p.setPen(pen)
            p.drawArc(arc_rect, int(seg_start * 16), int(seg_span * 16))
            prev = end_frac

        angle_rad = math.radians(ARC_START + self._progress * ARC_SWEEP)
        dot_x = cx + inner * math.cos(angle_rad)
        dot_y = cy - inner * math.sin(angle_rad)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(COLORS["bg"]), 2))
        p.drawEllipse(QPointF(dot_x, dot_y), 7, 7)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", fpt(12)))
        p.drawText(QRectF(0, 5, w, 16), Qt.AlignmentFlag.AlignCenter, "4-YEAR HALVING CYCLE")

        p.setPen(QPen(QColor(self._color)))
        p.setFont(QFont("Segoe UI", fpt(9), QFont.Weight.Bold))
        p.drawText(QRectF(cx - inner * 0.85, cy - inner * 0.48, inner * 1.7, 18),
                   Qt.AlignmentFlag.AlignCenter, self._phase)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", fpt(11)))
        p.drawText(QRectF(cx - inner * 0.85, cy - inner * 0.18, inner * 1.7, 15),
                   Qt.AlignmentFlag.AlignCenter, f"Day {self._days_in}")
        p.drawText(QRectF(cx - inner * 0.85, cy + inner * 0.08, inner * 1.7, 15),
                   Qt.AlignmentFlag.AlignCenter, f"{self._days_left}d to halving")

        action_y = cy + inner + track_w * 0.5 + 10
        p.setPen(QPen(QColor(self._color)))
        p.setFont(QFont("Segoe UI", fpt(15), QFont.Weight.Bold))
        p.drawText(QRectF(0, action_y, w, 24), Qt.AlignmentFlag.AlignCenter, self._action)
