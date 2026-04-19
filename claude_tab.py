"""
Claude tab — browse historical AI analyses.

Left pane: date list (most recent at top), grouped by day.
Right pane: responses for the selected date, most recent at top,
separated by horizontal lines with timestamps.
"""

from collections import OrderedDict
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                              QListWidgetItem, QScrollArea, QSizePolicy,
                              QSplitter, QVBoxLayout, QWidget)

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
        # Windows strftime doesn't support %-I
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self._analyses_by_date: OrderedDict[str, list[dict]] = OrderedDict()
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

        # Header
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

        # Empty state label
        self._empty_label = QLabel("No analyses yet.\nClick 'Ask Claude' to generate one.")
        self._empty_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; "
            f"padding: 20px; border: none;"
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        left_lay.addWidget(self._empty_label)

        root.addWidget(left_frame)

        # ── Right pane: response content ──────────────────────────────────────

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
        right_lay.addWidget(scroll)

        root.addWidget(right_frame, stretch=1)

    def showEvent(self, event):
        """Reload data every time the tab becomes visible."""
        super().showEvent(event)
        self.reload()

    def reload(self):
        """Fetch analyses from SQLite and rebuild the date list."""
        raw = get_recent_analyses(limit=200)

        # Group by date, most recent date first
        grouped: dict[str, list[dict]] = {}
        for entry in raw:
            dk = _date_key(entry.get("timestamp", ""))
            if dk not in grouped:
                grouped[dk] = []
            grouped[dk].append(entry)

        # Sort dates descending, responses within each date descending
        sorted_dates = sorted(grouped.keys(), reverse=True)
        self._analyses_by_date = OrderedDict()
        for dk in sorted_dates:
            entries = sorted(grouped[dk],
                             key=lambda e: e.get("timestamp", ""),
                             reverse=True)
            self._analyses_by_date[dk] = entries

        # Rebuild date list
        self._date_list.blockSignals(True)
        self._date_list.clear()

        if not self._analyses_by_date:
            self._empty_label.show()
            self._date_list.blockSignals(False)
            self._clear_content()
            return

        self._empty_label.hide()

        for dk, entries in self._analyses_by_date.items():
            # Use the first entry's timestamp for the display label
            label = _format_date_label(entries[0].get("timestamp", dk))
            count = len(entries)
            display = f"{label}  ({count})" if count > 1 else label

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, dk)
            self._date_list.addItem(item)

        self._date_list.blockSignals(False)

        # Select the first (most recent) date
        if self._date_list.count() > 0:
            self._date_list.setCurrentRow(0)

    def _on_date_selected(self, row: int):
        """Display responses for the selected date."""
        if row < 0:
            return

        item = self._date_list.item(row)
        if item is None:
            return

        dk = item.data(Qt.ItemDataRole.UserRole)
        entries = self._analyses_by_date.get(dk, [])
        self._render_responses(entries)

    def _clear_content(self):
        """Remove all widgets from the content area."""
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _render_responses(self, entries: list[dict]):
        """Render all responses for a date, most recent at top, with dividers."""
        self._clear_content()

        for i, entry in enumerate(entries):
            if i > 0:
                # Horizontal divider between responses
                divider = QFrame()
                divider.setFixedHeight(1)
                divider.setStyleSheet(
                    f"background-color: {COLORS['accent']}; border: none; "
                    f"margin: 0px;"
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

            # Timestamp header
            ts_str = entry.get("timestamp", "")
            time_display = _format_time(ts_str)
            date_display = _format_date_label(ts_str)

            ts_label = QLabel(f"🤖  {date_display}  ·  {time_display}")
            ts_label.setStyleSheet(
                f"color: {COLORS['accent']}; font-size: {fs(13)}px; "
                f"font-weight: bold; border: none; padding: 0px;"
            )
            self._content_layout.addWidget(ts_label)

            spacer = QWidget()
            spacer.setFixedHeight(8)
            spacer.setStyleSheet("border: none;")
            self._content_layout.addWidget(spacer)

            # Response body — use QLabel with word wrap for markdown-ish display
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

        self._content_layout.addStretch()

        # Scroll to top
        self._content_widget.adjustSize()
