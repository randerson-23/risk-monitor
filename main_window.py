import os

from PyQt6.QtCore import Qt, QSize, QSettings, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                              QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                              QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from ai_panel import AIPanel
from claude_tab import ClaudeTab
from crypto_tab import CryptoTab
from equity_tab import EquityTab
from history_db import log_macro_forward, log_snapshot, log_vol_forecast
from macro_tab import MacroTab
from notifications import NotificationManager, ToastWidget
from portfolio_tab import PortfolioTab
from sectors_tab import SectorsTab
from sentiment_tab import SentimentTab
from theme import TOKENS
from widgets import (BrandMark, COLORS, HeaderRegimeBadge, LatencyChip,
                     SignalLog, ToastNotification,
                     apply_font_delta_offset, fs, set_font_delta)
from workers import (CryptoWorker, EquityWorker, ForecastWorker, MacroForwardWorker,
                       MacroWorker, SectorWorker, SentimentWorker)

_REFRESH_MS = 5 * 60 * 1000  # 5 minutes
_MIN_FONT = 7
_MAX_FONT = 22
_DEFAULT_FONT = 14


class _AskClaudeDialog(QDialog):
    """Optional context input shown before sending the AI analysis request."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ask Claude")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"""
            QDialog   {{ background: {COLORS['card_bg']}; color: {COLORS['text_primary']}; }}
            QLabel    {{ color: {COLORS['text_secondary']}; font-size: {fs(14)}px; }}
            QTextEdit {{
                background: {COLORS['bg']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 4px;
                font-size: {fs(14)}px;
                padding: 6px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 14, 16, 14)

        lbl = QLabel(
            "Add specific questions or context for Claude (optional).\n"
            "Leave blank to run the standard 5-section market analysis."
        )
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        self._edit = QTextEdit()
        self._edit.setPlaceholderText(
            "e.g. \"Focus on the SPX premium strategy given the current VIX level\" "
            "or \"Should I be reducing BTC exposure this week?\""
        )
        self._edit.setFixedHeight(110)
        lay.addWidget(self._edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Send Analysis")
        btns.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #bc8cff;
                border: 1px solid #bc8cff;
                border-radius: 4px;
                padding: 4px 14px;
                font-size: {fs(14)}px;
            }}
            QPushButton:hover {{ background: #bc8cff; color: {COLORS['bg']}; }}
        """)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 4px;
                padding: 4px 14px;
                font-size: {fs(14)}px;
            }}
            QPushButton:hover {{ color: {COLORS['text_primary']}; border-color: {COLORS['text_primary']}; }}
        """)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def user_context(self) -> str:
        return self._edit.toPlainText().strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Risk Monitor")
        self.setMinimumSize(1060, 780)
        self._pending = set()
        self._sector_data: dict = {}
        self._prev_regimes: dict[str, str] = {}
        self._settings = QSettings("RiskMonitor", "Dashboard")
        self._font_size = int(self._settings.value("ui/font_size", _DEFAULT_FONT))
        # Sync the global font delta so every stylesheet built via fs()
        # starts at the persisted size.
        set_font_delta(self._font_size - _DEFAULT_FONT)
        self._applied_font_delta = self._font_size - _DEFAULT_FONT
        self._setup_ui()
        self._setup_font_shortcuts()
        self._setup_notifications()
        self._setup_workers()
        self._setup_timer()
        self._restore_window()
        self._apply_font()
        self.refresh_all()

    def _restore_window(self) -> None:
        geom = self._settings.value("ui/geometry")
        if geom is not None:
            try:
                self.restoreGeometry(geom)
            except Exception:
                pass

    def closeEvent(self, event):
        try:
            self._settings.setValue("ui/geometry", self.saveGeometry())
            self._settings.setValue("ui/font_size", self._font_size)
        except Exception:
            pass
        super().closeEvent(event)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {TOKENS['bg']}; }}
            QTabWidget::pane {{
                border: none;
                border-top: 1px solid {TOKENS['border']};
                background: {TOKENS['bg']};
                top: 0;
            }}
            QTabWidget::tab-bar {{ left: 12px; }}
            QTabBar {{
                background: {TOKENS['surface']};
                qproperty-drawBase: 0;
                border-bottom: 1px solid {TOKENS['border']};
            }}
            QTabBar::tab {{
                background: transparent;
                color: {TOKENS['text_secondary']};
                padding: 0 14px;
                height: 28px;
                border: none;
                border-bottom: 2px solid transparent;
                margin: 0;
                font-size: {fs(12)}px;
                letter-spacing: 0.5px;
            }}
            QTabBar::tab:selected {{
                color: {TOKENS['text_primary']};
                border-bottom: 2px solid {TOKENS['accent_amber']};
            }}
            QTabBar::tab:hover:!selected {{
                color: {TOKENS['text_primary']};
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # Toast notification bar
        self._toast = ToastWidget()
        root.addWidget(self._toast)

        # Main content area: tabs + AI panel side-by-side
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        self.tabs = QTabWidget()
        self.equity_tab    = EquityTab()
        self.crypto_tab    = CryptoTab()
        self.macro_tab     = MacroTab()
        self.portfolio_tab = PortfolioTab()
        self.sectors_tab   = SectorsTab()
        self.tabs.addTab(self.equity_tab,    "Equities")
        self.tabs.addTab(self.crypto_tab,    "Bitcoin")
        self.tabs.addTab(self.macro_tab,     "Macro")
        self.tabs.addTab(self.portfolio_tab, "Portfolio")
        self.tabs.addTab(self.sectors_tab,   "Sectors")
        self.sentiment_tab = SentimentTab()
        self.sentiment_tab.analysis_requested.connect(self._run_sentiment_analysis)
        self.tabs.addTab(self.sentiment_tab, "Consumer Sentiment")
        self.claude_tab = ClaudeTab()
        self.claude_tab.followup_requested.connect(self._on_followup_request)
        self.tabs.addTab(self.claude_tab,    "Claude")
        # Violet dot for the Claude tab (matches design spec)
        self.tabs.setTabIcon(self.tabs.indexOf(self.claude_tab),
                             self._regime_dot_icon("#BC8CFF"))
        # Portfolio is the default/"hero" tab per the design
        self.tabs.setCurrentWidget(self.portfolio_tab)
        self.tabs.setIconSize(QSize(10, 10))

        # Right-side sublabels on the tab bar
        corner = QWidget()
        corner_lay = QHBoxLayout(corner)
        corner_lay.setContentsMargins(8, 0, 14, 0)
        corner_lay.setSpacing(18)
        self.lbl_sub_refresh = QLabel("AUTO-REFRESH · 5M")
        self.lbl_sub_session = QLabel("SESSION · — ET")
        for lbl in (self.lbl_sub_refresh, self.lbl_sub_session):
            lbl.setStyleSheet(
                f"color: {TOKENS['text_muted']}; font-size: {fs(10)}px; "
                f"letter-spacing: 0.8px; background: transparent;"
            )
            corner_lay.addWidget(lbl)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        content_row.addWidget(self.tabs, stretch=1)

        # AI slide-out panel (starts hidden at width 0)
        self._ai_panel = AIPanel()
        content_row.addWidget(self._ai_panel)

        root.addLayout(content_row)

        # Status bar (terminal-style, 22px)
        root.addWidget(self._build_status_bar())

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(22)
        bar.setStyleSheet(
            f"background: {TOKENS['surface']}; "
            f"border-top: 1px solid {TOKENS['border']};"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(16)

        def _mono(text: str, color: str | None = None):
            lbl = QLabel(text)
            c = color or TOKENS["text_muted"]
            lbl.setStyleSheet(
                f"color: {c}; font-family: 'JetBrains Mono','Consolas',monospace; "
                f"font-size: {fs(10)}px; letter-spacing: 0.3px; background: transparent; border: none;"
            )
            return lbl

        self.lbl_status_conn = _mono("● CONNECTED", TOKENS["up"])
        self.lbl_status_eq = _mono("EQ —ms")
        self.lbl_status_cr = _mono("CR —ms")
        self.lbl_status_mc = _mono("MC —ms")
        self.lbl_status_sec = _mono("SEC —ms")
        from datetime import datetime as _dt
        self.lbl_status_build = _mono(f"BUILD {_dt.now().strftime('%Y.%m.%d')}")

        lay.addWidget(self.lbl_status_conn)
        lay.addWidget(self.lbl_status_eq)
        lay.addWidget(self.lbl_status_cr)
        lay.addWidget(self.lbl_status_mc)
        lay.addWidget(self.lbl_status_sec)
        lay.addStretch()
        lay.addWidget(self.lbl_status_build)
        return bar

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            f"background: {TOKENS['surface']}; "
            f"border-bottom: 1px solid {TOKENS['border']};"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        # Brand mark + wordmark
        lay.addWidget(BrandMark())
        title = QLabel("RISK MONITOR")
        title.setStyleSheet(
            f"color: {TOKENS['text_primary']}; font-size: {fs(13)}px; "
            f"font-weight: 700; letter-spacing: 2px; background: transparent;"
        )
        lay.addWidget(title)

        # Aggregate regime badge
        self.regime_badge = HeaderRegimeBadge()
        lay.addWidget(self.regime_badge)

        lay.addStretch()

        # Latency group — left/right bordered cluster
        lat_wrap = QWidget()
        lat_wrap.setFixedHeight(22)
        lat_wrap.setStyleSheet(
            f"background: transparent; "
            f"border-left: 1px solid {TOKENS['border']}; "
            f"border-right: 1px solid {TOKENS['border']};"
        )
        lat_lay = QHBoxLayout(lat_wrap)
        lat_lay.setContentsMargins(8, 0, 8, 0)
        lat_lay.setSpacing(10)
        self._latency_dots: dict[str, LatencyChip] = {}
        for src in ("equity", "crypto", "macro", "sectors"):
            chip = LatencyChip(src)
            self._latency_dots[src] = chip
            lat_lay.addWidget(chip)
        lay.addWidget(lat_wrap)

        # Updated / next-refresh label (mono)
        self.lbl_updated = QLabel("Updated —  ·  next —")
        self.lbl_updated.setStyleSheet(
            f"color: {TOKENS['text_secondary']}; font-size: {fs(11)}px; "
            f"letter-spacing: 0.4px; background: transparent;"
        )
        lay.addWidget(self.lbl_updated)

        # Ask Claude button (violet, glowing dot prefix)
        self.btn_claude = QPushButton("  Ask Claude")
        self.btn_claude.setFixedHeight(26)
        self.btn_claude.setMinimumWidth(118)
        violet = "#BC8CFF"
        self.btn_claude.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {violet};
                border: 1px solid {violet};
                border-radius: 4px;
                font-size: {fs(11)}px;
                letter-spacing: 0.3px;
                padding: 0 12px;
                text-align: center;
            }}
            QPushButton:hover    {{ background: {violet}; color: {TOKENS['bg']}; }}
            QPushButton:disabled {{ color: {TOKENS['text_secondary']};
                                     border-color: {TOKENS['border']}; }}
        """)
        self.btn_claude.clicked.connect(self._ask_claude)
        lay.addWidget(self.btn_claude)

        # Font size control — unified segmented pill (− size +)
        ghost_btn_style = f"""
            QPushButton {{
                background: transparent;
                color: {TOKENS['text_secondary']};
                border: 1px solid {TOKENS['border']};
                border-radius: 4px;
                font-size: {fs(11)}px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {TOKENS['text_primary']};
                border-color: {TOKENS['border_strong']};
            }}
        """
        font_group = QWidget()
        font_group.setFixedHeight(26)
        fg_lay = QHBoxLayout(font_group)
        fg_lay.setContentsMargins(0, 0, 0, 0)
        fg_lay.setSpacing(0)

        seg_left = f"""
            QPushButton {{
                background: {TOKENS['surface']}; color: {TOKENS['text_secondary']};
                border: 1px solid {TOKENS['border']};
                border-top-left-radius: 13px; border-bottom-left-radius: 13px;
                border-top-right-radius: 0; border-bottom-right-radius: 0;
                border-right: none;
                font-size: 14px; font-weight: 600; padding: 0;
            }}
            QPushButton:hover {{ color: {TOKENS['text_primary']}; background: {TOKENS['surface_alt']}; }}
        """
        seg_mid = f"""
            QPushButton {{
                background: {TOKENS['surface']}; color: {TOKENS['text_primary']};
                border-top: 1px solid {TOKENS['border']};
                border-bottom: 1px solid {TOKENS['border']};
                border-left: none; border-right: none;
                border-radius: 0;
                font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
                padding: 0 6px;
            }}
            QPushButton:hover {{ background: {TOKENS['surface_alt']}; }}
        """
        seg_right = f"""
            QPushButton {{
                background: {TOKENS['surface']}; color: {TOKENS['text_secondary']};
                border: 1px solid {TOKENS['border']};
                border-top-right-radius: 13px; border-bottom-right-radius: 13px;
                border-top-left-radius: 0; border-bottom-left-radius: 0;
                border-left: none;
                font-size: 12px; font-weight: 700; padding: 0;
            }}
            QPushButton:hover {{ color: {TOKENS['text_primary']}; background: {TOKENS['surface_alt']}; }}
        """

        self.btn_font_dec = QPushButton("−")
        self.btn_font_dec.setFixedSize(26, 26)
        self.btn_font_dec.setToolTip("Decrease font size (Ctrl −)")
        self.btn_font_dec.setStyleSheet(seg_left)
        self.btn_font_dec.clicked.connect(self._font_down)
        fg_lay.addWidget(self.btn_font_dec)

        self.btn_font_reset = QPushButton(f"{self._font_size}")
        self.btn_font_reset.setFixedHeight(26)
        self.btn_font_reset.setMinimumWidth(30)
        self.btn_font_reset.setToolTip("Reset font size (Ctrl 0)")
        self.btn_font_reset.setStyleSheet(seg_mid)
        self.btn_font_reset.clicked.connect(self._font_reset)
        fg_lay.addWidget(self.btn_font_reset)

        self.btn_font_inc = QPushButton("+")
        self.btn_font_inc.setFixedSize(26, 26)
        self.btn_font_inc.setToolTip("Increase font size (Ctrl +)")
        self.btn_font_inc.setStyleSheet(seg_right)
        self.btn_font_inc.clicked.connect(self._font_up)
        fg_lay.addWidget(self.btn_font_inc)

        lay.addWidget(font_group)

        # Refresh button — amber accent (design)
        amber = TOKENS["accent_amber"]
        self.btn_refresh = QPushButton("⟳  Refresh")
        self.btn_refresh.setFixedHeight(26)
        self.btn_refresh.setMinimumWidth(94)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {amber};
                border: 1px solid {amber};
                border-radius: 4px;
                font-size: {fs(11)}px;
                padding: 0 12px;
            }}
            QPushButton:hover    {{ background: {amber}; color: {TOKENS['bg']}; }}
            QPushButton:disabled {{ color: {TOKENS['text_secondary']};
                                     border-color: {TOKENS['border']}; }}
        """)
        self.btn_refresh.clicked.connect(self.refresh_all)
        lay.addWidget(self.btn_refresh)

        return bar

    # ── Tab regime dot icons ────────────────────────────────────────────────────

    def _regime_dot_icon(self, color: str) -> QIcon:
        px = QPixmap(14, 14)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        p.end()
        return QIcon(px)

    # ── Ask Claude ─────────────────────────────────────────────────────────────

    def _ask_claude(self):
        """Trigger AI analysis with current dashboard state."""
        snap = self.portfolio_tab.get_snapshot_data()
        if snap is None:
            self._ai_panel.toggle()
            return

        dlg = _AskClaudeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        user_context = dlg.user_context()

        equity_data = self.equity_tab._data if hasattr(self.equity_tab, "_data") else {}
        crypto_data = self.crypto_tab._data if hasattr(self.crypto_tab, "_data") else {}
        macro_data  = self.macro_tab._data if hasattr(self.macro_tab, "_data") else {}

        self.btn_claude.setEnabled(False)
        self.btn_claude.setText("🤖  Thinking…")

        self._ai_panel.request_analysis(snap, equity_data, crypto_data, macro_data,
                                        user_context=user_context,
                                        sector_data=self._sector_data or None)

        # Re-enable button when worker finishes (connect once)
        panel = self._ai_panel
        if panel._worker is not None:
            panel._worker.finished.connect(self._on_claude_done)
            panel._worker.error.connect(self._on_claude_done)

    def _on_claude_done(self, *args):
        self.btn_claude.setEnabled(True)
        self.btn_claude.setText("🤖  Ask Claude")
        self.claude_tab.reload()

    # ── Follow-up from Claude tab ──────────────────────────────────────────────

    def _on_followup_request(self, text: str):
        """Called when the user submits a follow-up in the Claude tab."""
        snap = self.portfolio_tab.get_snapshot_data()
        if snap is None:
            self.claude_tab.on_followup_error()
            return

        equity_data = self.equity_tab._data if hasattr(self.equity_tab, "_data") else {}
        crypto_data = self.crypto_tab._data if hasattr(self.crypto_tab, "_data") else {}
        macro_data  = self.macro_tab._data if hasattr(self.macro_tab, "_data") else {}

        self._ai_panel.request_analysis(snap, equity_data, crypto_data, macro_data,
                                        user_context=text,
                                        sector_data=self._sector_data or None)

        panel = self._ai_panel
        if panel._worker is not None:
            panel._worker.finished.connect(self._on_followup_done)
            panel._worker.error.connect(self._on_followup_failed)

    def _on_followup_done(self, *args):
        self.claude_tab.on_followup_complete()

    def _on_followup_failed(self, *args):
        self.claude_tab.on_followup_error()

    # ── Consumer sentiment ─────────────────────────────────────────────────────

    def _run_sentiment_analysis(self):
        """Start the sentiment worker when the tab requests it."""
        if self._sentiment_worker.isRunning():
            return
        self._sentiment_worker.start()

    def _on_sentiment_data(self, result: dict):
        self.sentiment_tab.on_analysis_complete(result)
        # Feed the score into the regime badge as a fifth source
        score = result.get("sentiment_score", "NEUTRAL").upper()
        regime_map = {
            "BULLISH": ("RISK-ON",  COLORS["risk_on"]),
            "NEUTRAL": ("NEUTRAL",  COLORS["neutral"]),
            "BEARISH": ("RISK-OFF", COLORS["risk_off"]),
        }
        regime, color = regime_map.get(score, ("NEUTRAL", COLORS["neutral"]))
        self.regime_badge.update_regime("sentiment", regime, color)

    def _on_sentiment_error(self, msg: str):
        self.sentiment_tab.on_analysis_error(msg)

    # ── Font scaling (Ctrl+Plus / Ctrl+Minus / Ctrl+0) ──────────────────────────

    def _setup_font_shortcuts(self):
        sc_plus = QShortcut(QKeySequence("Ctrl+="), self)
        sc_plus.activated.connect(self._font_up)
        sc_plus2 = QShortcut(QKeySequence("Ctrl++"), self)
        sc_plus2.activated.connect(self._font_up)
        sc_minus = QShortcut(QKeySequence("Ctrl+-"), self)
        sc_minus.activated.connect(self._font_down)
        sc_reset = QShortcut(QKeySequence("Ctrl+0"), self)
        sc_reset.activated.connect(self._font_reset)

    def _font_up(self):
        self._font_size = min(_MAX_FONT, self._font_size + 1)
        self._apply_font()

    def _font_down(self):
        self._font_size = max(_MIN_FONT, self._font_size - 1)
        self._apply_font()

    def _font_reset(self):
        self._font_size = _DEFAULT_FONT
        self._apply_font()

    def _apply_font(self):
        # Keep widgets.fs() in sync so newly-built stylesheets pick up the
        # right size, then walk every widget and shift currently-applied
        # font-size values by the delta vs. the previous call.
        new_delta = self._font_size - _DEFAULT_FONT
        offset = new_delta - getattr(self, "_applied_font_delta", 0)
        set_font_delta(new_delta)

        app = QApplication.instance()
        if app:
            app.setFont(QFont("Segoe UI", self._font_size))

        apply_font_delta_offset(self, offset)
        self._applied_font_delta = new_delta

        # Bump explicit QFont point sizes on widgets that don't rely on
        # stylesheet font-size (custom-painted widgets, labels using setFont).
        if offset != 0:
            for w in [self] + self.findChildren(QWidget):
                f = w.font()
                ps = f.pointSize()
                if ps > 0:
                    f.setPointSize(max(_MIN_FONT, ps + offset))
                    w.setFont(f)
                w.update()

        if hasattr(self, "btn_font_reset"):
            self.btn_font_reset.setText(f"{self._font_size}")

    # ── Notifications ──────────────────────────────────────────────────────────

    def _setup_notifications(self):
        self._notifier = NotificationManager(self)
        self._notifier.set_toast_widget(self._toast)

    # ── Workers ────────────────────────────────────────────────────────────────

    def _setup_workers(self):
        self._eq_worker = EquityWorker()
        self._eq_worker.data_ready.connect(self._on_equity_data)
        self._eq_worker.data_ready.connect(self.portfolio_tab.update_equity)
        self._eq_worker.error.connect(lambda e: self._on_error("equity", e))

        self._cr_worker = CryptoWorker()
        self._cr_worker.data_ready.connect(self._on_crypto_data)
        self._cr_worker.data_ready.connect(self.portfolio_tab.update_crypto)
        self._cr_worker.error.connect(lambda e: self._on_error("crypto", e))

        self._mc_worker = MacroWorker()
        self._mc_worker.data_ready.connect(self._on_macro_data)
        self._mc_worker.data_ready.connect(self.portfolio_tab.update_macro)
        self._mc_worker.error.connect(lambda e: self._on_error("macro", e))

        self._sec_worker = SectorWorker()
        self._sec_worker.data_ready.connect(self._on_sector_data)
        self._sec_worker.error.connect(lambda e: self._on_error("sectors", e))

        self._fwd_worker = MacroForwardWorker()
        self._fwd_worker.data_ready.connect(self._on_forward_data)
        self._fwd_worker.error.connect(lambda e: self._on_error("forward", e))

        self._sentiment_worker = SentimentWorker()
        self._sentiment_worker.data_ready.connect(self._on_sentiment_data)
        self._sentiment_worker.error.connect(self._on_sentiment_error)

        # GARCH forecast workers — spawned per refresh, keyed by tag
        self._fc_workers: dict[str, ForecastWorker] = {}

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh_all)
        self._timer.start()

        # 1s ticker drives latency-dot color transitions even between refreshes
        self._latency_timer = QTimer(self)
        self._latency_timer.setInterval(1000)
        self._latency_timer.timeout.connect(self._tick_latency_dots)
        self._latency_timer.start()

    def _tick_latency_dots(self):
        for dot in self._latency_dots.values():
            dot.tick()
        self._tick_header_clock()

    def _tick_header_clock(self) -> None:
        """Update 'Updated HH:MM:SS · next M:SS' + session sublabel each second."""
        from datetime import datetime
        now = datetime.now()
        ts = getattr(self, "_last_update_ts", None)
        if ts is None:
            self.lbl_updated.setText("Updated —  ·  next —")
        else:
            remaining_ms = max(0, self._timer.remainingTime())
            mm, ss = divmod(int(remaining_ms / 1000), 60)
            self.lbl_updated.setText(
                f"Updated {ts.strftime('%H:%M:%S')}  ·  next {mm}:{ss:02d}"
            )
        if hasattr(self, "lbl_sub_session"):
            self.lbl_sub_session.setText(f"SESSION · {now.strftime('%H:%M')} ET")
        self._tick_status_bar()

    def _tick_status_bar(self):
        if not hasattr(self, "lbl_status_eq"):
            return
        chip_to_lbl = [
            ("equity", self.lbl_status_eq, "EQ"),
            ("crypto", self.lbl_status_cr, "CR"),
            ("macro", self.lbl_status_mc, "MC"),
            ("sectors", self.lbl_status_sec, "SEC"),
        ]
        from datetime import datetime as _dt
        for src, lbl, prefix in chip_to_lbl:
            chip = self._latency_dots.get(src) if hasattr(self, "_latency_dots") else None
            last = getattr(chip, "_last", None) if chip else None
            if last is None:
                lbl.setText(f"{prefix} —ms")
                lbl.setStyleSheet(
                    f"color: {TOKENS['text_muted']}; font-family: 'JetBrains Mono','Consolas',monospace; "
                    f"font-size: {fs(10)}px; letter-spacing: 0.3px; background: transparent; border: none;"
                )
                continue
            age_s = max(0.0, (_dt.now() - last).total_seconds())
            if age_s < 60:
                text = f"{prefix} {age_s * 1000:.0f}ms" if age_s < 2 else f"{prefix} {age_s:.1f}s"
            else:
                text = f"{prefix} {age_s / 60:.0f}m"
            if age_s < 2:      c = TOKENS["up"]
            elif age_s < 5:    c = TOKENS["neutral"]
            else:              c = TOKENS["down"]
            lbl.setText(text)
            lbl.setStyleSheet(
                f"color: {c}; font-family: 'JetBrains Mono','Consolas',monospace; "
                f"font-size: {fs(10)}px; letter-spacing: 0.3px; background: transparent; border: none;"
            )

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh_all(self):
        if (self._eq_worker.isRunning() and self._cr_worker.isRunning()
                and self._mc_worker.isRunning() and self._sec_worker.isRunning()):
            return

        self.btn_refresh.setEnabled(False)
        self.lbl_updated.setText("Refreshing…")

        if not self._eq_worker.isRunning():
            self._pending.add("equity")
            self._eq_worker.start()

        if not self._cr_worker.isRunning():
            self._pending.add("crypto")
            self._cr_worker.start()

        if not self._mc_worker.isRunning():
            self._pending.add("macro")
            self._mc_worker.start()

        if not self._sec_worker.isRunning():
            self._pending.add("sectors")
            self._sec_worker.start()

        if not self._fwd_worker.isRunning():
            self._pending.add("forward")
            self._fwd_worker.start()

    def _check_regime_flip(self, source: str, new_regime: str, color: str) -> None:
        """Emit toast + log entry if ``source`` regime changed since last update."""
        prev = self._prev_regimes.get(source)
        self._prev_regimes[source] = new_regime
        if prev is None or prev == new_regime:
            return
        tone_map = {"RISK-ON": "up", "RISK-OFF": "down", "NEUTRAL": "neutral"}
        tone = tone_map.get(new_regime.upper(), "neutral")
        label = source.upper()
        msg = f"{label}: {prev} → {new_regime}"
        try:
            self.portfolio_tab.toast.show_toast(
                title=f"{label} REGIME FLIP",
                body=f"Moved from {prev} to {new_regime}.",
                tone=tone,
            )
            self.portfolio_tab.signal_log.add_entry(msg, tone=tone)
        except AttributeError:
            pass

    def _on_equity_data(self, data: dict):
        self._pending.discard("equity")
        self._latency_dots["equity"].mark()
        self.equity_tab.update_data(data)
        from regime import compute_equity_regime
        r = compute_equity_regime(data)
        self.tabs.setTabIcon(self.tabs.indexOf(self.equity_tab),
                             self._regime_dot_icon(r["color"]))
        self.regime_badge.update_regime("equity", r["regime"], r["color"])
        self._check_regime_flip("equity", r["regime"], r["color"])
        # Scoreboard
        score = int(r.get("score") or 0)
        vix = data.get("vix")
        breadth = data.get("breadth_pct")
        sub_parts = []
        if vix is not None:
            sub_parts.append(f"VIX {vix}")
        if breadth is not None:
            sub_parts.append(f"Breadth {breadth:.0f}%")
        self.portfolio_tab.scoreboard.update_source(
            "equity", r["regime"], r["color"],
            score=score, max_score=8, value=50 + (score / 8) * 50,
            sub=" · ".join(sub_parts),
        )
        self._spawn_forecast("spx", data.get("spx_hist"))
        self._finish_if_done(data.get("timestamp"))

    def _on_crypto_data(self, data: dict):
        self._pending.discard("crypto")
        self._latency_dots["crypto"].mark()
        self.crypto_tab.update_data(data)
        from regime import compute_crypto_regime
        r = compute_crypto_regime(data)
        self.tabs.setTabIcon(self.tabs.indexOf(self.crypto_tab),
                             self._regime_dot_icon(r["color"]))
        self.regime_badge.update_regime("crypto", r["regime"], r["color"])
        self._check_regime_flip("crypto", r["regime"], r["color"])
        # Scoreboard
        score = int(r.get("score") or 0)
        fg = data.get("crypto_fear_greed")
        sub_parts = []
        if fg is not None:
            sub_parts.append(f"F&G {fg}")
        cycle_week = data.get("halving_week")
        if cycle_week:
            sub_parts.append(f"Cycle wk {int(cycle_week)}")
        self.portfolio_tab.scoreboard.update_source(
            "crypto", r["regime"], r["color"],
            score=score, max_score=12, value=50 + (score / 12) * 50,
            sub=" · ".join(sub_parts),
        )
        self._spawn_forecast("btc", data.get("btc_hist"))
        self._finish_if_done(data.get("timestamp"))

    def _on_forward_data(self, data: dict):
        self._pending.discard("forward")
        self.macro_tab.update_forward_risk(data)
        log_macro_forward(data)
        # Latency dot piggybacks on the macro source
        self._latency_dots["macro"].mark()
        self._finish_if_done(data.get("timestamp"))

    def _spawn_forecast(self, tag: str, prices) -> None:
        if prices is None or len(prices) < 250:
            return
        existing = self._fc_workers.get(tag)
        if existing is not None and existing.isRunning():
            return
        w = ForecastWorker(tag, prices)
        w.data_ready.connect(self._on_forecast_ready)
        w.error.connect(lambda e: print(f"[forecast] {e}"))
        self._fc_workers[tag] = w
        w.start()

    def _on_forecast_ready(self, payload: dict) -> None:
        tag = payload.get("tag")
        fc  = payload.get("forecast", {})
        if tag == "spx":
            self.equity_tab.update_forecast(fc)
            log_vol_forecast("SPX", fc)
        elif tag == "btc":
            self.crypto_tab.update_forecast(fc)
            log_vol_forecast("BTC", fc)

    def _on_macro_data(self, data: dict):
        self._pending.discard("macro")
        self._latency_dots["macro"].mark()
        self.macro_tab.update_data(data)
        from regime import compute_macro_regime
        r = compute_macro_regime(data)
        self.tabs.setTabIcon(self.tabs.indexOf(self.macro_tab),
                             self._regime_dot_icon(r["color"]))
        self.regime_badge.update_regime("macro", r["regime"], r["color"])
        self._check_regime_flip("macro", r["regime"], r["color"])
        # Scoreboard
        score = int(r.get("score") or 0)
        move = data.get("move")
        curve = data.get("yield_spread")
        sub_parts = []
        if move is not None:
            sub_parts.append(f"MOVE {move:.0f}")
        if curve is not None:
            sub_parts.append(f"Curve {curve:+.0f}bp")
        self.portfolio_tab.scoreboard.update_source(
            "macro", r["regime"], r["color"],
            score=score, max_score=8, value=50 + (score / 8) * 50,
            sub=" · ".join(sub_parts),
        )
        self._finish_if_done(data.get("timestamp"))

    def _on_sector_data(self, data: dict):
        self._pending.discard("sectors")
        self._latency_dots["sectors"].mark()
        self._sector_data = data
        self.sectors_tab.update_data(data)
        rot = data.get("rotation_regime", "MIXED")
        icon_color = {"OFFENSIVE": COLORS["risk_on"],
                      "DEFENSIVE": COLORS["risk_off"],
                      "MIXED":     COLORS["neutral"]}.get(rot, COLORS["na"])
        self.tabs.setTabIcon(self.tabs.indexOf(self.sectors_tab),
                             self._regime_dot_icon(icon_color))
        # Scoreboard: sector rotation cell
        leading = [t for t, d in data.get("sectors", {}).items()
                   if d.get("quadrant") in ("Leading", "Improving")]
        # Map rotation to gauge value
        val = {"OFFENSIVE": 78, "DEFENSIVE": 22, "MIXED": 50}.get(rot, 50)
        self.portfolio_tab.scoreboard.update_source(
            "sectors", rot, icon_color,
            value=val,
            score_text=f"{len(leading)} LEADING" if leading else "—",
            sub=", ".join(leading[:3]) + (" leading" if leading else ""),
        )
        self._finish_if_done(data.get("timestamp"))

    def _on_error(self, source: str, msg: str):
        self._pending.discard(source)
        self._finish_if_done()
        print(f"[{source}] fetch error: {msg}")

    def _finish_if_done(self, ts=None):
        if self._pending:
            return
        self.btn_refresh.setEnabled(True)
        from datetime import datetime
        self._last_update_ts = ts or datetime.now()
        self._tick_header_clock()

        # Check for allocation changes and notify
        alloc_state = self.portfolio_tab.get_allocation_state()
        if alloc_state:
            alloc_state["sector_rotation_regime"] = self._sector_data.get("rotation_regime", "")
            alloc_state["improving_sectors"] = [
                t for t, d in self._sector_data.get("sectors", {}).items()
                if d.get("quadrant") == "Improving"
            ]
            self._notifier.check_for_changes(alloc_state)

        # Log snapshot to SQLite
        self._log_to_history()

    def _log_to_history(self):
        """Write current state to the SQLite history database."""
        snap = self.portfolio_tab.get_snapshot_data()
        if snap is None:
            return
        try:
            log_snapshot(
                eq_regime=snap["eq"],
                cr_regime=snap["cr"],
                mc_regime=snap["mc"],
                overall=snap["overall"],
                betterment_eq_pct=snap["eq_pct"],
                betterment_bond_pct=snap["bond_pct"],
                btc_exposure_pct=snap["btc_exposure"],
                equity_data=self.equity_tab._data if hasattr(self.equity_tab, "_data") else {},
                crypto_data=self.crypto_tab._data if hasattr(self.crypto_tab, "_data") else {},
                macro_data=self.macro_tab._data if hasattr(self.macro_tab, "_data") else {},
                spx_sizing=snap.get("spx_sizing", 0),
                spx_lean=snap.get("spx_lean", ""),
                ibit_sizing=snap.get("ibit_sizing", 0),
                bet_drivers=snap.get("alloc_drivers"),
            )
        except Exception as exc:
            print(f"[history] log error: {exc}")
