from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                              QTabWidget, QVBoxLayout, QWidget)

from crypto_tab import CryptoTab
from equity_tab import EquityTab
from widgets import COLORS
from workers import CryptoWorker, EquityWorker

_REFRESH_MS = 5 * 60 * 1000  # 5 minutes


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Risk Monitor")
        self.setMinimumSize(920, 700)
        self._pending = set()          # tracks which workers are still running
        self._setup_ui()
        self._setup_workers()
        self._setup_timer()
        self.refresh_all()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(f"""
            QMainWindow   {{ background: {COLORS['bg']}; }}
            QTabWidget::pane {{
                border: 1px solid {COLORS['card_border']};
                background: {COLORS['bg']};
            }}
            QTabBar::tab {{
                background: {COLORS['card_bg']};
                color: {COLORS['text_secondary']};
                padding: 8px 22px;
                border: 1px solid {COLORS['card_border']};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
            }}
            QTabBar::tab:selected {{
                background: {COLORS['bg']};
                color: {COLORS['text_primary']};
                border-bottom-color: {COLORS['bg']};
            }}
            QTabBar::tab:hover:!selected {{
                background: #1c2128;
                color: {COLORS['text_primary']};
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.equity_tab = EquityTab()
        self.crypto_tab = CryptoTab()
        self.tabs.addTab(self.equity_tab, "Equities")
        self.tabs.addTab(self.crypto_tab, "Crypto")
        root.addWidget(self.tabs)

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            f"background: {COLORS['card_bg']}; border-bottom: 1px solid {COLORS['card_border']};"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)

        title = QLabel("RISK MONITOR")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold; letter-spacing: 2px;"
        )
        lay.addWidget(title)
        lay.addStretch()

        self.lbl_updated = QLabel("Not yet loaded")
        self.lbl_updated.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px;")
        lay.addWidget(self.lbl_updated)

        self.btn_refresh = QPushButton("⟳  Refresh")
        self.btn_refresh.setFixedSize(88, 26)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['accent']};
                border: 1px solid {COLORS['accent']};
                border-radius: 4px;
                font-size: 11px;
            }}
            QPushButton:hover   {{ background: {COLORS['accent']}; color: {COLORS['bg']}; }}
            QPushButton:disabled {{ color: {COLORS['text_secondary']};
                                    border-color: {COLORS['card_border']}; }}
        """)
        self.btn_refresh.clicked.connect(self.refresh_all)
        lay.addWidget(self.btn_refresh)
        return bar

    # ── Workers ────────────────────────────────────────────────────────────────

    def _setup_workers(self):
        self._eq_worker = EquityWorker()
        self._eq_worker.data_ready.connect(self._on_equity_data)
        self._eq_worker.error.connect(lambda e: self._on_error("equity", e))

        self._cr_worker = CryptoWorker()
        self._cr_worker.data_ready.connect(self._on_crypto_data)
        self._cr_worker.error.connect(lambda e: self._on_error("crypto", e))

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh_all)
        self._timer.start()

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh_all(self):
        if self._eq_worker.isRunning() and self._cr_worker.isRunning():
            return  # already in progress

        self.btn_refresh.setEnabled(False)
        self.lbl_updated.setText("Refreshing…")

        if not self._eq_worker.isRunning():
            self._pending.add("equity")
            self._eq_worker.start()

        if not self._cr_worker.isRunning():
            self._pending.add("crypto")
            self._cr_worker.start()

    def _on_equity_data(self, data: dict):
        self._pending.discard("equity")
        self.equity_tab.update_data(data)
        self._finish_if_done(data.get("timestamp"))

    def _on_crypto_data(self, data: dict):
        self._pending.discard("crypto")
        self.crypto_tab.update_data(data)
        self._finish_if_done(data.get("timestamp"))

    def _on_error(self, source: str, msg: str):
        self._pending.discard(source)
        self._finish_if_done()
        print(f"[{source}] fetch error: {msg}")

    def _finish_if_done(self, ts=None):
        if self._pending:
            return
        self.btn_refresh.setEnabled(True)
        if ts:
            self.lbl_updated.setText(f"Updated {ts.strftime('%H:%M:%S')}")
        else:
            self.lbl_updated.setText("Updated (partial)")
