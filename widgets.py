"""
Custom PyQt6 widgets:
  GaugeWidget   — semicircular Fear & Greed gauge
  RegimeCard    — coloured regime status card
  MetricCard    — small single-metric tile
"""

import math

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


# ── GaugeWidget ───────────────────────────────────────────────────────────────

# Arc segments: (hex_color, start_deg, span_deg) left→right = 180→0
_GAUGE_SEGMENTS = [
    ("#f85149", 180, 36),  # 0–20  Extreme Fear
    ("#e07b39", 144, 36),  # 20–40 Fear
    ("#d29922", 108, 36),  # 40–60 Neutral
    ("#7cb342",  72, 36),  # 60–80 Greed
    ("#3fb950",  36, 36),  # 80–100 Extreme Greed
]


class GaugeWidget(QWidget):
    def __init__(self, title: str = "Fear & Greed", parent=None):
        super().__init__(parent)
        self.title = title
        self._value: float | None = None
        self._label: str = ""
        self.setMinimumSize(220, 155)

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

        # Coloured arc track
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setWidth(track_w)
        for color, start, span in _GAUGE_SEGMENTS:
            pen.setColor(QColor(color))
            p.setPen(pen)
            p.drawArc(arc_rect, start * 16, -span * 16)

        # Needle
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

        # Score text
        p.setPen(QPen(QColor(COLORS["text_primary"])))
        p.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        val_str = f"{int(self._value)}" if self._value is not None else "—"
        p.drawText(QRectF(cx - 50, cy - 14, 100, 30), Qt.AlignmentFlag.AlignCenter, val_str)

        # Rating label
        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(cx - 75, cy + 18, 150, 18), Qt.AlignmentFlag.AlignCenter, self._label)

        # Title
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(0, 6, w, 18), Qt.AlignmentFlag.AlignCenter, self.title)

        # Left / right axis labels
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(cx - radius - 2, cy - 14, 44, 16), Qt.AlignmentFlag.AlignCenter, "Fear")
        p.drawText(QRectF(cx + radius - 42, cy - 14, 44, 16), Qt.AlignmentFlag.AlignCenter, "Greed")


# ── RegimeCard ────────────────────────────────────────────────────────────────

class RegimeCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._regime = "—"
        self._score: int | None = None
        self._color = COLORS["na"]
        self.setMinimumSize(155, 130)

    def set_regime(self, regime: str, score: int, color: str) -> None:
        self._regime = regime
        self._score = score
        self._color = color
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Card background + coloured border
        p.setBrush(QBrush(QColor(COLORS["card_bg"])))
        p.setPen(QPen(QColor(self._color), 2))
        p.drawRoundedRect(2, 2, w - 4, h - 4, 8, 8)

        # "REGIME" label
        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(0, 12, w, 18), Qt.AlignmentFlag.AlignCenter, "REGIME")

        # Regime name
        p.setPen(QPen(QColor(self._color)))
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        p.drawText(QRectF(0, 32, w, 36), Qt.AlignmentFlag.AlignCenter, self._regime)

        # Score
        if self._score is not None:
            p.setPen(QPen(QColor(COLORS["text_secondary"])))
            p.setFont(QFont("Segoe UI", 10))
            sign = "+" if self._score > 0 else ""
            p.drawText(QRectF(0, 72, w, 22), Qt.AlignmentFlag.AlignCenter,
                       f"Score: {sign}{self._score}")

        # Bottom colour bar
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
        self.setMinimumSize(110, 82)
        self.setMaximumHeight(92)

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

        # Label
        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(4, 8, w - 8, 15), Qt.AlignmentFlag.AlignCenter, self._label)

        # Value
        p.setPen(QPen(QColor(self._val_color)))
        p.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        p.drawText(QRectF(4, 24, w - 8, 26), Qt.AlignmentFlag.AlignCenter, self._value)

        # Sub-text
        if self._sub:
            p.setPen(QPen(QColor(COLORS["text_secondary"])))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(4, 52, w - 8, 14), Qt.AlignmentFlag.AlignCenter, self._sub)
