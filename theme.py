"""
Design tokens and font helpers for the Risk Monitor.

Palette derived from the Bloomberg/Koyfin-style dark institutional look:
near-black background, accessible teal-green up / red down (avoid pure
green/red for color-blindness), amber + blue accents.

Font stack:
  • Inter for UI / labels (variable weight, dense-screen legibility)
  • JetBrains Mono for tabular numerics (column-aligned digits)
If the bundled TTFs in assets/fonts/ aren't present, fall back to
platform-friendly names (Segoe UI / Consolas on Windows).
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase

# ── Tokens ────────────────────────────────────────────────────────────────────

TOKENS: dict[str, str] = {
    # Surfaces
    "bg":             "#0B0E11",
    "surface":        "#15191F",
    "surface_alt":    "#1B2029",
    "border":         "#262B33",
    "border_strong":  "#3A4150",

    # Text
    "text_primary":   "#E6E8EB",
    "text_secondary": "#8B95A1",
    "text_muted":     "#5C6573",

    # Direction (color-blind aware)
    "up":             "#26A69A",
    "down":           "#EF5350",
    "neutral":        "#D29922",

    # Accents
    "accent_amber":   "#FFA028",
    "accent_blue":    "#3B82F6",
    "accent_violet":  "#BC8CFF",

    # Latency
    "latency_ok":     "#26A69A",
    "latency_warn":   "#D29922",
    "latency_stale":  "#EF5350",

    # NA / unknown
    "na":             "#5C6573",
}

# ── Backwards-compatible alias dict ───────────────────────────────────────────
#   Existing code imports COLORS from widgets.py with these keys; preserve
#   semantics so call sites keep working unchanged.

COLORS: dict[str, str] = {
    "bg":             TOKENS["bg"],
    "card_bg":        TOKENS["surface"],
    "card_border":    TOKENS["border"],
    "text_primary":   TOKENS["text_primary"],
    "text_secondary": TOKENS["text_secondary"],
    "risk_on":        TOKENS["up"],
    "neutral":        TOKENS["neutral"],
    "risk_off":       TOKENS["down"],
    "accent":         TOKENS["accent_blue"],
    "violet":         TOKENS["accent_violet"],
    "na":             TOKENS["na"],
}


# ── Font loading ──────────────────────────────────────────────────────────────

_UI_FAMILY: str = "Segoe UI"   # set by load_fonts()
_NUM_FAMILY: str = "Consolas"  # set by load_fonts()
_FONTS_LOADED: bool = False


def _load_dir(path: Path) -> list[str]:
    families: list[str] = []
    if not path.is_dir():
        return families
    for ttf in sorted(path.glob("*.ttf")) + sorted(path.glob("*.otf")):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id != -1:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return families


def load_fonts() -> tuple[str, str]:
    """Load bundled fonts if present; return (ui_family, numeric_family)."""
    global _UI_FAMILY, _NUM_FAMILY, _FONTS_LOADED

    fonts_dir = Path(__file__).parent / "assets" / "fonts"
    loaded = _load_dir(fonts_dir)

    inter = next((f for f in loaded if "Inter" in f), None)
    jb    = next((f for f in loaded if "JetBrains" in f), None)

    available = set(QFontDatabase.families())
    _UI_FAMILY  = inter or ("Inter" if "Inter" in available else "Segoe UI")
    _NUM_FAMILY = jb    or ("JetBrains Mono" if "JetBrains Mono" in available
                            else ("Cascadia Mono" if "Cascadia Mono" in available else "Consolas"))
    _FONTS_LOADED = True
    return _UI_FAMILY, _NUM_FAMILY


def ui_font(size: int = 11, bold: bool = False) -> QFont:
    if not _FONTS_LOADED:
        load_fonts()
    f = QFont(_UI_FAMILY, size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


def numeric_font(size: int = 11, bold: bool = False) -> QFont:
    """Tabular-figure font for numbers. Enables OpenType `tnum` where supported."""
    if not _FONTS_LOADED:
        load_fonts()
    f = QFont(_NUM_FAMILY, size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    # Enable tabular numerics on proportional fonts (Qt 6.7+; harmless on monospace)
    try:
        from PyQt6.QtGui import QFont as _QF
        if hasattr(_QF, "Tag") and hasattr(f, "setFeature"):
            f.setFeature(_QF.Tag("tnum"), 1)  # type: ignore[attr-defined]
    except Exception:
        pass
    return f


def app_qss() -> str:
    """Application-wide stylesheet using the token palette."""
    t = TOKENS
    return f"""
    QMainWindow, QWidget {{
        background-color: {t['bg']};
        color: {t['text_primary']};
    }}
    QFrame, QGroupBox {{
        background-color: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 6px;
    }}
    QLabel {{
        color: {t['text_primary']};
        background: transparent;
        border: none;
    }}
    QPushButton {{
        background-color: {t['surface_alt']};
        color: {t['text_primary']};
        border: 1px solid {t['border']};
        border-radius: 4px;
        padding: 5px 12px;
    }}
    QPushButton:hover {{
        background-color: {t['border']};
        border-color: {t['border_strong']};
    }}
    QPushButton:pressed {{
        background-color: {t['border_strong']};
    }}
    QTabWidget::pane {{
        border: 1px solid {t['border']};
        background-color: {t['bg']};
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: {t['surface']};
        color: {t['text_secondary']};
        border: 1px solid {t['border']};
        border-bottom: none;
        padding: 7px 16px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {t['bg']};
        color: {t['text_primary']};
        border-bottom: 2px solid {t['accent_amber']};
    }}
    QTabBar::tab:hover:!selected {{
        color: {t['text_primary']};
    }}
    QComboBox {{
        background-color: {t['surface_alt']};
        color: {t['text_primary']};
        border: 1px solid {t['border']};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QComboBox:hover {{ border-color: {t['border_strong']}; }}
    QScrollBar:vertical {{
        background: {t['bg']}; width: 10px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t['border']}; border-radius: 5px; min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['border_strong']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QToolTip {{
        background-color: {t['surface_alt']};
        color: {t['text_primary']};
        border: 1px solid {t['border_strong']};
        padding: 4px 6px;
    }}
    QDockWidget {{
        color: {t['text_secondary']};
        titlebar-close-icon: none;
    }}
    QDockWidget::title {{
        background: {t['surface']};
        padding: 4px 8px;
        border: 1px solid {t['border']};
    }}
    """
