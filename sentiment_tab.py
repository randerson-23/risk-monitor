"""
Consumer Sentiment tab — compiles recent news on economy, AI fears, job loss,
and inflation using Claude with web search.

Features:
- "Run Sentiment Analysis" button (Claude tokens required)
- Last-run timestamp with stale banner (>24 hours)
- Risk On / Off indicator for consumer sentiment
- Full analysis text display
- Results feed into the overall regime badge
"""

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QRectF, QSettings, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ai_analysis import get_latest_sentiment
from widgets import COLORS
from theme import ui_font

_STALE_HOURS = 24


def _format_ts(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%b %d, %Y  %I:%M %p").lstrip("0")
    except Exception:
        return iso_str


def _is_stale(iso_str: str) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now() - dt) > timedelta(hours=_STALE_HOURS)
    except Exception:
        return True


class SentimentTab(QWidget):
    """Consumer Sentiment tab powered by Claude with web search."""

    # Emitted when the user clicks "Run Sentiment Analysis"
    analysis_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("RiskMonitor", "Dashboard")
        self._last_run_ts: str | None = self._settings.value("sentiment/last_run_ts", None)
        self._current_score: str = "NEUTRAL"
        self._setup_ui()
        self._load_latest()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(
            f"background-color: {COLORS['bg']}; color: {COLORS['text_primary']};"
        )
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._build_header())

        self._stale_banner = self._build_stale_banner()
        root.addWidget(self._stale_banner)
        self._stale_banner.hide()

        root.addLayout(self._build_body(), stretch=1)

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(52)
        bar.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border-bottom: 1px solid {COLORS['card_border']};"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        title = QLabel("CONSUMER SENTIMENT")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        lay.addWidget(title)

        lay.addStretch()

        self._lbl_last_run = QLabel("Never run")
        self._lbl_last_run.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 13px; border: none;"
        )
        lay.addWidget(self._lbl_last_run)

        self._btn_run = QPushButton("Run Sentiment Analysis")
        self._btn_run.setFixedHeight(28)
        self._btn_run.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #bc8cff;
                border: 1px solid #bc8cff;
                border-radius: 4px;
                font-size: 13px;
                padding: 0 14px;
            }}
            QPushButton:hover   {{ background: #bc8cff; color: {COLORS['bg']}; }}
            QPushButton:disabled {{
                color: {COLORS['text_secondary']};
                border-color: {COLORS['card_border']};
            }}
        """)
        self._btn_run.clicked.connect(self._on_run_clicked)
        lay.addWidget(self._btn_run)

        return bar

    def _build_stale_banner(self) -> QLabel:
        banner = QLabel(
            f"⚠  Data is more than {_STALE_HOURS} hours old — consider re-running the analysis."
        )
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setFixedHeight(30)
        banner.setStyleSheet(
            f"background: #3d2b00; color: {COLORS['neutral']}; "
            f"font-size: 13px; border: none; "
            f"border-bottom: 1px solid {COLORS['card_border']};"
        )
        return banner

    def _build_body(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setSpacing(0)
        lay.setContentsMargins(0, 0, 0, 0)

        # Left pane: risk indicator + sub-scores
        left = QFrame()
        left.setFixedWidth(220)
        left.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border-right: 1px solid {COLORS['card_border']};"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(16, 16, 16, 16)
        left_lay.setSpacing(12)

        section_hdr = QLabel("RISK SIGNAL")
        section_hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        left_lay.addWidget(section_hdr)

        self._risk_indicator = _RiskOnOffCard()
        left_lay.addWidget(self._risk_indicator)

        left_lay.addSpacing(8)

        areas_hdr = QLabel("COVERAGE AREAS")
        areas_hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        left_lay.addWidget(areas_hdr)

        for area in ("Economy & Confidence", "AI & Job Displacement",
                     "Inflation / Cost of Living", "Employment & Layoffs"):
            lbl = QLabel(f"• {area}")
            lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 13px; border: none;"
            )
            lbl.setWordWrap(True)
            left_lay.addWidget(lbl)

        left_lay.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;"
        )
        left_lay.addWidget(self._lbl_status)

        lay.addWidget(left)

        # Right pane: scrollable analysis text
        right = QFrame()
        right.setStyleSheet(f"background: {COLORS['bg']}; border: none;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['bg']}; }}"
            f"QScrollBar:vertical {{ background: {COLORS['bg']}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['card_border']}; "
            f"border-radius: 4px; }}"
        )

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(20, 16, 20, 16)
        self._content_layout.setSpacing(0)

        self._empty_label = QLabel(
            "No analysis yet.\n\n"
            "Click  'Run Sentiment Analysis'  to compile the latest consumer\n"
            "sentiment data from economy, AI fears, job loss, and inflation news.\n\n"
            "Note: this uses Claude tokens with web search."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 14px; border: none;"
        )
        self._content_layout.addStretch()
        self._content_layout.addWidget(self._empty_label)
        self._content_layout.addStretch()

        self._response_label = QLabel("")
        self._response_label.setWordWrap(True)
        self._response_label.setTextFormat(Qt.TextFormat.MarkdownText)
        self._response_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._response_label.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14px; "
            f"line-height: 1.6; border: none; padding: 0; background: transparent;"
        )
        self._response_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._response_label.hide()
        self._content_layout.addWidget(self._response_label)

        scroll.setWidget(self._content_widget)
        right_lay.addWidget(scroll)

        lay.addWidget(right, stretch=1)
        return lay

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load_latest(self):
        """Load the most recent analysis from SQLite on startup."""
        latest = get_latest_sentiment()
        if latest:
            self._display_result(latest)
        else:
            self._update_last_run_label()

    def _update_last_run_label(self):
        if self._last_run_ts:
            self._lbl_last_run.setText(f"Last run: {_format_ts(self._last_run_ts)}")
            if _is_stale(self._last_run_ts):
                self._stale_banner.show()
            else:
                self._stale_banner.hide()
        else:
            self._lbl_last_run.setText("Never run")
            self._stale_banner.hide()

    def _display_result(self, result: dict):
        ts = result.get("timestamp", "")
        self._last_run_ts = ts
        self._settings.setValue("sentiment/last_run_ts", ts)

        score = result.get("sentiment_score", "NEUTRAL").upper()
        self._current_score = score
        self._risk_indicator.set_score(score)

        response = result.get("response", "")
        if response:
            self._empty_label.hide()
            self._response_label.setText(response)
            self._response_label.show()
        else:
            self._empty_label.show()
            self._response_label.hide()

        self._update_last_run_label()
        self._content_widget.adjustSize()

    # ── Button / worker callbacks ──────────────────────────────────────────────

    def _on_run_clicked(self):
        self._btn_run.setEnabled(False)
        self._btn_run.setText("Running…")
        self._lbl_status.setText("⏳  Querying Claude with web search…")
        self._lbl_status.setStyleSheet(
            f"color: {COLORS['neutral']}; font-size: 12px; border: none;"
        )
        self.analysis_requested.emit()

    def on_analysis_complete(self, result: dict):
        self._btn_run.setEnabled(True)
        self._btn_run.setText("Run Sentiment Analysis")
        self._lbl_status.setText("✓  Analysis complete")
        self._lbl_status.setStyleSheet(
            f"color: {COLORS['risk_on']}; font-size: 12px; border: none;"
        )
        self._display_result(result)

    def on_analysis_error(self, msg: str):
        self._btn_run.setEnabled(True)
        self._btn_run.setText("Run Sentiment Analysis")
        self._lbl_status.setText(f"⚠  Error: {msg[:80]}")
        self._lbl_status.setStyleSheet(
            f"color: {COLORS['risk_off']}; font-size: 12px; border: none;"
        )

    def sentiment_score(self) -> str:
        """Current sentiment score: BEARISH, NEUTRAL, or BULLISH."""
        return self._current_score


# ── _RiskOnOffCard ─────────────────────────────────────────────────────────────

class _RiskOnOffCard(QWidget):
    """
    Large coloured pill showing RISK ON, RISK OFF, or NEUTRAL
    for consumer sentiment.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._score = "NEUTRAL"
        self.setMinimumSize(180, 90)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_score(self, score: str):
        self._score = score.upper()
        self.update()

    def _state(self):
        if self._score == "BULLISH":
            return "RISK ON", COLORS["risk_on"]
        if self._score == "BEARISH":
            return "RISK OFF", COLORS["risk_off"]
        return "NEUTRAL", COLORS["neutral"]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        text, color = self._state()

        bg = QColor(color)
        bg.setAlpha(28)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor(color), 1.5))
        p.drawRoundedRect(2, 2, w - 4, h - 4, 8, 8)

        p.setPen(QPen(QColor(color)))
        p.setFont(ui_font(18, bold=True))
        p.drawText(QRectF(0, 0, w, h * 0.65), Qt.AlignmentFlag.AlignCenter, text)

        p.setPen(QPen(QColor(COLORS["text_secondary"])))
        p.setFont(ui_font(10))
        score_label = {
            "BULLISH": "Consumer Bullish",
            "BEARISH": "Consumer Bearish",
            "NEUTRAL": "Neutral Signal",
        }.get(self._score, self._score)
        p.drawText(QRectF(0, h * 0.62, w, h * 0.38), Qt.AlignmentFlag.AlignCenter, score_label)
