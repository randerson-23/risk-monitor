"""
Consumer Sentiment tab — compiles recent news on economy, AI fears, job loss,
and inflation using Claude with web search.

Features:
- "Run Sentiment Analysis" button (Claude tokens required)
- Last-run timestamp with stale banner (>24 hours)
- Risk On / Off indicator for consumer sentiment
- Left pane: risk indicator + date history list (like Claude tab)
- Right pane: scrollable analysis text for selected entry
- Results are persisted to SQLite and displayed even when stale
"""

from collections import OrderedDict
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QRectF, QSettings, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                              QListWidgetItem, QPushButton, QScrollArea,
                              QSizePolicy, QVBoxLayout, QWidget)

from ai_analysis import get_recent_sentiment_analyses
from widgets import COLORS, fs
from theme import ui_font

_STALE_HOURS = 24


def _format_ts(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%b %d, %Y  %I:%M %p").lstrip("0")
    except Exception:
        return iso_str


def _format_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-I:%M %p")
    except Exception:
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return iso_str


def _format_date_label(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        day = dt.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return dt.strftime(f"%B {day}{suffix}, %Y")
    except Exception:
        return iso_str[:10]


def _date_key(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).strftime("%Y-%m-%d")
    except Exception:
        return iso_str[:10]


def _is_stale(iso_str: str) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now() - dt) > timedelta(hours=_STALE_HOURS)
    except Exception:
        return True


def _is_error_response(text: str) -> bool:
    return text.strip().startswith("⚠")


class SentimentTab(QWidget):
    """Consumer Sentiment tab powered by Claude with web search."""

    analysis_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("RiskMonitor", "Dashboard")
        self._last_run_ts: str | None = self._settings.value("sentiment/last_run_ts", None)
        self._current_score: str = "NEUTRAL"
        self._analyses_by_date: OrderedDict = OrderedDict()
        self._setup_ui()
        self.reload()

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

        # ── Left pane: risk indicator + history list ──────────────────────────
        left = QFrame()
        left.setFixedWidth(220)
        left.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border-right: 1px solid {COLORS['card_border']};"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        # Risk indicator section
        risk_section = QWidget()
        risk_section.setStyleSheet("background: transparent; border: none;")
        risk_inner = QVBoxLayout(risk_section)
        risk_inner.setContentsMargins(14, 14, 14, 10)
        risk_inner.setSpacing(8)

        section_hdr = QLabel("RISK SIGNAL")
        section_hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        risk_inner.addWidget(section_hdr)

        self._risk_indicator = _RiskOnOffCard()
        risk_inner.addWidget(self._risk_indicator)

        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;"
        )
        risk_inner.addWidget(self._lbl_status)

        left_lay.addWidget(risk_section)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {COLORS['card_border']}; border: none;")
        left_lay.addWidget(div)

        # History header
        hist_hdr = QLabel("  HISTORY")
        hist_hdr.setFixedHeight(32)
        hist_hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"font-weight: bold; letter-spacing: 1px; "
            f"padding: 8px 12px 2px 12px; border: none;"
        )
        left_lay.addWidget(hist_hdr)

        # Date list
        self._date_list = QListWidget()
        self._date_list.setStyleSheet(f"""
            QListWidget {{
                background: {COLORS['card_bg']};
                border: none;
                outline: none;
                font-size: {fs(13)}px;
            }}
            QListWidget::item {{
                color: {COLORS['text_secondary']};
                padding: 8px 14px;
                border-bottom: 1px solid {COLORS['card_border']};
            }}
            QListWidget::item:selected {{
                background: {COLORS['bg']};
                color: {COLORS['text_primary']};
                border-left: 3px solid #bc8cff;
            }}
            QListWidget::item:hover:!selected {{
                background: #1c2128;
                color: {COLORS['text_primary']};
            }}
        """)
        self._date_list.currentRowChanged.connect(self._on_date_selected)
        left_lay.addWidget(self._date_list, stretch=1)

        self._empty_list_label = QLabel("No analyses yet.")
        self._empty_list_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_list_label.setWordWrap(True)
        self._empty_list_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; "
            f"padding: 16px; border: none;"
        )
        left_lay.addWidget(self._empty_list_label)

        lay.addWidget(left)

        # ── Right pane: scrollable analysis text ──────────────────────────────
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
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_label = QLabel(
            "No analysis yet.\n\n"
            "Click  'Run Sentiment Analysis'  to compile the latest consumer\n"
            "sentiment data from economy, AI fears, job loss, and inflation news.\n\n"
            "Note: this uses Claude tokens with web search."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 14px; border: none; "
            f"padding: 40px 20px;"
        )
        self._content_layout.addWidget(self._empty_label)

        self._ts_label = QLabel("")
        self._ts_label.setStyleSheet(
            f"color: #bc8cff; font-size: {fs(13)}px; "
            f"font-weight: bold; border: none; padding-bottom: 8px;"
        )
        self._ts_label.hide()
        self._content_layout.addWidget(self._ts_label)

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

        self._content_layout.addStretch()

        scroll.setWidget(self._content_widget)
        right_lay.addWidget(scroll)
        lay.addWidget(right, stretch=1)
        return lay

    # ── History loading ────────────────────────────────────────────────────────

    def reload(self):
        """Fetch all analyses from SQLite and rebuild the date list."""
        raw = get_recent_sentiment_analyses(limit=100)

        grouped: dict[str, list[dict]] = {}
        for entry in raw:
            dk = _date_key(entry.get("timestamp", ""))
            grouped.setdefault(dk, []).append(entry)

        sorted_dates = sorted(grouped.keys(), reverse=True)
        self._analyses_by_date = OrderedDict()
        for dk in sorted_dates:
            entries = sorted(grouped[dk], key=lambda e: e.get("timestamp", ""), reverse=True)
            self._analyses_by_date[dk] = entries

        self._date_list.blockSignals(True)
        self._date_list.clear()

        if not self._analyses_by_date:
            self._empty_list_label.show()
            self._date_list.hide()
            self._date_list.blockSignals(False)
            self._show_empty()
            self._update_last_run_label()
            return

        self._empty_list_label.hide()
        self._date_list.show()

        for dk, entries in self._analyses_by_date.items():
            label = _format_date_label(entries[0].get("timestamp", dk))
            count = len(entries)
            display = f"{label}  ({count})" if count > 1 else label
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, dk)
            self._date_list.addItem(item)

        self._date_list.blockSignals(False)

        if self._date_list.count() > 0:
            self._date_list.setCurrentRow(0)

        # Update last-run from the most recent analysis
        all_entries = [e for entries in self._analyses_by_date.values() for e in entries]
        if all_entries:
            latest_ts = max(e.get("timestamp", "") for e in all_entries)
            self._last_run_ts = latest_ts
            self._settings.setValue("sentiment/last_run_ts", latest_ts)
        self._update_last_run_label()

    def _on_date_selected(self, row: int):
        if row < 0:
            return
        item = self._date_list.item(row)
        if item is None:
            return
        dk = item.data(Qt.ItemDataRole.UserRole)
        entries = self._analyses_by_date.get(dk, [])
        if entries:
            self._display_entry(entries[0])

    def _show_empty(self):
        self._ts_label.hide()
        self._response_label.hide()
        self._empty_label.show()

    def _display_entry(self, entry: dict):
        ts = entry.get("timestamp", "")
        score = entry.get("sentiment_score", "NEUTRAL").upper()
        response = entry.get("response", "")

        self._current_score = score
        self._risk_indicator.set_score(score)

        if response:
            self._empty_label.hide()
            date_display = _format_date_label(ts)
            time_display = _format_time(ts)
            self._ts_label.setText(f"🤖  {date_display}  ·  {time_display}")
            self._ts_label.show()
            self._response_label.setText(response)
            self._response_label.show()
        else:
            self._show_empty()

    # ── Last-run label + stale banner ──────────────────────────────────────────

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

        response = result.get("response", "")

        if _is_error_response(response):
            # Error result: show in status bar but preserve the cached display
            self._lbl_status.setText(f"⚠  {response[:120]}")
            self._lbl_status.setStyleSheet(
                f"color: {COLORS['risk_off']}; font-size: 12px; border: none;"
            )
            return

        self._lbl_status.setText("✓  Analysis complete")
        self._lbl_status.setStyleSheet(
            f"color: {COLORS['risk_on']}; font-size: 12px; border: none;"
        )
        self.reload()

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
    """Large coloured pill showing RISK ON, RISK OFF, or NEUTRAL for consumer sentiment."""

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
