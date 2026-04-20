"""
Custom PyQt6 widgets:
  GaugeWidget      — semicircular Fear & Greed gauge
  RegimeCard       — coloured regime status card
  MetricCard       — small single-metric tile (optional sparkline)
  CycleClockWidget — arc showing BTC 4-year halving cycle position
  FlashLabel       — QLabel that flashes on numeric change
"""

import math
import re
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy

from theme import COLORS, TOKENS, numeric_font, ui_font  # noqa: F401  (COLORS re-exported)


def regime_color(condition) -> str:
    """Green for True, red for False, grey for None."""
    if condition is None:
        return COLORS["na"]
    return COLORS["risk_on"] if condition else COLORS["risk_off"]


# ── Global font-size scaling ─────────────────────────────────────────────────
# A single delta (in px) applied to every base font size used by tab
# stylesheets via the ``fs()`` helper. MainWindow mutates this via
# ``set_font_delta(...)`` and then walks the widget tree with
# ``apply_font_delta_offset(...)`` to shift existing stylesheets.

_FONT_DELTA: int = 0


def font_delta() -> int:
    return _FONT_DELTA


def set_font_delta(delta: int) -> None:
    global _FONT_DELTA
    _FONT_DELTA = int(delta)


def fs(base_px: int) -> int:
    """Return the scaled pixel size for stylesheet ``font-size: ...px``."""
    return max(7, base_px + _FONT_DELTA)


_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def apply_font_delta_offset(root, offset: int) -> None:
    """Walk ``root`` and every descendant QWidget, adding ``offset`` to every
    ``font-size: Npx`` value in their stylesheets. Pass the *difference* vs.
    the previously-applied delta; values clamp at ≥ 7 px. Also calls
    ``.update()`` so custom-painted widgets repaint."""
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
        p.setFont(numeric_font(20, bold=True))
        val_str = f"{int(self._value)}" if self._value is not None else "—"
        p.drawText(QRectF(cx - 50, cy - 14, 100, 30), Qt.AlignmentFlag.AlignCenter, val_str)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(ui_font(11))
        p.drawText(QRectF(cx - 75, cy + 18, 150, 18), Qt.AlignmentFlag.AlignCenter, self._label)

        p.setFont(ui_font(11))
        p.drawText(QRectF(0, 6, w, 18), Qt.AlignmentFlag.AlignCenter, self.title)

        p.setFont(ui_font(10))
        p.drawText(QRectF(cx - radius - 2, cy - 14, 44, 16), Qt.AlignmentFlag.AlignCenter, "Fear")
        p.drawText(QRectF(cx + radius - 42, cy - 14, 44, 16), Qt.AlignmentFlag.AlignCenter, "Greed")


# ── RiskSentimentWidget ───────────────────────────────────────────────────────

class RiskSentimentWidget(QWidget):
    """
    Replaces the speedometer gauge with a clean Risk On / Risk Off indicator.
    Shows the sentiment score, label, and a colour-coded risk signal.
    """

    def __init__(self, title: str = "Fear & Greed", parent=None):
        super().__init__(parent)
        self.title = title
        self._value: float | None = None
        self._label: str = ""
        self.setMinimumSize(250, 160)

    def set_value(self, value: float, label: str = "") -> None:
        self._value = value
        self._label = label
        self.update()

    def _risk_state(self):
        """Return (text, color) for the current value."""
        if self._value is None:
            return "—", COLORS["na"]
        if self._value >= 60:
            return "RISK ON", COLORS["risk_on"]
        if self._value <= 40:
            return "RISK OFF", COLORS["risk_off"]
        return "NEUTRAL", COLORS["neutral"]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Background card
        p.setBrush(QBrush(QColor(COLORS["card_bg"])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 8, 8)

        # Title
        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(ui_font(11))
        p.drawText(QRectF(0, 10, w, 18), Qt.AlignmentFlag.AlignCenter, self.title)

        state_text, state_color = self._risk_state()

        # Coloured pill background
        pill_w, pill_h = min(w - 40, 200), 48
        pill_x = (w - pill_w) / 2
        pill_y = (h - pill_h) / 2 - 4

        bg_color = QColor(state_color)
        bg_color.setAlpha(30)
        p.setBrush(QBrush(bg_color))
        p.setPen(QPen(QColor(state_color), 1.5))
        p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), 8, 8)

        # State text inside pill
        p.setPen(QPen(QColor(state_color)))
        p.setFont(ui_font(20, bold=True))
        p.drawText(QRectF(pill_x, pill_y, pill_w, pill_h),
                   Qt.AlignmentFlag.AlignCenter, state_text)

        # Score and label below pill
        val_str = f"{int(self._value)}" if self._value is not None else "—"
        sub = f"{val_str}  ·  {self._label}" if self._label else val_str

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(ui_font(11))
        p.drawText(QRectF(0, pill_y + pill_h + 8, w, 18),
                   Qt.AlignmentFlag.AlignCenter, sub)


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
        p.setFont(ui_font(11, bold=True))
        p.drawText(QRectF(0, 14, w, 22), Qt.AlignmentFlag.AlignCenter, "REGIME")

        p.setPen(QPen(QColor(self._color)))
        p.setFont(ui_font(20, bold=True))
        p.drawText(QRectF(0, 40, w, 40), Qt.AlignmentFlag.AlignCenter, self._regime)

        if self._score is not None:
            p.setPen(QPen(QColor(COLORS["text_secondary"])))
            p.setFont(numeric_font(12))
            sign = "+" if self._score > 0 else ""
            p.drawText(QRectF(0, 86, w, 24), Qt.AlignmentFlag.AlignCenter,
                       f"Score: {sign}{self._score}")

        p.setBrush(QBrush(QColor(self._color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(10, h - 14, w - 20, 6, 3, 3)


# ── Regime Scoreboard (4-cell) ────────────────────────────────────────────────

class RegimeCell(QWidget):
    """One cell of the top-of-page regime scoreboard.

    Layout:
        [KICKER LABEL]                [SCORE +n / +max]
        [ gauge ]   [ VERDICT ]
                    [ sub caption ]
        [───────── 4px meter ─────────]
    """

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label.upper()
        self._score: int | None = None
        self._max_score: int | None = None
        self._score_text: str | None = None  # overrides "SCORE ±x / ±max" when set
        self._verdict = "—"
        self._sub = ""
        self._value = 0.0   # gauge position, 0–100
        self._color = TOKENS["na"]
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_state(
        self,
        verdict: str,
        color: str,
        score: int | None = None,
        max_score: int | None = None,
        value: float | None = None,
        sub: str = "",
        score_text: str | None = None,
    ) -> None:
        self._verdict = verdict or "—"
        self._color = color or TOKENS["na"]
        self._score = score
        self._max_score = max_score
        self._value = 50.0 if value is None else max(0.0, min(100.0, float(value)))
        self._sub = sub
        self._score_text = score_text
        self.update()

    def _score_display(self) -> str:
        if self._score_text:
            return self._score_text
        if self._score is None:
            return ""
        sign = "+" if self._score > 0 else ("" if self._score < 0 else "±")
        if self._max_score is not None:
            max_s = f"+{self._max_score}" if self._max_score >= 0 else str(self._max_score)
            return f"SCORE {sign}{self._score} / {max_s}"
        return f"SCORE {sign}{self._score}"

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Cell surface (the grid parent paints the 1px border gaps).
        p.fillRect(self.rect(), QColor(TOKENS["surface"]))

        pad_x = 16
        pad_y = 14

        # Kicker row
        p.setFont(ui_font(9, bold=True))
        p.setPen(QPen(QColor(TOKENS["text_muted"])))
        p.drawText(QRectF(pad_x, pad_y - 2, w - pad_x * 2, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._label)
        p.setFont(numeric_font(10))
        p.setPen(QPen(QColor(TOKENS["text_secondary"])))
        p.drawText(QRectF(pad_x, pad_y - 2, w - pad_x * 2, 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._score_display())

        # Gauge (64x40 semicircle), left
        gauge_w, gauge_h = 64, 40
        gx = pad_x
        gy = pad_y + 16
        self._paint_gauge(p, QRectF(gx, gy, gauge_w, gauge_h))

        # Verdict + sub caption, right of gauge
        tx = gx + gauge_w + 14
        p.setFont(numeric_font(16, bold=True))
        p.setPen(QPen(QColor(self._color)))
        p.drawText(QRectF(tx, gy - 2, w - tx - pad_x, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._verdict)
        p.setFont(ui_font(10))
        p.setPen(QPen(QColor(TOKENS["text_secondary"])))
        p.drawText(QRectF(tx, gy + 20, w - tx - pad_x, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._sub)

        # Meter bar, full-width at bottom: 4px, centered fill left/right by score sign
        meter_y = h - pad_y
        meter_rect = QRectF(pad_x, meter_y, w - pad_x * 2, 4)
        p.setBrush(QBrush(QColor(TOKENS["surface_alt"])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(meter_rect, 2, 2)

        # Fill proportional to |score| / max_score; direction from sign.
        if self._score is not None and self._max_score not in (None, 0):
            frac = max(-1.0, min(1.0, float(self._score) / float(self._max_score)))
            center_x = meter_rect.x() + meter_rect.width() / 2
            half_w = meter_rect.width() / 2
            fw = abs(frac) * half_w
            fx = center_x if frac >= 0 else center_x - fw
            p.setBrush(QBrush(QColor(self._color)))
            p.drawRoundedRect(QRectF(fx, meter_rect.y(), fw, 4), 2, 2)

    def _paint_gauge(self, p: QPainter, rect: QRectF) -> None:
        """Draw 180° semicircular gauge in the given rect with a glowing stroke."""
        # Arc spans a full circle whose diameter == rect.width, clipped to top half.
        cx = rect.x() + rect.width() / 2
        cy = rect.y() + rect.height()  # bottom of rect == horizontal diameter
        r = rect.width() / 2 - 4
        arc_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        stroke_w = 5

        # Background track (180° from left=180° to right=0°)
        pen = QPen(QColor(TOKENS["border_strong"]), stroke_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(arc_rect, 0 * 16, 180 * 16)

        # Value sweep from left (180°) clockwise to value mapped 0–100.
        frac = max(0.0, min(1.0, self._value / 100.0))
        sweep_deg = 180 * frac
        # Halo
        halo = QColor(self._color)
        halo.setAlpha(70)
        halo_pen = QPen(halo, stroke_w + 4)
        halo_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(halo_pen)
        p.drawArc(arc_rect, int(180 * 16), int(-sweep_deg * 16))
        # Foreground
        fg_pen = QPen(QColor(self._color), stroke_w)
        fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(fg_pen)
        p.drawArc(arc_rect, int(180 * 16), int(-sweep_deg * 16))

        # Center value text (mono, inside gauge)
        p.setFont(numeric_font(11, bold=True))
        p.setPen(QPen(QColor(TOKENS["text_primary"])))
        p.drawText(QRectF(rect.x(), cy - 18, rect.width(), 16),
                   Qt.AlignmentFlag.AlignCenter, f"{int(self._value)}")


class RegimeScoreboard(QWidget):
    """Container for 4 RegimeCells laid out in a 1px-gap grid."""

    _SOURCES = ("equity", "crypto", "macro", "sectors")
    _LABELS = {
        "equity":  "EQUITY REGIME",
        "crypto":  "CRYPTO REGIME",
        "macro":   "MACRO REGIME",
        "sectors": "SECTOR ROTATION",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {TOKENS['border']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 6px;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(1)
        self._cells: dict[str, RegimeCell] = {}
        for src in self._SOURCES:
            cell = RegimeCell(self._LABELS[src])
            self._cells[src] = cell
            lay.addWidget(cell, stretch=1)

    def update_source(
        self,
        source: str,
        verdict: str,
        color: str,
        score: int | None = None,
        max_score: int | None = None,
        value: float | None = None,
        sub: str = "",
        score_text: str | None = None,
    ) -> None:
        cell = self._cells.get(source)
        if cell is None:
            return
        cell.set_state(verdict=verdict, color=color, score=score,
                       max_score=max_score, value=value, sub=sub,
                       score_text=score_text)


# ── Sparkline ─────────────────────────────────────────────────────────────────

class Sparkline(QWidget):
    """Minimalist 1-color polyline; no axes, no grid. Cheap pyqtgraph-free draw."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[float] = []
        self._color: str = TOKENS["text_secondary"]
        self.setMinimumHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data, color: str | None = None) -> None:
        self._data = [float(x) for x in data if x is not None and not _isnan(x)]
        if color is None and len(self._data) >= 2:
            delta = self._data[-1] - self._data[0]
            color = TOKENS["up"] if delta > 0 else TOKENS["down"] if delta < 0 else TOKENS["text_secondary"]
        self._color = color or TOKENS["text_secondary"]
        self.update()

    def paintEvent(self, _event):
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        lo, hi = min(self._data), max(self._data)
        rng = hi - lo or 1.0
        n = len(self._data)
        pts = []
        for i, v in enumerate(self._data):
            x = i * (w - 2) / (n - 1) + 1
            y = h - 2 - (v - lo) * (h - 4) / rng
            pts.append(QPointF(x, y))
        pen = QPen(QColor(self._color), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)


def _isnan(x) -> bool:
    try:
        return x != x  # noqa: PLR0124
    except Exception:
        return False


# ── MetricCard ────────────────────────────────────────────────────────────────

class _DeltaChip(QLabel):
    """Small colored background chip for a metric delta (e.g. '+0.8')."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(numeric_font(9, bold=True))
        self.setVisible(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(15)
        self.setContentsMargins(5, 0, 5, 0)

    def set_delta(self, text: str, color: str | None = None) -> None:
        if not text:
            self.setVisible(False)
            return
        c = color or TOKENS["text_secondary"]
        self.setText(text)
        self.setStyleSheet(
            f"color: {c}; background-color: {c}28; "
            f"border: 1px solid {c}55; border-radius: 2px; padding: 0 5px;"
        )
        self.setVisible(True)


class DriverChip(QLabel):
    """Mono-labeled chip: 'LABEL VALUE' with a colored border/tint.

    direction: 'up' (risk_on), 'down' (risk_off), 'neutral' (amber/accent),
    or 'muted' (text_secondary). Compact, inline pill for sleeve drivers.
    """

    def __init__(self, label: str, value: str = "", direction: str = "muted", parent=None):
        super().__init__(parent)
        self.setFont(numeric_font(10, bold=True))
        self.setFixedHeight(20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(8, 0, 8, 0)
        self.set_chip(label, value, direction)

    def set_chip(self, label: str, value: str = "", direction: str = "muted") -> None:
        color_map = {
            "up": TOKENS["up"],
            "down": TOKENS["down"],
            "neutral": TOKENS["accent_amber"],
            "muted": TOKENS["text_secondary"],
        }
        c = color_map.get(direction, TOKENS["text_secondary"])
        text = f"{label.upper()} {value}".strip()
        self.setText(text)
        self.setStyleSheet(
            f"color: {c}; background-color: {c}1A; "
            f"border: 1px solid {c}55; border-radius: 10px; padding: 0 8px;"
        )


class MetricCard(QWidget):
    """Tile with uppercase label + delta chip, big left-aligned value (tnum),
    optional sparkline, sub-caption + '30d' footer, and a 3px colored
    left-inset accent bar driven by the value color (regime tint)."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._val_color = TOKENS["text_muted"]
        self.setMinimumSize(140, 104)
        self.setMaximumHeight(140)

        # Top row: label + delta chip
        self._label_lbl = QLabel(label.upper())
        self._label_lbl.setFont(ui_font(9, bold=True))
        self._label_lbl.setStyleSheet(
            f"color: {TOKENS['text_muted']}; letter-spacing: 0.8px; background: transparent;"
        )
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._delta_chip = _DeltaChip()

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        top_row.addWidget(self._label_lbl, stretch=1)
        top_row.addWidget(self._delta_chip)

        # Value
        self._value_lbl = QLabel("—")
        self._value_lbl.setFont(numeric_font(16, bold=True))
        self._value_lbl.setStyleSheet(f"color: {TOKENS['text_primary']}; background: transparent;")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._spark = Sparkline()
        self._spark.setMinimumHeight(22)
        self._spark.setMaximumHeight(22)
        self._spark.setVisible(False)

        # Footer: sub (left) + "30d" (right)
        self._sub_lbl = QLabel("")
        self._sub_lbl.setFont(ui_font(9))
        self._sub_lbl.setStyleSheet(
            f"color: {TOKENS['text_secondary']}; background: transparent;"
        )
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._range_lbl = QLabel("30d")
        self._range_lbl.setFont(ui_font(9, bold=True))
        self._range_lbl.setStyleSheet(
            f"color: {TOKENS['text_muted']}; letter-spacing: 0.6px; background: transparent;"
        )
        self._range_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._range_lbl.setVisible(False)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(6)
        bottom_row.addWidget(self._sub_lbl, stretch=1)
        bottom_row.addWidget(self._range_lbl)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        layout.addLayout(top_row)
        layout.addWidget(self._value_lbl)
        layout.addWidget(self._spark)
        layout.addLayout(bottom_row)

    def set_value(self, value: str, sub: str = "", color: str | None = None) -> None:
        prev = self._value_lbl.text()
        self._val_color = color or TOKENS["text_primary"]
        self._value_lbl.setStyleSheet(f"color: {self._val_color}; background: transparent;")
        self._value_lbl.setText(value)
        self._sub_lbl.setText(sub or "")
        self._sub_lbl.setVisible(bool(sub))
        if prev not in ("", "—") and prev != value:
            self._flash(prev, value)
        self.update()  # repaint left-inset accent

    def set_delta(self, text: str, color: str | None = None) -> None:
        self._delta_chip.set_delta(text, color)

    def set_sparkline(self, data, color: str | None = None,
                      delta_fmt: str | None = "{:+.1f}") -> None:
        if data is None or len(data) < 2:
            self._spark.setVisible(False)
            self._range_lbl.setVisible(False)
            return
        self._spark.set_data(data, color=color or self._val_color)
        self._spark.setVisible(True)
        self._range_lbl.setVisible(True)
        # Auto-derive a delta chip from first → last of the history window,
        # unless the caller has already set one (check via visibility).
        if delta_fmt and not self._delta_chip.isVisible():
            try:
                vals = [float(x) for x in data if x is not None and not _isnan(x)]
                if len(vals) >= 2:
                    delta = vals[-1] - vals[0]
                    dc = (TOKENS["up"] if delta > 0
                          else TOKENS["down"] if delta < 0
                          else TOKENS["text_secondary"])
                    self._delta_chip.set_delta(delta_fmt.format(delta), dc)
            except Exception:
                pass

    def _flash(self, prev: str, current: str) -> None:
        try:
            p = float(str(prev).replace(",", "").replace("%", "").strip().split()[0])
            c = float(str(current).replace(",", "").replace("%", "").strip().split()[0])
        except (ValueError, IndexError):
            return
        flash = TOKENS["up"] if c > p else TOKENS["down"] if c < p else None
        if not flash:
            return
        base_qss = f"color: {self._val_color}; background: transparent;"
        self._value_lbl.setStyleSheet(f"{base_qss} background-color: {flash}33; border-radius: 3px;")
        QTimer.singleShot(220, lambda: self._value_lbl.setStyleSheet(base_qss))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Card surface
        p.setBrush(QBrush(QColor(TOKENS["surface"])))
        p.setPen(QPen(QColor(TOKENS["border"]), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
        # 3px left-inset accent bar, colored by value color
        p.setBrush(QBrush(QColor(self._val_color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(1, 4, 3, h - 8), 1.5, 1.5)


# ── TearOffFrame ──────────────────────────────────────────────────────────────

class TearOffFrame(QWidget):
    """Wrap any inner widget with a small tear-off button. When clicked, the
    inner widget is reparented into a borderless top-level window the user can
    drag to a second monitor; clicking the (now-)dock-button puts it back.

    Position + size of the floating window is persisted via QSettings under
    the supplied `key`.
    """

    def __init__(self, key: str, inner: QWidget, title: str = "", parent=None):
        super().__init__(parent)
        self._key = key
        self._inner = inner
        self._floating: QWidget | None = None

        from PyQt6.QtCore import QSettings
        self._settings = QSettings("RiskMonitor", "Dashboard")

        self._btn = _TearOffButton()
        self._btn.setToolTip("Tear off to a separate window")
        self._btn.clicked.connect(self._toggle)

        self._wrap = QVBoxLayout(self)
        self._wrap.setContentsMargins(0, 0, 0, 0)
        self._wrap.setSpacing(0)

        self._embed_layout = QVBoxLayout()
        self._embed_layout.setContentsMargins(0, 0, 0, 0)
        self._embed_layout.setSpacing(0)

        # Top bar with just the button (overlaid on inner widget)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 4, 0)
        top.addStretch()
        top.addWidget(self._btn)
        self._embed_layout.addLayout(top)
        self._embed_layout.addWidget(self._inner)
        self._wrap.addLayout(self._embed_layout)

        self._title = title or key

    def _toggle(self) -> None:
        if self._floating is None:
            self._tear_off()
        else:
            self._dock_back()

    def _tear_off(self) -> None:
        win = QWidget()
        win.setWindowTitle(f"Risk Monitor — {self._title}")
        win.setStyleSheet(f"background: {TOKENS['bg']};")
        layout = QVBoxLayout(win)
        layout.setContentsMargins(8, 8, 8, 8)

        # Move inner widget out of embedded layout
        self._embed_layout.removeWidget(self._inner)
        self._inner.setParent(win)
        layout.addWidget(self._inner)

        # Restore previous geometry if known
        geom = self._settings.value(f"tearoff/{self._key}/geom")
        if geom is not None:
            try:
                win.restoreGeometry(geom)
            except Exception:
                win.resize(720, 480)
        else:
            win.resize(720, 480)

        win.show()
        self._floating = win
        self._btn.set_state(docked=False)

        # When user closes the floating window, re-dock automatically
        win.closeEvent = self._wrap_close_event(win.closeEvent)  # type: ignore[assignment]

    def _wrap_close_event(self, original):
        def handler(event):
            try:
                self._settings.setValue(f"tearoff/{self._key}/geom",
                                        self._floating.saveGeometry())
            except Exception:
                pass
            self._dock_back()
            event.ignore()
        return handler

    def _dock_back(self) -> None:
        if self._floating is None:
            return
        win = self._floating
        try:
            self._settings.setValue(f"tearoff/{self._key}/geom", win.saveGeometry())
        except Exception:
            pass
        self._inner.setParent(self)
        self._embed_layout.addWidget(self._inner)
        win.hide()
        win.deleteLater()
        self._floating = None
        self._btn.set_state(docked=True)


class _TearOffButton(QWidget):
    """Tiny clickable widget — shows ⤢ when docked, ⤡ when floating."""

    from PyQt6.QtCore import pyqtSignal as _sig
    clicked = _sig()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._docked = True

    def set_state(self, docked: bool) -> None:
        self._docked = docked
        self.update()

    def mousePressEvent(self, _ev):
        self.clicked.emit()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(TOKENS["text_secondary"]), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Outer rect
        p.drawRoundedRect(2, 4, 14, 10, 1.5, 1.5)
        # Diagonal arrow corner
        if self._docked:
            p.drawLine(11, 4, 16, 1)
            p.drawLine(13, 1, 16, 1)
            p.drawLine(16, 1, 16, 4)
        else:
            p.drawLine(2, 16, 7, 11)
            p.drawLine(2, 16, 5, 16)
            p.drawLine(2, 16, 2, 13)


# ── BrandMark ─────────────────────────────────────────────────────────────────

class BrandMark(QWidget):
    """16x16 rounded square with a three-segment conic gradient
    (teal/amber/red) — the Risk Monitor brand glyph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 16, 16)
        # Approximate a 3-segment conic gradient (from 210° clockwise) by
        # painting three pie slices into a rounded clip.
        from PyQt6.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addRoundedRect(rect, 3, 3)
        p.setClipPath(clip)
        # Qt angles: 0° = 3 o'clock, counter-clockwise positive, 16ths of a degree.
        # Design wants "from 210deg" CSS conic → we emulate with three 120° wedges.
        segs = [
            (TOKENS["up"],      210),
            (TOKENS["neutral"], 330),  # 210 + 120
            (TOKENS["down"],     90),  # 330 + 120 (mod 360)
        ]
        p.setPen(Qt.PenStyle.NoPen)
        for color, css_angle in segs:
            # Convert CSS conic angle (0°=up, clockwise) to Qt (0°=right, ccw)
            qt_start = (90 - css_angle) % 360
            p.setBrush(QBrush(QColor(color)))
            p.drawPie(rect, int(qt_start * 16), int(-120 * 16))
        # Inner inset (simulate 2px inset shadow of surface bg)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(TOKENS["surface"]), 2)
        p.setPen(pen)
        inset = QRectF(1, 1, 14, 14)
        path = QPainterPath()
        path.addRoundedRect(inset, 2, 2)
        p.drawPath(path)


# ── HeaderRegimeBadge ─────────────────────────────────────────────────────────

class HeaderRegimeBadge(QWidget):
    """Pill-style aggregate badge: AGGREGATE label + glowing dot + verdict
    + mono count summary (e.g. 3↑ 2→ 2↓). Tracks per-source regimes and
    surfaces the worst."""

    _SEVERITY = {"RISK-OFF": 2, "NEUTRAL": 1, "RISK-ON": 0, "—": -1}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._regimes: dict[str, dict] = {}
        self._color = TOKENS["na"]
        self._verdict = "—"
        self._counts = (0, 0, 0)  # up, neutral, down
        self.setFixedHeight(22)
        self.setMinimumWidth(180)

    def update_regime(self, source: str, regime: str, color: str) -> None:
        self._regimes[source] = {"regime": regime, "color": color}
        worst_src, worst_data = max(
            self._regimes.items(),
            key=lambda kv: self._SEVERITY.get(kv[1]["regime"], -1),
        )
        self._verdict = "MIXED" if self._is_mixed() else worst_data["regime"]
        self._color = worst_data["color"] if self._verdict != "MIXED" else TOKENS["neutral"]
        up = sum(1 for d in self._regimes.values() if d["regime"] == "RISK-ON")
        nu = sum(1 for d in self._regimes.values() if d["regime"] == "NEUTRAL")
        dn = sum(1 for d in self._regimes.values() if d["regime"] == "RISK-OFF")
        self._counts = (up, nu, dn)
        breakdown = "  ·  ".join(f"{s.upper()}: {d['regime']}" for s, d in self._regimes.items())
        self.setToolTip(breakdown)
        self.update()

    def _is_mixed(self) -> bool:
        regs = {d["regime"] for d in self._regimes.values()}
        return len(regs) >= 2 and "RISK-ON" in regs and "RISK-OFF" in regs

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(220, 22)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Pill background
        p.setBrush(QBrush(QColor(TOKENS["surface_alt"])))
        p.setPen(QPen(QColor(TOKENS["border_strong"]), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)

        x = 10
        # AGGREGATE label
        p.setPen(QPen(QColor(TOKENS["text_secondary"])))
        p.setFont(ui_font(9, bold=True))
        label = "AGGREGATE"
        fm = p.fontMetrics()
        lw = fm.horizontalAdvance(label)
        p.drawText(QRectF(x, 0, lw, h), Qt.AlignmentFlag.AlignVCenter, label)
        x += lw + 8

        # Glowing dot
        dot_r = 4
        dot_cy = h / 2
        # Halo
        halo = QColor(self._color)
        halo.setAlpha(80)
        p.setBrush(QBrush(halo))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x + dot_r, dot_cy), dot_r + 3, dot_r + 3)
        # Dot
        p.setBrush(QBrush(QColor(self._color)))
        p.drawEllipse(QPointF(x + dot_r, dot_cy), dot_r, dot_r)
        x += dot_r * 2 + 8

        # Verdict
        p.setPen(QPen(QColor(TOKENS["text_primary"])))
        p.setFont(ui_font(10, bold=True))
        fm = p.fontMetrics()
        vw = fm.horizontalAdvance(self._verdict)
        p.drawText(QRectF(x, 0, vw, h), Qt.AlignmentFlag.AlignVCenter, self._verdict)
        x += vw + 8

        # Mono counts "3↑ 2→ 2↓"
        up, nu, dn = self._counts
        counts = f"{up}↑ {nu}→ {dn}↓"
        p.setPen(QPen(QColor(TOKENS["text_muted"])))
        p.setFont(numeric_font(9))
        fm = p.fontMetrics()
        cw = fm.horizontalAdvance(counts)
        p.drawText(QRectF(x, 0, cw, h), Qt.AlignmentFlag.AlignVCenter, counts)


# ── LatencyDot ────────────────────────────────────────────────────────────────

class LatencyDot(QWidget):
    """Single colored dot + tooltip showing seconds since last successful fetch."""

    def __init__(self, source: str, warn_sec: int = 120, stale_sec: int = 600, parent=None):
        super().__init__(parent)
        self._source = source
        self._warn = warn_sec
        self._stale = stale_sec
        self._last: datetime | None = None
        self.setFixedSize(10, 10)
        self.setToolTip(f"{source}: no data yet")

    def mark(self, when: datetime | None = None) -> None:
        self._last = when or datetime.now()
        self._refresh_tooltip()
        self.update()

    def _age(self) -> float | None:
        if self._last is None:
            return None
        return (datetime.now() - self._last).total_seconds()

    def _color(self) -> str:
        age = self._age()
        if age is None:
            return TOKENS["na"]
        if age < self._warn:
            return TOKENS["latency_ok"]
        if age < self._stale:
            return TOKENS["latency_warn"]
        return TOKENS["latency_stale"]

    def _refresh_tooltip(self) -> None:
        age = self._age()
        if age is None:
            self.setToolTip(f"{self._source}: no data yet")
        elif age < 60:
            self.setToolTip(f"{self._source}: {int(age)}s ago")
        elif age < 3600:
            self.setToolTip(f"{self._source}: {int(age / 60)}m ago")
        else:
            self.setToolTip(f"{self._source}: {age / 3600:.1f}h ago")

    def tick(self) -> None:
        """Call from a 1s QTimer to keep dot color accurate as time passes."""
        self._refresh_tooltip()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(self._color())))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 10, 10)


# ── LatencyChip ───────────────────────────────────────────────────────────────

class LatencyChip(QWidget):
    """Compact chip: glowing dot + uppercase source label + seconds-since-fetch.
    Drops into the header latency group. Replaces the bare LatencyDot in the
    redesigned header while preserving the same mark()/tick() interface."""

    _LABELS = {"equity": "EQ", "crypto": "CR", "macro": "MC", "sectors": "SEC"}

    def __init__(self, source: str, warn_sec: int = 120, stale_sec: int = 600, parent=None):
        super().__init__(parent)
        self._source = source
        self._warn = warn_sec
        self._stale = stale_sec
        self._last: datetime | None = None
        self.setFixedHeight(22)
        self.setMinimumWidth(58)

    def mark(self, when: datetime | None = None) -> None:
        self._last = when or datetime.now()
        self.update()

    def tick(self) -> None:
        self.update()

    def _age(self) -> float | None:
        if self._last is None:
            return None
        return (datetime.now() - self._last).total_seconds()

    def _color(self) -> str:
        age = self._age()
        if age is None:
            return TOKENS["na"]
        if age < self._warn:
            return TOKENS["latency_ok"]
        if age < self._stale:
            return TOKENS["latency_warn"]
        return TOKENS["latency_stale"]

    def _age_text(self) -> str:
        age = self._age()
        if age is None:
            return "—"
        if age < 60:
            return f"{age:.1f}s" if age < 10 else f"{int(age)}s"
        if age < 3600:
            return f"{int(age / 60)}m"
        return f"{age / 3600:.1f}h"

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2
        color = self._color()

        # Glowing dot
        halo = QColor(color)
        halo.setAlpha(90)
        p.setBrush(QBrush(halo))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(5, cy), 5, 5)
        p.setBrush(QBrush(QColor(color)))
        p.drawEllipse(QPointF(5, cy), 3, 3)

        # Label + seconds
        label = self._LABELS.get(self._source, self._source.upper())
        text = f"{label} {self._age_text()}"
        p.setPen(QPen(QColor(TOKENS["text_muted"])))
        p.setFont(ui_font(9, bold=True))
        p.drawText(QRectF(13, 0, w - 13, h), Qt.AlignmentFlag.AlignVCenter, text)


# ── FlashLabel ────────────────────────────────────────────────────────────────

class FlashLabel(QLabel):
    """QLabel that briefly flashes its background green/red when its numeric
    text changes between calls to setText. Use for header tickers / KPI rows.
    """

    def __init__(self, *args, base_color: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._base_color = base_color or TOKENS["text_primary"]
        self._base_qss = f"color: {self._base_color}; background: transparent;"
        self.setStyleSheet(self._base_qss)

    def setText(self, text: str) -> None:  # type: ignore[override]
        prev = self.text()
        super().setText(text)
        if not prev or prev == "—" or prev == text:
            return
        try:
            p = float(prev.replace(",", "").replace("%", "").strip().split()[0])
            c = float(text.replace(",", "").replace("%", "").strip().split()[0])
        except (ValueError, IndexError):
            return
        flash = TOKENS["up"] if c > p else TOKENS["down"] if c < p else None
        if not flash:
            return
        self.setStyleSheet(f"{self._base_qss} background-color: {flash}33; border-radius: 3px;")
        QTimer.singleShot(220, lambda: self.setStyleSheet(self._base_qss))


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
        p.setFont(ui_font(11, bold=True))
        p.drawText(QRectF(0, 5, w, 16), Qt.AlignmentFlag.AlignCenter, "4-YEAR HALVING CYCLE")

        p.setPen(QPen(QColor(self._color)))
        p.setFont(ui_font(9, bold=True))
        p.drawText(QRectF(cx - inner * 0.85, cy - inner * 0.48, inner * 1.7, 18),
                   Qt.AlignmentFlag.AlignCenter, self._phase)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(numeric_font(10))
        p.drawText(QRectF(cx - inner * 0.85, cy - inner * 0.18, inner * 1.7, 15),
                   Qt.AlignmentFlag.AlignCenter, f"Day {self._days_in}")
        p.drawText(QRectF(cx - inner * 0.85, cy + inner * 0.08, inner * 1.7, 15),
                   Qt.AlignmentFlag.AlignCenter, f"{self._days_left}d to halving")

        action_y = cy + inner + track_w * 0.5 + 10
        p.setPen(QPen(QColor(self._color)))
        p.setFont(ui_font(13, bold=True))
        p.drawText(QRectF(0, action_y, w, 24), Qt.AlignmentFlag.AlignCenter, self._action)


# ── Treemap (squarified) ──────────────────────────────────────────────────────


def _squarify(values, x, y, w, h):
    """Return list of (x, y, w, h) rects, one per value, squarified layout."""
    rects = []
    items = list(values)
    total = sum(v for v in items if v > 0)
    if total <= 0 or not items:
        return [(x, y, 0, 0) for _ in items]
    # Normalize to area
    norm = [v / total * (w * h) for v in items]
    indices = list(range(len(items)))
    # Sort descending by area, remember original index
    order = sorted(indices, key=lambda i: -norm[i])
    sorted_norm = [norm[i] for i in order]
    placed = _squarify_recurse(sorted_norm, [], x, y, w, h, [])
    # Reorder back to original indices
    out = [None] * len(items)
    for orig_i, rect in zip(order, placed):
        out[orig_i] = rect
    return out


def _squarify_recurse(sizes, current, x, y, w, h, placed_out):
    if not sizes and not current:
        return placed_out
    if not sizes:
        return placed_out + _layout_row(current, x, y, w, h)[0]
    short = min(w, h)
    if not current:
        new_current = [sizes[0]]
        return _squarify_recurse(sizes[1:], new_current, x, y, w, h, placed_out)
    next_row = current + [sizes[0]]
    if _worst(current, short) >= _worst(next_row, short):
        return _squarify_recurse(sizes[1:], next_row, x, y, w, h, placed_out)
    row_rects, (nx, ny, nw, nh) = _layout_row(current, x, y, w, h)
    return _squarify_recurse(sizes, [], nx, ny, nw, nh, placed_out + row_rects)


def _worst(row, short):
    s = sum(row)
    if s <= 0:
        return float("inf")
    rmax = max(row)
    rmin = min(row)
    return max((short ** 2) * rmax / (s ** 2), (s ** 2) / ((short ** 2) * rmin))


def _layout_row(row, x, y, w, h):
    s = sum(row)
    if s <= 0:
        return [(x, y, 0, 0) for _ in row], (x, y, w, h)
    rects = []
    if w <= h:
        # Lay out horizontally across the top
        row_h = s / w
        cx = x
        for v in row:
            rw = v / row_h if row_h > 0 else 0
            rects.append((cx, y, rw, row_h))
            cx += rw
        return rects, (x, y + row_h, w, h - row_h)
    else:
        row_w = s / h
        cy = y
        for v in row:
            rh = v / row_w if row_w > 0 else 0
            rects.append((x, cy, row_w, rh))
            cy += rh
        return rects, (x + row_w, y, w - row_w, h)


class Treemap(QWidget):
    """Squarified treemap. Each cell colored on diverging scale by `color_value`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells: list[dict] = []
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._hover_idx: int | None = None

    def set_data(self, cells: list[dict]) -> None:
        """cells: [{label, sublabel, weight, color_value}]. color_value in roughly [-5, +5] (%)."""
        self._cells = cells or []
        self.update()

    def _color_for(self, v: float | None) -> QColor:
        if v is None:
            return QColor(COLORS["card_border"])
        # Diverging: clamp to ±3, blend
        c = max(-3.0, min(3.0, float(v))) / 3.0
        if c >= 0:
            base = QColor(COLORS["risk_on"])
            bg = QColor(COLORS["card_bg"])
            t = c
        else:
            base = QColor(COLORS["risk_off"])
            bg = QColor(COLORS["card_bg"])
            t = -c
        r = int(bg.red() + (base.red() - bg.red()) * (0.25 + 0.75 * t))
        g = int(bg.green() + (base.green() - bg.green()) * (0.25 + 0.75 * t))
        b = int(bg.blue() + (base.blue() - bg.blue()) * (0.25 + 0.75 * t))
        return QColor(r, g, b)

    def mouseMoveEvent(self, e):
        pos = e.position()
        x, y = pos.x(), pos.y()
        idx = None
        for i, c in enumerate(self._cells):
            r = c.get("_rect")
            if r and r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]:
                idx = i
                break
        if idx != self._hover_idx:
            self._hover_idx = idx
            if idx is not None:
                c = self._cells[idx]
                cv = c.get("color_value")
                cv_s = f"{cv:+.2f}%" if cv is not None else "—"
                self.setToolTip(f"{c.get('label','')} — {c.get('sublabel','')}\n{cv_s}")
            else:
                self.setToolTip("")

    def paintEvent(self, _e):
        if not self._cells:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        weights = [max(0.0001, float(c.get("weight", 1.0))) for c in self._cells]
        rects = _squarify(weights, 1, 1, w - 2, h - 2)
        for c, rect in zip(self._cells, rects):
            c["_rect"] = rect
            x, y, rw, rh = rect
            if rw < 1 or rh < 1:
                continue
            color = self._color_for(c.get("color_value"))
            p.setBrush(QBrush(color))
            p.setPen(QPen(QColor(COLORS["bg"]), 1))
            p.drawRect(QRectF(x, y, rw, rh))
            # Text only if the cell is large enough
            if rw > 38 and rh > 22:
                p.setPen(QPen(QColor(COLORS["text_primary"])))
                p.setFont(ui_font(10, bold=True))
                p.drawText(QRectF(x + 4, y + 3, rw - 8, 14),
                           Qt.AlignmentFlag.AlignLeft, str(c.get("label", "")))
                cv = c.get("color_value")
                if cv is not None and rh > 36:
                    p.setPen(QPen(QColor(COLORS["text_primary"])))
                    p.setFont(numeric_font(10, bold=True))
                    p.drawText(QRectF(x + 4, y + 18, rw - 8, 14),
                               Qt.AlignmentFlag.AlignLeft, f"{cv:+.2f}%")


# ── Correlation heatmap ───────────────────────────────────────────────────────


class CorrelationHeatmap(QWidget):
    """Symmetric NxN correlation matrix renderer. Diverging colormap, tnum cell labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels: list[str] = []
        self._matrix = None  # 2D list/np.ndarray
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_matrix(self, labels: list[str], matrix) -> None:
        self._labels = list(labels)
        self._matrix = matrix
        self.update()

    def _color(self, v: float) -> QColor:
        v = max(-1.0, min(1.0, float(v)))
        bg = QColor(COLORS["card_bg"])
        if v >= 0:
            base = QColor(COLORS["risk_on"])
        else:
            base = QColor(COLORS["risk_off"])
            v = -v
        r = int(bg.red() + (base.red() - bg.red()) * (0.15 + 0.85 * v))
        g = int(bg.green() + (base.green() - bg.green()) * (0.15 + 0.85 * v))
        b = int(bg.blue() + (base.blue() - bg.blue()) * (0.15 + 0.85 * v))
        return QColor(r, g, b)

    def paintEvent(self, _e):
        if self._matrix is None or not self._labels:
            return
        n = len(self._labels)
        if n == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        margin_l = 46
        margin_t = 22
        cell_w = max(8, (w - margin_l - 6) / n)
        cell_h = max(8, (h - margin_t - 6) / n)

        # Column labels (top)
        p.setFont(ui_font(9, bold=True))
        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        for j, lab in enumerate(self._labels):
            x = margin_l + j * cell_w
            p.drawText(QRectF(x, 2, cell_w, margin_t - 4),
                       Qt.AlignmentFlag.AlignCenter, lab)

        # Row labels + cells
        for i, lab in enumerate(self._labels):
            y = margin_t + i * cell_h
            p.setFont(ui_font(9, bold=True))
            p.setPen(QPen(QColor(COLORS["text_secondary"])))
            p.drawText(QRectF(2, y, margin_l - 4, cell_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, lab)
            for j in range(n):
                try:
                    v = float(self._matrix[i][j])
                except Exception:
                    continue
                x = margin_l + j * cell_w
                p.setBrush(QBrush(self._color(v)))
                p.setPen(QPen(QColor(COLORS["bg"]), 1))
                p.drawRect(QRectF(x, y, cell_w, cell_h))
                if cell_w >= 32 and cell_h >= 18:
                    p.setPen(QPen(QColor(COLORS["text_primary"])))
                    p.setFont(numeric_font(9))
                    p.drawText(QRectF(x, y, cell_w, cell_h),
                               Qt.AlignmentFlag.AlignCenter, f"{v:+.2f}")


class ToastNotification(QWidget):
    """Dismissible notification with a colored left border, title, body.

    tone: 'up' / 'down' / 'neutral' / 'violet' — controls border + tint.
    """

    dismissed = None  # type: ignore[assignment]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tone_color = TOKENS["down"]
        self.setVisible(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self._title = QLabel("")
        self._title.setFont(ui_font(10, bold=True))
        self._title.setStyleSheet(f"color: {TOKENS['text_primary']}; letter-spacing: 0.5px; background: transparent;")
        self._body = QLabel("")
        self._body.setFont(ui_font(10))
        self._body.setWordWrap(True)
        self._body.setStyleSheet(f"color: {TOKENS['text_secondary']}; background: transparent;")
        text_col.addWidget(self._title)
        text_col.addWidget(self._body)
        lay.addLayout(text_col, stretch=1)

        self._btn = QLabel("✕")
        self._btn.setFixedSize(18, 18)
        self._btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn.setStyleSheet(
            f"color: {TOKENS['text_muted']}; background: transparent; "
            f"border: none; font-size: 12px;"
        )
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.mousePressEvent = lambda e: self.dismiss()  # type: ignore[assignment]
        lay.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignTop)

        self._apply_tone()

    def _apply_tone(self):
        c = self._tone_color
        self.setStyleSheet(
            f"QWidget {{ background-color: {c}14; "
            f"border: 1px solid {c}55; border-left: 3px solid {c}; "
            f"border-radius: 4px; }}"
        )

    def show_toast(self, title: str, body: str, tone: str = "down"):
        tone_map = {
            "up": TOKENS["up"],
            "down": TOKENS["down"],
            "neutral": TOKENS["neutral"],
            "violet": TOKENS.get("accent_violet", TOKENS["accent_blue"]),
        }
        self._tone_color = tone_map.get(tone, TOKENS["down"])
        self._apply_tone()
        self._title.setText(title)
        self._body.setText(body)
        self.setVisible(True)

    def dismiss(self):
        self.setVisible(False)


class SignalLog(QWidget):
    """Rolling timestamped log of regime flips and notable events.

    Displays up to ``max_entries`` rows, newest on top. Each entry has
    a colored dot (tone) + HH:MM:SS timestamp + message.
    """

    def __init__(self, max_entries: int = 20, parent=None):
        super().__init__(parent)
        self._max = max_entries
        self.setStyleSheet(
            f"background: {TOKENS['surface']}; border: 1px solid {TOKENS['border']}; "
            f"border-radius: 6px;"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)

        hdr = QLabel("SIGNAL LOG")
        hdr.setFont(ui_font(9, bold=True))
        hdr.setStyleSheet(
            f"color: {TOKENS['text_muted']}; letter-spacing: 0.8px; "
            f"background: transparent; border: none;"
        )
        outer.addWidget(hdr)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(4)
        outer.addLayout(self._rows)
        outer.addStretch()

    def add_entry(self, message: str, tone: str = "neutral"):
        tone_map = {
            "up": TOKENS["up"],
            "down": TOKENS["down"],
            "neutral": TOKENS["neutral"],
            "muted": TOKENS["text_muted"],
        }
        c = tone_map.get(tone, TOKENS["text_muted"])
        ts = datetime.now().strftime("%H:%M:%S")

        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {c}; background: transparent; font-size: 11px;")
        dot.setFixedWidth(10)

        ts_lbl = QLabel(ts)
        ts_lbl.setFont(numeric_font(9))
        ts_lbl.setStyleSheet(f"color: {TOKENS['text_muted']}; background: transparent;")
        ts_lbl.setFixedWidth(58)

        msg_lbl = QLabel(message)
        msg_lbl.setFont(ui_font(10))
        msg_lbl.setStyleSheet(f"color: {TOKENS['text_primary']}; background: transparent;")
        msg_lbl.setWordWrap(True)

        h.addWidget(dot)
        h.addWidget(ts_lbl)
        h.addWidget(msg_lbl, stretch=1)

        self._rows.insertWidget(0, row)

        while self._rows.count() > self._max:
            item = self._rows.takeAt(self._rows.count() - 1)
            if item and item.widget():
                item.widget().deleteLater()
