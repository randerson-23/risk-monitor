"""
Slide-out panel for AI analysis.

Shows Claude's market assessment in a right-side panel that can be
toggled open/closed. Runs the API call in a background thread.
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QThread
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QTextEdit, QVBoxLayout, QWidget)

from widgets import COLORS, fs


class AnalysisWorker(QThread):
    """Run the Anthropic API call off the main thread."""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, snapshot, equity_data, crypto_data, macro_data,
                 user_context="", sector_data=None):
        super().__init__()
        self._snapshot = snapshot
        self._equity = equity_data
        self._crypto = crypto_data
        self._macro = macro_data
        self._user_context = user_context
        self._sector_data = sector_data

    def run(self):
        try:
            from ai_analysis import run_analysis
            result = run_analysis(self._snapshot, self._equity,
                                  self._crypto, self._macro,
                                  user_context=self._user_context,
                                  sector_data=self._sector_data)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class AIPanel(QFrame):
    """
    Right-side slide-out panel showing AI analysis.
    Width animates between 0 (closed) and target width (open).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_open = False
        self._target_width = 480
        self._worker: AnalysisWorker | None = None

        self.setFixedWidth(0)
        self.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border-left: 2px solid {COLORS['accent']};"
        )

        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header bar
        header = QFrame()
        header.setFixedHeight(42)
        header.setStyleSheet(
            f"background: #1c2128; border: none; "
            f"border-bottom: 1px solid {COLORS['card_border']};"
        )
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(12, 0, 8, 0)

        title = QLabel("🤖  AI ANALYSIS")
        title.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: {fs(14)}px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        h_lay.addWidget(title)
        h_lay.addStretch()

        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(28, 28)
        self._btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['text_secondary']};
                border: none;
                font-size: {fs(14)}px;
            }}
            QPushButton:hover {{ color: {COLORS['text_primary']}; }}
        """)
        self._btn_close.clicked.connect(self.toggle)
        h_lay.addWidget(self._btn_close)
        lay.addWidget(header)

        # Status bar
        self._status = QLabel("")
        self._status.setFixedHeight(24)
        self._status.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: {fs(14)}px; "
            f"padding: 4px 12px; border: none; background: #1c2128;"
        )
        lay.addWidget(self._status)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['card_bg']}; }}"
            f"QScrollBar:vertical {{ background: {COLORS['card_bg']}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['card_border']}; border-radius: 4px; }}"
        )

        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {COLORS['card_bg']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: none;"
            f"  padding: 12px;"
            f"  font-size: {fs(14)}px;"
            f"  font-family: 'Segoe UI', 'Consolas', monospace;"
            f"  line-height: 1.5;"
            f"}}"
        )
        self._content.setPlaceholderText(
            "Click 'Ask Claude' to get an AI-powered market assessment "
            "based on current dashboard data..."
        )
        scroll.setWidget(self._content)
        lay.addWidget(scroll, stretch=1)

        # Footer with timestamp
        self._footer = QLabel("")
        self._footer.setFixedHeight(22)
        self._footer.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; "
            f"padding: 2px 12px; border: none; "
            f"border-top: 1px solid {COLORS['card_border']};"
        )
        lay.addWidget(self._footer)

    def toggle(self):
        """Open or close the panel with animation."""
        self._is_open = not self._is_open
        target = self._target_width if self._is_open else 0

        anim = QPropertyAnimation(self, b"fixedWidth")
        # QPropertyAnimation doesn't directly support fixedWidth,
        # so we use minimumWidth + maximumWidth
        self._animate_to(target)

    def _animate_to(self, target_w: int):
        """Smoothly resize the panel."""
        # Simple step-based approach that works reliably with Qt
        self.setFixedWidth(target_w)
        if target_w == 0:
            self.hide()
        else:
            self.show()

    def is_open(self) -> bool:
        return self._is_open

    def request_analysis(self, snapshot: dict, equity_data: dict,
                          crypto_data: dict, macro_data: dict,
                          user_context: str = "", sector_data=None):
        """Start the AI analysis in a background thread."""
        if self._worker is not None and self._worker.isRunning():
            return  # already running

        # Open panel if closed
        if not self._is_open:
            self.toggle()

        self._status.setText("⏳  Analyzing current conditions...")
        self._status.setStyleSheet(
            f"color: {COLORS['neutral']}; font-size: {fs(14)}px; "
            f"padding: 4px 12px; border: none; background: #1c2128;"
        )
        self._content.setPlainText("")

        self._worker = AnalysisWorker(snapshot, equity_data, crypto_data, macro_data,
                                      user_context=user_context, sector_data=sector_data)
        self._worker.finished.connect(self._on_analysis_complete)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_complete(self, text: str):
        """Display the analysis result."""
        self._content.setMarkdown(text)
        self._status.setText("✓  Analysis complete")
        self._status.setStyleSheet(
            f"color: {COLORS['risk_on']}; font-size: {fs(14)}px; "
            f"padding: 4px 12px; border: none; background: #1c2128;"
        )

        from datetime import datetime
        self._footer.setText(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        self._worker = None

    def _on_analysis_error(self, msg: str):
        """Display error."""
        self._content.setPlainText(f"Analysis failed:\n\n{msg}")
        self._status.setText("⚠  Error")
        self._status.setStyleSheet(
            f"color: {COLORS['risk_off']}; font-size: {fs(14)}px; "
            f"padding: 4px 12px; border: none; background: #1c2128;"
        )
        self._worker = None
