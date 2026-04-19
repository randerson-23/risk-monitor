"""
Toast notification system for allocation changes.

Uses QSystemTrayIcon for persistent notifications that require manual dismissal.
Falls back to a custom overlay widget if system tray is unavailable.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QBrush, QPixmap
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                              QPushButton, QSystemTrayIcon, QVBoxLayout,
                              QWidget)

from widgets import COLORS, fs


def _make_icon() -> QIcon:
    """Create a simple colored icon for the system tray."""
    px = QPixmap(64, 64)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(COLORS["accent"])))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QPen(QColor("#ffffff")))
    p.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    p.end()
    return QIcon(px)


class ToastWidget(QFrame):
    """
    Custom overlay toast that appears at the top of the main window.
    Stays visible until the user clicks Dismiss.
    """
    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(0)
        self._visible = False
        self.setStyleSheet(
            f"background: #1c2128; "
            f"border: 1px solid {COLORS['accent']}; "
            f"border-radius: 6px;"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        self._icon_lbl = QLabel("⚠")
        self._icon_lbl.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: {fs(16)}px; border: none;"
        )
        lay.addWidget(self._icon_lbl)

        self._msg_lbl = QLabel("")
        self._msg_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; border: none;"
        )
        self._msg_lbl.setWordWrap(True)
        lay.addWidget(self._msg_lbl, stretch=1)

        self._dismiss_btn = QPushButton("Dismiss")
        self._dismiss_btn.setFixedSize(70, 24)
        self._dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['accent']};
                color: {COLORS['bg']};
                border: none;
                border-radius: 4px;
                font-size: {fs(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #79c0ff; }}
        """)
        self._dismiss_btn.clicked.connect(self._dismiss)
        lay.addWidget(self._dismiss_btn)

    def show_toast(self, message: str, color: str = COLORS["accent"]) -> None:
        self._msg_lbl.setText(message)
        self.setStyleSheet(
            f"background: #1c2128; "
            f"border: 1px solid {color}; "
            f"border-radius: 6px;"
        )
        self._icon_lbl.setStyleSheet(
            f"color: {color}; font-size: {fs(16)}px; border: none;"
        )
        self.setFixedHeight(50)
        self._visible = True
        self.show()
        self.raise_()

    def _dismiss(self) -> None:
        self.setFixedHeight(0)
        self._visible = False
        self.hide()
        self.dismissed.emit()

    def is_showing(self) -> bool:
        return self._visible


class NotificationManager:
    """
    Manages allocation change detection and notification delivery.

    Uses system tray when available, falls back to in-app toast overlay.
    """

    def __init__(self, main_window):
        self._window = main_window
        self._prev_state: dict = {}
        self._tray: QSystemTrayIcon | None = None
        self._toast: ToastWidget | None = None

        # Try system tray first
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(_make_icon(), main_window)
            self._tray.setToolTip("Risk Monitor")
            self._tray.show()

    def set_toast_widget(self, toast: ToastWidget) -> None:
        self._toast = toast

    def check_for_changes(self, new_state: dict) -> None:
        """Compare new allocation state vs previous and fire notifications."""
        if not self._prev_state:
            self._prev_state = dict(new_state)
            return

        changes = []

        # Regime flips
        for key, label in (
            ("eq_regime",  "Equity"),
            ("cr_regime",  "Crypto"),
            ("mc_regime",  "Macro"),
        ):
            old = self._prev_state.get(key)
            new = new_state.get(key)
            if old and new and old != new:
                changes.append(f"{label} regime: {old} → {new}")

        # Significant allocation changes (>= 10pp shift)
        for key, label in (
            ("btc_exposure",  "BTC Exposure"),
            ("eq_bond_split", "Betterment Equity/Bond"),
        ):
            old = self._prev_state.get(key, 0)
            new = new_state.get(key, 0)
            if abs(new - old) >= 10:
                changes.append(f"{label}: {old}% → {new}%")

        # Sector rotation regime flip
        old_rot = self._prev_state.get("sector_rotation_regime")
        new_rot = new_state.get("sector_rotation_regime")
        if old_rot and new_rot and old_rot != new_rot:
            changes.append(f"Sector Rotation: {old_rot} → {new_rot}")

        if changes:
            msg = "ALLOCATION CHANGE:  " + "  |  ".join(changes)
            self._notify(msg)

        # Sectors entering Improving quadrant (separate alert, not bundled)
        old_imp = set(self._prev_state.get("improving_sectors", []))
        new_imp = set(new_state.get("improving_sectors", []))
        for ticker in sorted(new_imp - old_imp):
            self._notify(f"SECTOR ALERT:  {ticker} entered IMPROVING quadrant — potential entry signal",
                         color=COLORS["accent"])

        self._prev_state = dict(new_state)

    def _notify(self, message: str, color: str | None = None) -> None:
        """Show persistent notification via tray or toast."""
        # System tray notification
        if self._tray is not None:
            self._tray.showMessage(
                "Risk Monitor — Allocation Change",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                0,   # 0 = no auto-dismiss on most platforms
            )

        # In-app toast (always show as fallback / supplement)
        if self._toast is not None:
            if color is None:
                color = COLORS["neutral"]
                if "RISK-OFF" in message or "DEFENSIVE" in message:
                    color = COLORS["risk_off"]
                elif "RISK-ON" in message or "OFFENSIVE" in message:
                    color = COLORS["risk_on"]
            self._toast.show_toast(message, color)
