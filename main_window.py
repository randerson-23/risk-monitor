import os

from PyQt6.QtCore import Qt, QSize, QSettings, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                              QHBoxLayout, QLabel, QMainWindow, QPushButton,
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
from widgets import COLORS, HeaderRegimeBadge, LatencyDot
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
            QLabel    {{ color: {COLORS['text_secondary']}; font-size: 14px; }}
            QTextEdit {{
                background: {COLORS['bg']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 4px;
                font-size: 14px;
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
                font-size: 14px;
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
                font-size: 14px;
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
        self._settings = QSettings("RiskMonitor", "Dashboard")
        self._font_size = int(self._settings.value("ui/font_size", _DEFAULT_FONT))
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
                font-size: 14px;
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
        self.tabs.setIconSize(QSize(14, 14))
        content_row.addWidget(self.tabs, stretch=1)

        # AI slide-out panel (starts hidden at width 0)
        self._ai_panel = AIPanel()
        content_row.addWidget(self._ai_panel)

        root.addLayout(content_row)

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
            f"color: {COLORS['text_primary']}; font-size: 15px; font-weight: bold; letter-spacing: 2px;"
        )
        lay.addWidget(title)

        # Aggregate regime badge (right of title)
        self.regime_badge = HeaderRegimeBadge()
        lay.addSpacing(12)
        lay.addWidget(self.regime_badge)

        lay.addStretch()

        # Latency dots — one per data source
        self._latency_dots: dict[str, LatencyDot] = {}
        for src in ("equity", "crypto", "macro", "sectors"):
            dot = LatencyDot(src)
            self._latency_dots[src] = dot
            lay.addWidget(dot)
            lay.addSpacing(6)

        self.lbl_updated = QLabel("Not yet loaded")
        self.lbl_updated.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 15px;")
        lay.addWidget(self.lbl_updated)

        # Ask Claude button
        self.btn_claude = QPushButton("🤖  Ask Claude")
        self.btn_claude.setFixedSize(112, 26)
        self.btn_claude.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #bc8cff;
                border: 1px solid #bc8cff;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover   {{ background: #bc8cff; color: {COLORS['bg']}; }}
            QPushButton:disabled {{ color: {COLORS['text_secondary']};
                                    border-color: {COLORS['card_border']}; }}
        """)
        self.btn_claude.clicked.connect(self._ask_claude)
        lay.addWidget(self.btn_claude)

        # Refresh button
        self.btn_refresh = QPushButton("⟳  Refresh")
        self.btn_refresh.setFixedSize(88, 26)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['accent']};
                border: 1px solid {COLORS['accent']};
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover   {{ background: {COLORS['accent']}; color: {COLORS['bg']}; }}
            QPushButton:disabled {{ color: {COLORS['text_secondary']};
                                    border-color: {COLORS['card_border']}; }}
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
        app = QApplication.instance()
        if app:
            app.setFont(QFont("Segoe UI", self._font_size))

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

    def _on_equity_data(self, data: dict):
        self._pending.discard("equity")
        self._latency_dots["equity"].mark()
        self.equity_tab.update_data(data)
        from regime import compute_equity_regime
        r = compute_equity_regime(data)
        self.tabs.setTabIcon(self.tabs.indexOf(self.equity_tab),
                             self._regime_dot_icon(r["color"]))
        self.regime_badge.update_regime("equity", r["regime"], r["color"])
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
                betterment_eq_pct=snap["betterment_eq_pct"],
                betterment_bond_pct=snap["betterment_bond_pct"],
                btc_exposure_pct=snap["btc_exposure"],
                equity_data=self.equity_tab._data if hasattr(self.equity_tab, "_data") else {},
                crypto_data=self.crypto_tab._data if hasattr(self.crypto_tab, "_data") else {},
                macro_data=self.macro_tab._data if hasattr(self.macro_tab, "_data") else {},
                spx_sizing=snap.get("spx_sizing", 0),
                spx_lean=snap.get("spx_lean", ""),
                ibit_sizing=snap.get("ibit_sizing", 0),
                bet_drivers=snap.get("bet_drivers"),
            )
        except Exception as exc:
            print(f"[history] log error: {exc}")
