"""
Claude tab — browse historical AI analyses and send follow-up questions.

Left pane: date list (most recent at top), grouped by day.
Right pane: responses for the selected date, most recent at top,
separated by horizontal lines with timestamps.
Bottom: follow-up question input that re-uses the main analysis pipeline.
"""

from collections import OrderedDict
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                              QListWidgetItem, QPushButton, QScrollArea,
                              QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from ai_analysis import get_recent_analyses
from widgets import COLORS, fs


def _format_date_label(iso_str: str) -> str:
    """Convert '2026-04-04T14:32:00' → 'April 4th, 2026'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        day = dt.day
        if 11 <= day <= 13:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return dt.strftime(f"%B {day}{suffix}, %Y")
    except Exception:
        return iso_str[:10]


def _format_time(iso_str: str) -> str:
    """Convert ISO timestamp → '2:32 PM'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-I:%M %p") if hasattr(dt, "hour") else iso_str
    except Exception:
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return iso_str


def _date_key(iso_str: str) -> str:
    """Extract date portion for grouping."""
    try:
        return datetime.fromisoformat(iso_str).strftime("%Y-%m-%d")
    except Exception:
        return iso_str[:10]


class ClaudeTab(QWidget):
    # Emitted when the user submits a follow-up question.
    # MainWindow connects this to trigger a new analysis with user_context set.
    followup_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._analyses_by_date: OrderedDict[str, list[dict]] = OrderedDict()
        self._stream_target: QLabel | None = None
        self._stream_full_text: str = ""
        self._stream_pos: int = 0
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(12)
        self._stream_timer.timeout.connect(self._tick_stream)
        self._just_streamed_ts: str | None = None
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(
            f"background-color: {COLORS['bg']}; color: {COLORS['text_primary']};"
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left pane: date list ──────────────────────────────────────────────

        left_frame = QFrame()
        left_frame.setFixedWidth(220)
        left_frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border-right: 1px solid {COLORS['card_border']};"
        )
        left_lay = QVBoxLayout(left_frame)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        hdr = QLabel("  ANALYSIS HISTORY")
        hdr.setFixedHeight(38)
        hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; "
            f"font-weight: bold; letter-spacing: 1px; "
            f"padding: 12px 12px 4px 12px; border: none; "
            f"border-bottom: 1px solid {COLORS['card_border']};"
        )
        left_lay.addWidget(hdr)

        self._date_list = QListWidget()
        self._date_list.setStyleSheet(f"""
            QListWidget {{
                background: {COLORS['card_bg']};
                border: none;
                outline: none;
                font-size: {fs(14)}px;
            }}
            QListWidget::item {{
                color: {COLORS['text_secondary']};
                padding: 10px 14px;
                border-bottom: 1px solid {COLORS['card_border']};
            }}
            QListWidget::item:selected {{
                background: {COLORS['bg']};
                color: {COLORS['text_primary']};
                border-left: 3px solid {COLORS['accent']};
            }}
            QListWidget::item:hover:!selected {{
                background: #1c2128;
                color: {COLORS['text_primary']};
            }}
        """)
        self._date_list.currentRowChanged.connect(self._on_date_selected)
        left_lay.addWidget(self._date_list, stretch=1)

        self._empty_label = QLabel("No analyses yet.\nClick 'Ask Claude' to generate one.")
        self._empty_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; "
            f"padding: 20px; border: none;"
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        left_lay.addWidget(self._empty_label)

        root.addWidget(left_frame)

        # ── Right pane: response content + follow-up input ────────────────────

        right_frame = QFrame()
        right_frame.setStyleSheet(f"background: {COLORS['bg']}; border: none;")
        right_lay = QVBoxLayout(right_frame)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # Scroll area for responses
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['bg']}; }}"
            f"QScrollBar:vertical {{ background: {COLORS['bg']}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['card_border']}; border-radius: 4px; }}"
        )

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(20, 16, 20, 16)
        self._content_layout.setSpacing(0)
        self._content_layout.addStretch()

        scroll.setWidget(self._content_widget)
        right_lay.addWidget(scroll, stretch=1)

        # ── Follow-up input bar ───────────────────────────────────────────────

        followup_frame = QFrame()
        followup_frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border-top: 1px solid {COLORS['card_border']}; border-radius: 0;"
        )
        followup_lay = QVBoxLayout(followup_frame)
        followup_lay.setContentsMargins(16, 10, 16, 10)
        followup_lay.setSpacing(6)

        followup_hdr = QLabel("FOLLOW-UP QUESTION")
        followup_hdr.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        followup_lay.addWidget(followup_hdr)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._followup_input = QTextEdit()
        self._followup_input.setFixedHeight(64)
        self._followup_input.setPlaceholderText(
            "Ask a follow-up question about current conditions…"
        )
        self._followup_input.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS['bg']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 6px;
                font-size: 14px;
                padding: 6px 8px;
            }}
            QTextEdit:focus {{
                border-color: {COLORS['accent']};
            }}
        """)
        input_row.addWidget(self._followup_input, stretch=1)

        violet = COLORS.get("violet", COLORS["accent"])
        self._btn_send = QPushButton("Send")
        self._btn_send.setFixedSize(72, 64)
        self._btn_send.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {violet};
                border: 1px solid {violet};
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {violet}; color: {COLORS['bg']}; }}
            QPushButton:disabled {{
                color: {COLORS['text_secondary']};
                border-color: {COLORS['card_border']};
            }}
        """)
        self._btn_send.clicked.connect(self._on_send_followup)
        input_row.addWidget(self._btn_send)

        followup_lay.addLayout(input_row)

        self._followup_status = QLabel("")
        self._followup_status.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; border: none;"
        )
        followup_lay.addWidget(self._followup_status)

        right_lay.addWidget(followup_frame)
        root.addWidget(right_frame, stretch=1)

    def showEvent(self, event):
        """Reload data every time the tab becomes visible."""
        super().showEvent(event)
        self.reload()

    def reload(self):
        """Fetch analyses from SQLite and rebuild the date list."""
        raw = get_recent_analyses(limit=200)

        grouped: dict[str, list[dict]] = {}
        for entry in raw:
            dk = _date_key(entry.get("timestamp", ""))
            if dk not in grouped:
                grouped[dk] = []
            grouped[dk].append(entry)

        sorted_dates = sorted(grouped.keys(), reverse=True)
        self._analyses_by_date = OrderedDict()
        for dk in sorted_dates:
            entries = sorted(grouped[dk],
                             key=lambda e: e.get("timestamp", ""),
                             reverse=True)
            self._analyses_by_date[dk] = entries

        self._date_list.blockSignals(True)
        self._date_list.clear()

        if not self._analyses_by_date:
            self._empty_label.show()
            self._date_list.blockSignals(False)
            self._clear_content()
            return

        self._empty_label.hide()

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

    def _on_date_selected(self, row: int):
        if row < 0:
            return
        item = self._date_list.item(row)
        if item is None:
            return
        dk = item.data(Qt.ItemDataRole.UserRole)
        entries = self._analyses_by_date.get(dk, [])
        self._render_responses(entries)

    def _clear_content(self):
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _render_responses(self, entries: list[dict]):
        self._clear_content()

        for i, entry in enumerate(entries):
            if i > 0:
                divider = QFrame()
                divider.setFixedHeight(1)
                divider.setStyleSheet(
                    f"background-color: {COLORS['accent']}; border: none; margin: 0px;"
                )
                spacer_top = QWidget()
                spacer_top.setFixedHeight(16)
                spacer_top.setStyleSheet("border: none;")
                spacer_bot = QWidget()
                spacer_bot.setFixedHeight(16)
                spacer_bot.setStyleSheet("border: none;")
                self._content_layout.addWidget(spacer_top)
                self._content_layout.addWidget(divider)
                self._content_layout.addWidget(spacer_bot)

            ts_str = entry.get("timestamp", "")
            time_display = _format_time(ts_str)
            date_display = _format_date_label(ts_str)

            violet = COLORS.get("violet", COLORS["accent"])
            ts_label = QLabel(f"🤖  {date_display}  ·  {time_display}")
            ts_label.setStyleSheet(
                f"color: {violet}; font-size: {fs(13)}px; "
                f"font-weight: bold; border: none; padding: 0px;"
            )
            self._content_layout.addWidget(ts_label)

            spacer = QWidget()
            spacer.setFixedHeight(8)
            spacer.setStyleSheet("border: none;")
            self._content_layout.addWidget(spacer)

            response_text = entry.get("response", "")
            body = QLabel(response_text)
            body.setWordWrap(True)
            body.setTextFormat(Qt.TextFormat.MarkdownText)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            body.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; "
                f"line-height: 1.6; border: none; padding: 0px; "
                f"background: transparent;"
            )
            body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._content_layout.addWidget(body)

            if i == 0 and self._just_streamed_ts == entry.get("timestamp"):
                self._begin_stream(body, response_text)
                self._just_streamed_ts = None

        self._content_layout.addStretch()
        self._content_widget.adjustSize()

    # ── Streaming reveal ──────────────────────────────────────────────────────

    def _begin_stream(self, target: QLabel, text: str):
        """Reveal ``text`` in ``target`` char-by-char (4 chars / 12ms tick)."""
        self._stream_timer.stop()
        self._stream_target = target
        self._stream_full_text = text
        self._stream_pos = 0
        target.setText("▊")
        self._stream_timer.start()

    def _tick_stream(self):
        if self._stream_target is None:
            self._stream_timer.stop()
            return
        self._stream_pos = min(len(self._stream_full_text), self._stream_pos + 5)
        partial = self._stream_full_text[: self._stream_pos]
        caret = "▊" if self._stream_pos < len(self._stream_full_text) else ""
        self._stream_target.setText(partial + caret)
        if self._stream_pos >= len(self._stream_full_text):
            self._stream_timer.stop()
            self._stream_target = None

    # ── Follow-up handling ────────────────────────────────────────────────────

    def _on_send_followup(self):
        text = self._followup_input.toPlainText().strip()
        if not text:
            return
        self.set_loading(True)
        self.followup_requested.emit(text)

    def set_loading(self, loading: bool):
        """Called by MainWindow to toggle the loading state."""
        self._btn_send.setEnabled(not loading)
        self._btn_send.setText("…" if loading else "Send")
        if loading:
            self._followup_status.setText("⏳  Sending to Claude…")
            self._followup_status.setStyleSheet(
                f"color: {COLORS['neutral']}; font-size: 12px; border: none;"
            )
        else:
            self._followup_status.setText("")

    def on_followup_complete(self):
        """Called by MainWindow when the follow-up analysis finishes."""
        self.set_loading(False)
        self._followup_input.clear()
        self._followup_status.setText("✓  Response received")
        self._followup_status.setStyleSheet(
            f"color: {COLORS['risk_on']}; font-size: 12px; border: none;"
        )
        # Mark newest entry for stream-reveal, then reload.
        from ai_analysis import get_recent_analyses
        recent = get_recent_analyses(limit=1)
        if recent:
            self._just_streamed_ts = recent[0].get("timestamp")
        self.reload()

    def on_followup_error(self):
        """Called by MainWindow when the follow-up analysis fails."""
        self.set_loading(False)
        self._followup_status.setText("⚠  Request failed — check API key")
        self._followup_status.setStyleSheet(
            f"color: {COLORS['risk_off']}; font-size: 12px; border: none;"
        )
