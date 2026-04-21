import math
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                              QScrollArea, QVBoxLayout, QWidget)

from regime import (NEUTRAL, REGIME_COLORS, RISK_OFF, RISK_ON,
                    compute_crypto_regime, compute_equity_regime,
                    compute_macro_regime)
from widgets import (COLORS, CycleClockWidget, DriverChip, RegimeScoreboard,
                     SignalLog, ToastNotification, fs)

# ── Continuous allocation functions ──────────────────────────────────────────

def _sigmoid(x: float, k: float = 2.5) -> float:
    return 1.0 / (1.0 + math.exp(-k * x))


def _btc_exposure(cr_score: int) -> int:
    """Return exposure_pct for the Bitcoin/IBIT sleeve."""
    norm = cr_score / 6.0
    return min(100, max(10, round(10 + _sigmoid(norm, k=3.0) * 90)))


def _equity_bond_split(eq_score: int, mc_score: int,
                       vix: float | None, vix_pctile: float | None,
                       move: float | None, hy_spread: float | None,
                       yield_spread: float | None,
                       real_yield: float | None,
                       breakeven_5y: float | None) -> tuple[int, int, list[str]]:
    """
    Single authoritative equity/bond split for the equity sleeve.

    Incorporates equity regime, macro regime, VIX conditions, MOVE,
    credit spreads, yield curve, real yields, and inflation expectations.

    Base: 80/20 (aggressive). Range: 40–95% equity.
    Returns (equity_pct, bond_pct, list_of_driver_notes).
    """
    eq_pct = 80.0
    notes = []

    # ── Equity regime (±15pp) ──
    eq_norm = eq_score / 8.0
    adj = round(eq_norm * 15, 1)
    eq_pct += adj
    if abs(adj) >= 3:
        direction = "risk-on" if adj > 0 else "risk-off"
        notes.append(f"Equity regime {eq_score:+d}/8 — {direction} ({adj:+.0f}pp)")

    # ── Macro regime (±10pp) ──
    mc_norm = mc_score / 7.0
    adj = round(mc_norm * 10, 1)
    eq_pct += adj
    if abs(adj) >= 3:
        direction = "supportive" if adj > 0 else "headwind"
        notes.append(f"Macro regime {mc_score:+d}/7 — {direction} ({adj:+.0f}pp)")

    # ── VIX percentile trim (0 to -12pp) ──
    if vix_pctile is not None and vix_pctile >= 70:
        trim = round((vix_pctile - 70) / 30 * 12)
        eq_pct -= trim
        notes.append(f"VIX {vix_pctile:.0f}th pctile — trimmed {trim}pp")

    # ── VIX level extreme adjustment ──
    if vix is not None:
        if vix >= 35:
            eq_pct -= 5
            notes.append(f"VIX {vix:.0f} extreme — defensive (−5pp)")
        elif vix < 13:
            notes.append(f"VIX {vix:.0f} compressed — complacency watch")

    # ── MOVE index (bond vol) ──
    if move is not None:
        if move > 130:
            eq_pct += 5
            notes.append(f"MOVE {move:.0f} — bond vol elevated, reduced bond weight (+5pp)")
        elif move > 110:
            eq_pct += 2
            notes.append(f"MOVE {move:.0f} — bond vol above normal (+2pp)")
        elif move < 80:
            eq_pct -= 5
            notes.append(f"MOVE {move:.0f} — calm bond market, bonds attractive (−5pp)")

    # ── HY credit spread ──
    if hy_spread is not None:
        if hy_spread > 6.0:
            eq_pct -= 12
            notes.append(f"HY spread {hy_spread:.1f}% — severe credit stress (−12pp)")
        elif hy_spread > 5.0:
            eq_pct -= 8
            notes.append(f"HY spread {hy_spread:.1f}% — credit stress (−8pp)")
        elif hy_spread > 4.0:
            eq_pct -= 4
            notes.append(f"HY spread {hy_spread:.1f}% — widening (−4pp)")
        elif hy_spread < 3.0:
            eq_pct += 4
            notes.append(f"HY spread {hy_spread:.1f}% — tight, risk appetite (+4pp)")

    # ── Yield curve ──
    if yield_spread is not None:
        if yield_spread < -0.5:
            eq_pct -= 5
            notes.append(f"Yield curve deeply inverted ({yield_spread:+.2f}%) — recession risk (−5pp)")
        elif yield_spread < 0:
            eq_pct -= 3
            notes.append(f"Yield curve inverted ({yield_spread:+.2f}%) (−3pp)")
        elif yield_spread > 1.5:
            eq_pct += 3
            notes.append(f"Yield curve steep ({yield_spread:+.2f}%) — growth signal (+3pp)")

    # ── Real yields (TIPS) ──
    if real_yield is not None:
        if real_yield > 2.5:
            eq_pct -= 5
            notes.append(f"Real yield {real_yield:.1f}% — bonds very attractive (−5pp)")
        elif real_yield > 2.0:
            eq_pct -= 3
            notes.append(f"Real yield {real_yield:.1f}% — bonds offer real return (−3pp)")
        elif real_yield < 0.5:
            eq_pct += 3
            notes.append(f"Real yield {real_yield:.1f}% — bonds unattractive (+3pp)")

    # ── Inflation expectations ──
    if breakeven_5y is not None:
        if breakeven_5y > 3.0:
            eq_pct += 3
            notes.append(f"5Y breakeven {breakeven_5y:.1f}% — inflation risk, favor equity (+3pp)")
        elif breakeven_5y < 1.5:
            eq_pct -= 2
            notes.append(f"5Y breakeven {breakeven_5y:.1f}% — deflation risk (−2pp)")

    # Clamp
    eq_pct = max(40, min(95, round(eq_pct)))
    bond_pct = 100 - eq_pct

    if not notes:
        notes.append("Balanced conditions — no significant adjustments")

    return eq_pct, bond_pct, notes


# ── Premium overlay for IBIT ─────────────────────────────────────────────────

def _ibit_premium_sizing(cr_score: int, btc_rv30: float | None) -> tuple[float, str]:
    if btc_rv30 is None:
        return 0.5, "— awaiting volatility data"

    if cr_score >= 3:
        sizing = 0.75
        label = "Moderate — strong risk-on, keep CC light to avoid assignment"
    elif cr_score >= 1:
        sizing = 1.0
        label = "Full — mild risk-on, good premium environment"
    elif cr_score <= -3:
        sizing = 0.5
        label = "Reduced — risk-off, accumulate via CSPs"
    elif cr_score <= -1:
        sizing = 0.75
        label = "Moderate — mild risk-off"
    else:
        sizing = 0.75
        label = "Moderate — neutral regime"

    if btc_rv30 > 80:
        sizing = min(sizing, 0.5)
        label += "  [capped — extreme BTC vol]"
    elif btc_rv30 > 60:
        sizing *= 1.1
        label += "  [vol-boosted premium]"

    return round(sizing, 2), label


def _ibit_strategy_recs(cr_score: int, ibit_price: float | None,
                         btc_rv30: float | None) -> dict:
    recs = {
        "cc_action": "—", "cc_color": COLORS["na"],
        "csp_action": "—", "csp_color": COLORS["na"],
        "lean": "—", "lean_color": COLORS["na"],
    }
    if ibit_price is None:
        return recs

    if cr_score >= 3:
        recs["cc_action"] = "LIGHT CCs — strong uptrend, widen to 0.10∆ to avoid assignment"
        recs["cc_color"] = COLORS["risk_on"]
    elif cr_score >= 1:
        recs["cc_action"] = "SELL CCs — 0.15∆ target, standard monthly cycle"
        recs["cc_color"] = COLORS["text_primary"]
    elif cr_score <= -2:
        recs["cc_action"] = "AGGRESSIVE CCs — 0.20-0.25∆, risk-off regime"
        recs["cc_color"] = COLORS["risk_off"]
    else:
        recs["cc_action"] = "SELL CCs — 0.15∆ target, standard"
        recs["cc_color"] = COLORS["text_primary"]

    if cr_score <= -3:
        recs["csp_action"] = "AGGRESSIVE CSPs — 0.25-0.30∆, accumulation zone"
        recs["csp_color"] = COLORS["risk_on"]
    elif cr_score <= -1:
        recs["csp_action"] = "SELL CSPs — 0.20∆, accumulate on weakness"
        recs["csp_color"] = COLORS["text_primary"]
    elif cr_score >= 3:
        recs["csp_action"] = "LIGHT CSPs — 0.15∆ or pause, price extended"
        recs["csp_color"] = COLORS["neutral"]
    else:
        recs["csp_action"] = "SELL CSPs — 0.20∆ target, standard"
        recs["csp_color"] = COLORS["text_primary"]

    if cr_score >= 2:
        recs["lean"] = "LEAN: Favor CSPs over CCs (bullish accumulation)"
        recs["lean_color"] = COLORS["risk_on"]
    elif cr_score <= -2:
        recs["lean"] = "LEAN: Favor CCs over CSPs (bearish income)"
        recs["lean_color"] = COLORS["risk_off"]
    else:
        recs["lean"] = "LEAN: Balanced CC + CSP"
        recs["lean_color"] = COLORS["neutral"]

    return recs


# ── SPX directional lean ─────────────────────────────────────────────────────

def _spx_directional_lean(eq_regime, eq_score, mc_regime):
    if eq_regime == RISK_ON and eq_score >= 4:
        return ("BULLISH — sell naked puts",
                "Sell naked PUTs · lean into uptrend · calls side via spread only",
                COLORS["risk_on"])
    elif eq_regime == RISK_ON:
        return ("MILD BULL — favor put side",
                "Sell naked PUTs · standard delta · can add call spread for balance",
                COLORS["risk_on"])
    elif eq_regime == RISK_OFF and eq_score <= -3:
        return ("BEARISH — sell naked calls",
                "Sell naked CALLs · lean into downtrend · puts side via spread only",
                COLORS["risk_off"])
    elif eq_regime == RISK_OFF:
        return ("MILD BEAR — favor call side",
                "Sell naked CALLs · standard delta · can add put spread for balance",
                COLORS["risk_off"])
    else:
        return ("NEUTRAL — balanced iron condor",
                "Full IC · symmetric deltas · no naked lean",
                COLORS["neutral"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _regime_vote(r):
    return 1 if r == RISK_ON else (-1 if r == RISK_OFF else 0)

def _exposure_color(pct):
    if pct >= 80: return COLORS["risk_on"]
    if pct >= 55: return COLORS["neutral"]
    return COLORS["risk_off"]

def _bar_style(color):
    return (
        f"QProgressBar {{ background: {COLORS['bg']}; "
        f"border: 1px solid {COLORS['card_border']}; border-radius: 3px; }}"
        f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
    )

def _key_signals(factors, n):
    return [f for f in factors if "(0)" not in f][:n]

def _vix_percentile(vix, hist):
    if vix is None or hist is None or hist.empty: return None
    arr = hist.dropna().to_numpy()
    return round(float((arr < vix).mean() * 100), 1)

def _iv_rank(vix, hist):
    if vix is None or hist is None or hist.empty: return None
    arr = hist.dropna().to_numpy()
    lo, hi = float(arr.min()), float(arr.max())
    if hi == lo: return None
    return round((vix - lo) / (hi - lo) * 100, 1)

def _strategy_recs(vix, eq_regime):
    TENORS = ("1DTE", "30DTE", "45DTE")
    if vix is None:
        return [(t, "—", COLORS["na"]) for t in TENORS]
    risk_off = eq_regime == RISK_OFF
    if vix < 15:     env, env_color = "low",      COLORS["risk_off"]
    elif vix < 20:   env, env_color = "normal",   COLORS["text_primary"]
    elif vix < 30:   env, env_color = "elevated", COLORS["risk_on"]
    else:            env, env_color = "extreme",  COLORS["neutral"]
    TABLE = {
        "low":     (None,          (10, 25, ""),   (12, 30, "")),
        "normal":  ((12, 15, ""),  (16, 40, ""),   (16, 40, "")),
        "elevated":((18, 20, ""),  (20, 55, ""),   (20, 50, "")),
        "extreme": ((20, 25, "tight size"), (22, 70, ""), (20, 65, "")),
    }
    rows = TABLE[env]
    results = []
    for tenor, rec in zip(TENORS, rows):
        if rec is None:
            results.append((tenor, "SKIP — IV too compressed", COLORS["risk_off"]))
            continue
        delta, wings, note = rec
        if risk_off:
            line = f"PCS  {delta}∆ put  ·  {wings}pt wing"
            note = (note + "  " if note else "") + "[risk-off: calls side off]"
        else:
            line = f"IC   {delta}∆ short  ·  {wings}pt wings"
        if note and not risk_off:
            line += f"  [{note}]"
        results.append((tenor, line, env_color))
    return results

def _premium_sizing(vix_pctile, equity_regime):
    if vix_pctile is None:
        return 0.5, "— awaiting VIX data"
    if vix_pctile >= 70:   sizing, label = 1.00, "Full — elevated vol, rich premium"
    elif vix_pctile >= 50: sizing, label = 0.75, "Reduced — moderate vol"
    elif vix_pctile >= 30: sizing, label = 0.50, "Half — compressed vol"
    else:                  sizing, label = 0.25, "Minimal — vol near lows, thin premium"
    if equity_regime == RISK_OFF:
        sizing = min(sizing, 0.50)
        label += "  [capped — equity risk-off]"
    return sizing, label


# ── Tab widget ────────────────────────────────────────────────────────────────

class PortfolioTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._equity_data: dict = {}
        self._crypto_data: dict = {}
        self._macro_data:  dict = {}
        self._prev_alloc_state: dict = {}
        self._setup_ui()

    def get_allocation_state(self) -> dict:
        return dict(self._prev_alloc_state)

    def _setup_ui(self):
        self.setStyleSheet(
            f"background-color: {COLORS['bg']}; color: {COLORS['text_primary']};"
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['bg']}; }}"
            f"QScrollBar:vertical {{ background: {COLORS['bg']}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['card_border']}; border-radius: 4px; }}"
        )
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(6)
        lay.setContentsMargins(10, 6, 10, 6)

        self.toast = ToastNotification()
        lay.addWidget(self.toast)

        self.scoreboard = RegimeScoreboard()
        lay.addWidget(self.scoreboard)

        lay.addWidget(self._build_header())

        self.signal_log = SignalLog(max_entries=10)
        lay.addWidget(self.signal_log)

        # Portfolio allocation: 3 equal cards in one row
        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(self._build_passive_etf_card(), stretch=1)
        row.addWidget(self._build_btc_ibit_card(), stretch=1)
        row.addWidget(self._build_spx_card(), stretch=1)
        lay.addLayout(row)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _card(self):
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        return f

    def _section_lbl(self, text):
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        return l

    def _divider(self):
        line = QFrame(); line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {COLORS['card_border']}; border: none;")
        return line

    def _bar(self):
        b = QProgressBar(); b.setRange(0, 100); b.setValue(0)
        b.setTextVisible(False); b.setFixedHeight(8)
        b.setStyleSheet(_bar_style(COLORS["na"]))
        return b

    def _big_lbl(self):
        l = QLabel("—")
        l.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: {fs(38)}px; "
            f"font-weight: bold; border: none;"
        )
        return l

    def _chip_strip(self):
        """Horizontal container for a row of DriverChips. Returns (widget, layout)."""
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addStretch()
        return w, h

    def _set_chips(self, layout, chips):
        """Replace all chips in ``layout`` with the given list of
        (label, value, direction) tuples."""
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for label, value, direction in chips:
            layout.addWidget(DriverChip(label, value, direction))
        layout.addStretch()

    def _signal_lbl(self):
        l = QLabel("")
        l.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; border: none;")
        l.setWordWrap(True)
        return l

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        frame = QFrame(); frame.setFixedHeight(46)
        frame.setStyleSheet(
            f"background: {COLORS['card_bg']}; "
            f"border: 1px solid {COLORS['card_border']}; border-radius: 8px;"
        )
        lay = QHBoxLayout(frame); lay.setContentsMargins(16, 0, 16, 0); lay.setSpacing(0)

        title = QLabel("PORTFOLIO ALLOCATION")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;"
        )
        lay.addWidget(title); lay.addStretch()

        def _badge(text):
            l = QLabel(text)
            l.setStyleSheet(f"color: {COLORS['na']}; font-size: {fs(13)}px; font-weight: bold; border: none;")
            return l

        self.lbl_eq_badge  = _badge("EQ: —")
        self.lbl_cr_badge  = _badge("BTC: —")
        self.lbl_mc_badge  = _badge("MACRO: —")
        self.lbl_overall   = _badge("Overall: —")
        self.lbl_overall.setStyleSheet(
            f"color: {COLORS['na']}; font-size: {fs(14)}px; font-weight: bold; border: none;"
        )
        for lbl in (self.lbl_eq_badge, self.lbl_cr_badge, self.lbl_mc_badge):
            lay.addSpacing(20); lay.addWidget(lbl)
        lay.addSpacing(28); lay.addWidget(self.lbl_overall)
        return frame

    # ── Passive ETF Allocation card ───────────────────────────────────────────

    def _build_passive_etf_card(self):
        frame = self._card()
        lay = QVBoxLayout(frame); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(4)

        hdr = QHBoxLayout()
        t = QLabel("PASSIVE ETFs")
        t.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        badge = QLabel("40% NW")
        badge.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(12)}px; border: none;")
        hdr.addWidget(t); hdr.addStretch(); hdr.addWidget(badge)
        lay.addLayout(hdr)

        self.lbl_deployed = QLabel("—")
        self.lbl_deployed.setStyleSheet(
            f"color: {COLORS['risk_on']}; font-size: {fs(36)}px; font-weight: bold; border: none;")
        lay.addWidget(self.lbl_deployed)

        self.bar_eq_bond = self._bar()
        lay.addWidget(self.bar_eq_bond)

        def _alloc_row(label):
            row = QHBoxLayout(); row.setSpacing(0)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; border: none;")
            val = QLabel("—")
            val.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: {fs(13)}px; border: none;")
            row.addWidget(lbl); row.addStretch(); row.addWidget(val)
            lay.addLayout(row)
            return val

        self.lbl_passive_eq_val   = _alloc_row("Equity (VTI/VXUS)")
        self.lbl_passive_bond_val = _alloc_row("Bonds (BND/BNDX)")

        lay.addWidget(self._divider())

        tgt_row = QHBoxLayout()
        tgt_lbl = QLabel("ALLOCATION TARGET")
        tgt_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(12)}px; letter-spacing: 1px; border: none;")
        self.lbl_alloc_target = QLabel("— / —")
        self.lbl_alloc_target.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: {fs(13)}px; font-weight: bold; border: none;")
        tgt_row.addWidget(tgt_lbl); tgt_row.addStretch(); tgt_row.addWidget(self.lbl_alloc_target)
        lay.addLayout(tgt_row)

        strip, self._alloc_chips_lay = self._chip_strip()
        lay.addWidget(strip)

        lay.addStretch()
        return frame

    # ── Bitcoin / IBIT card (merged) ──────────────────────────────────────────

    def _build_btc_ibit_card(self):
        frame = self._card()
        lay = QVBoxLayout(frame); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(4)

        hdr = QHBoxLayout()
        t = QLabel("BITCOIN / IBIT")
        t.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        badge = QLabel("40% NW")
        badge.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(12)}px; border: none;")
        hdr.addWidget(t); hdr.addStretch(); hdr.addWidget(badge)
        lay.addLayout(hdr)

        self.lbl_btc_regime = QLabel("CRYPTO: —")
        self.lbl_btc_regime.setStyleSheet(
            f"color: {COLORS['na']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        lay.addWidget(self.lbl_btc_regime)

        self.lbl_btc_pct = self._big_lbl()
        self.bar_btc = self._bar()
        lay.addWidget(self.lbl_btc_pct); lay.addWidget(self.bar_btc)

        self.lbl_btc_desc = QLabel("")
        self.lbl_btc_desc.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; border: none;")
        self.lbl_btc_desc.setWordWrap(True)
        lay.addWidget(self.lbl_btc_desc)

        lay.addWidget(self._divider())

        def _detail_row(label):
            row = QHBoxLayout(); row.setSpacing(0)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; border: none;")
            val = QLabel("—")
            val.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: {fs(13)}px; border: none;")
            val.setWordWrap(True)
            row.addWidget(lbl, stretch=0); row.addSpacing(6); row.addWidget(val, stretch=1)
            lay.addLayout(row)
            return val

        self.lbl_ibit_core_val = _detail_row("IBIT core")
        self.lbl_ibit_cc       = _detail_row("CC overlay (0.15Δ)")
        self.lbl_ibit_csp      = _detail_row("CSP (0.20Δ)")

        lay.addWidget(self._divider())

        self.lbl_cycle_phase_info = QLabel("CYCLE PHASE  —")
        self.lbl_cycle_phase_info.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {fs(12)}px; letter-spacing: 1px; border: none;")
        lay.addWidget(self.lbl_cycle_phase_info)

        strip, self._btc_ibit_chips_lay = self._chip_strip()
        lay.addWidget(strip)

        self.cycle_clock = CycleClockWidget()
        self.cycle_clock.setFixedHeight(180)
        lay.addWidget(self.cycle_clock, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addStretch()
        return frame

    # ── SPX Premium card ──────────────────────────────────────────────────────

    def _build_spx_card(self):
        frame = self._card()
        lay = QVBoxLayout(frame); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(4)

        spx_hdr = QHBoxLayout()
        t = QLabel("SPX PREMIUM SELLING")
        t.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        badge = QLabel("20% NW")
        badge.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(12)}px; border: none;")
        spx_hdr.addWidget(t); spx_hdr.addStretch(); spx_hdr.addWidget(badge)
        lay.addLayout(spx_hdr)

        strip, self._spx_chips_lay = self._chip_strip()
        lay.addWidget(strip)

        lay.addWidget(self._divider())
        lay.addWidget(self._section_lbl("DIRECTIONAL LEAN"))
        self.lbl_spx_lean = QLabel("—")
        self.lbl_spx_lean.setStyleSheet(f"color: {COLORS['na']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        self.lbl_spx_lean.setWordWrap(True)
        self.lbl_spx_naked = QLabel("—")
        self.lbl_spx_naked.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; border: none;")
        self.lbl_spx_naked.setWordWrap(True)
        lay.addWidget(self.lbl_spx_lean); lay.addWidget(self.lbl_spx_naked)

        lay.addWidget(self._divider())
        lay.addWidget(self._section_lbl("VIX CONDITIONS"))
        vix_row = QHBoxLayout()
        self.lbl_vix_val    = QLabel("VIX: —")
        self.lbl_vix_pctile = QLabel("Pctile: —  ·  IVR: —")
        for l in (self.lbl_vix_val, self.lbl_vix_pctile):
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; border: none;")
        vix_row.addWidget(self.lbl_vix_val); vix_row.addStretch(); vix_row.addWidget(self.lbl_vix_pctile)
        lay.addLayout(vix_row)
        self.bar_vix = self._bar()
        lay.addWidget(self.bar_vix)
        self.lbl_iv_rv = QLabel("IV/RV Spread: —")
        self.lbl_iv_rv.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(13)}px; border: none;")
        lay.addWidget(self.lbl_iv_rv)

        lay.addWidget(self._divider())
        lay.addWidget(self._section_lbl("POSITION SIZING"))
        self.lbl_sizing = self._big_lbl()
        self.lbl_sizing_desc = QLabel("")
        self.lbl_sizing_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; border: none;")
        self.lbl_sizing_desc.setWordWrap(True)
        lay.addWidget(self.lbl_sizing); lay.addWidget(self.lbl_sizing_desc)

        lay.addWidget(self._divider())
        lay.addWidget(self._section_lbl("EXPECTED MOVES  (1σ, SPX pts)"))
        self.lbl_ev1w = QLabel("1-Week:   —")
        self.lbl_ev1m = QLabel("1-Month:  —")
        for l in (self.lbl_ev1w, self.lbl_ev1m):
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(13)}px; border: none;")
        lay.addWidget(self.lbl_ev1w); lay.addWidget(self.lbl_ev1m)

        lay.addWidget(self._divider())
        lay.addWidget(self._section_lbl("STRATEGY GUIDE  (delta · SPX wings)"))
        self._strat_lbls: dict[str, QLabel] = {}
        for tenor in ("1DTE", "30DTE", "45DTE"):
            row = QHBoxLayout(); row.setSpacing(6)
            t_lbl = QLabel(tenor); t_lbl.setFixedWidth(38)
            t_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
            r_lbl = QLabel("—")
            r_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {fs(14)}px; border: none;")
            r_lbl.setWordWrap(True)
            self._strat_lbls[tenor] = r_lbl
            row.addWidget(t_lbl); row.addWidget(r_lbl, stretch=1)
            lay.addLayout(row)
        lay.addStretch()
        return frame

    # ── Data ingress ──────────────────────────────────────────────────────────

    def update_equity(self, data): self._equity_data = data; self._recompute()
    def update_crypto(self, data): self._crypto_data = data; self._recompute()
    def update_macro(self, data):  self._macro_data = data;  self._recompute()

    # ── Recompute ─────────────────────────────────────────────────────────────

    def _recompute(self):
        eq = compute_equity_regime(self._equity_data)
        cr = compute_crypto_regime(self._crypto_data)
        mc = compute_macro_regime(self._macro_data)

        vix_hist   = self._equity_data.get("vix_hist")
        vix        = self._equity_data.get("vix")
        vix_pctile = _vix_percentile(vix, vix_hist)
        ivr        = _iv_rank(vix, vix_hist)

        self._update_header(eq, cr, mc)
        self._update_passive_etf_card(eq, mc, vix, vix_pctile)
        self._update_btc_ibit_card(cr)
        self._update_spx_card(self._equity_data, eq, mc, vix_pctile, ivr)

        # Only update allocation state/snapshot when all data sources are populated.
        # This prevents partial-data recommendations and spurious allocation notifications.
        if not (self._equity_data and self._crypto_data and self._macro_data):
            return

        eq_bond = _equity_bond_split(
            eq.get("score", 0), mc.get("score", 0), vix, vix_pctile,
            self._macro_data.get("move"), self._macro_data.get("hy_spread"),
            self._macro_data.get("yield_spread"), self._macro_data.get("real_yield_10y"),
            self._macro_data.get("breakeven_5y"),
        )
        btc_exp = _btc_exposure(cr.get("score", 0))
        spx_sizing, _ = _premium_sizing(vix_pctile, eq["regime"])
        ibit_sizing, _ = _ibit_premium_sizing(cr.get("score", 0), self._crypto_data.get("btc_rv30"))
        lean_text, _, _ = _spx_directional_lean(eq["regime"], eq.get("score", 0), mc["regime"])

        # Determine overall regime for logging
        vote = _regime_vote(eq["regime"]) + _regime_vote(cr["regime"]) + _regime_vote(mc["regime"])
        if vote >= 2:    overall_regime = RISK_ON
        elif vote <= -2: overall_regime = RISK_OFF
        else:            overall_regime = NEUTRAL

        self._prev_alloc_state = {
            "eq_regime": eq["regime"], "cr_regime": cr["regime"], "mc_regime": mc["regime"],
            "btc_exposure": btc_exp,
            "eq_bond_split": eq_bond[0],
        }
        self._last_snapshot = {
            "eq": eq, "cr": cr, "mc": mc,
            "overall": overall_regime,
            "eq_pct": eq_bond[0],
            "bond_pct": eq_bond[1],
            "alloc_drivers": eq_bond[2],
            "btc_exposure": btc_exp,
            "spx_sizing": spx_sizing,
            "spx_lean": lean_text,
            "ibit_sizing": ibit_sizing,
        }

    def get_snapshot_data(self) -> dict | None:
        """Return the last computed snapshot for logging to SQLite."""
        return getattr(self, "_last_snapshot", None)

    # ── Header ────────────────────────────────────────────────────────────────

    def _update_header(self, eq, cr, mc):
        vote = _regime_vote(eq["regime"]) + _regime_vote(cr["regime"]) + _regime_vote(mc["regime"])
        if vote >= 2:    overall, oc = RISK_ON,  REGIME_COLORS[RISK_ON]
        elif vote <= -2: overall, oc = RISK_OFF, REGIME_COLORS[RISK_OFF]
        else:            overall, oc = NEUTRAL,  REGIME_COLORS[NEUTRAL]
        self.lbl_overall.setText(f"Overall: {overall}  ({vote:+d}/3)")
        self.lbl_overall.setStyleSheet(f"color: {oc}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        for lbl, rd, prefix in ((self.lbl_eq_badge, eq, "EQ"), (self.lbl_cr_badge, cr, "BTC"), (self.lbl_mc_badge, mc, "MACRO")):
            lbl.setText(f"{prefix}: {rd['regime']}")
            lbl.setStyleSheet(f"color: {rd['color']}; font-size: {fs(13)}px; font-weight: bold; border: none;")

    # ── Passive ETF Allocation ────────────────────────────────────────────────

    def _update_passive_etf_card(self, eq, mc, vix, vix_pctile):
        move      = self._macro_data.get("move")
        hy_spread = self._macro_data.get("hy_spread")
        eq_score  = eq.get("score", 0)
        mc_score  = mc.get("score", 0)

        eq_pct, bond_pct, _ = _equity_bond_split(
            eq_score, mc_score, vix, vix_pctile, move, hy_spread,
            self._macro_data.get("yield_spread"),
            self._macro_data.get("real_yield_10y"),
            self._macro_data.get("breakeven_5y"),
        )

        eq_color = COLORS["risk_on"] if eq_pct >= 75 else (COLORS["neutral"] if eq_pct >= 60 else COLORS["risk_off"])
        self.lbl_deployed.setText(f"{eq_pct}% deployed")
        self.lbl_deployed.setStyleSheet(
            f"color: {eq_color}; font-size: {fs(36)}px; font-weight: bold; border: none;")
        self.bar_eq_bond.setValue(eq_pct)
        self.bar_eq_bond.setStyleSheet(_bar_style(eq_color))

        self.lbl_passive_eq_val.setText(f"{eq_pct}%")
        self.lbl_passive_bond_val.setText(f"{bond_pct}%")
        self.lbl_alloc_target.setText(f"{eq_pct} / {bond_pct}")

        chips = []
        eq_dir = "up" if eq_score > 0 else ("down" if eq_score < 0 else "neutral")
        chips.append(("EQ REGIME", f"{eq_score:+d}", eq_dir))
        mc_dir = "up" if mc_score > 0 else ("down" if mc_score < 0 else "neutral")
        chips.append(("MACRO", f"{mc_score:+d}", mc_dir))
        if move is not None:
            mv_dir = "down" if move > 130 else ("up" if move < 80 else "neutral")
            chips.append(("MOVE", f"{move:.0f}", mv_dir))
        if hy_spread is not None:
            hy_dir = "down" if hy_spread > 5 else ("up" if hy_spread < 3 else "neutral")
            chips.append(("HY OAS", f"{hy_spread:.1f}%", hy_dir))
        self._set_chips(self._alloc_chips_lay, chips)

    # ── Bitcoin / IBIT ────────────────────────────────────────────────────────

    def _update_btc_ibit_card(self, cr):
        # Live halving data → clock widget
        h_progress    = self._crypto_data.get("halving_progress")
        h_days_in     = self._crypto_data.get("halving_days_in")
        h_days_left   = self._crypto_data.get("halving_days_remaining")
        h_blocks_left = self._crypto_data.get("halving_blocks_remaining", 0)
        if h_progress is not None and h_days_in is not None and h_days_left is not None:
            self.cycle_clock.update_live(h_days_in, h_days_left, h_progress,
                                         blocks_left=h_blocks_left)

        cr_score   = cr.get("score", 0)
        exposure   = _btc_exposure(cr_score)
        color      = _exposure_color(exposure)
        cyc_action = self.cycle_clock.get_action()
        cyc_phase  = self.cycle_clock.get_phase()
        week_in    = (h_days_in or 0) // 7

        self.lbl_btc_regime.setText(f"CRYPTO: {cr['regime']}  ({cr_score:+d})  ·  {cyc_action}")
        self.lbl_btc_regime.setStyleSheet(
            f"color: {cr['color']}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        self.lbl_btc_pct.setText(f"{exposure}%")
        self.lbl_btc_pct.setStyleSheet(
            f"color: {color}; font-size: {fs(38)}px; font-weight: bold; border: none;")
        self.bar_btc.setValue(exposure); self.bar_btc.setStyleSheet(_bar_style(color))

        # Description: regime + cycle context
        regime_str = cr['regime'].lower().replace("risk-", "risk ")
        self.lbl_btc_desc.setText(
            f"{regime_str.capitalize()} regime · post-halving wk {week_in}.  {cyc_action}.")

        # IBIT core + overlay recs
        self.lbl_ibit_core_val.setText(f"{exposure}%")
        btc_rv30   = self._crypto_data.get("btc_rv30")
        ibit_price = self._crypto_data.get("ibit_price")
        recs = _ibit_strategy_recs(cr_score, ibit_price, btc_rv30)
        self.lbl_ibit_cc.setText(recs["cc_action"])
        self.lbl_ibit_cc.setStyleSheet(
            f"color: {recs['cc_color']}; font-size: {fs(13)}px; border: none;")
        self.lbl_ibit_csp.setText(recs["csp_action"])
        self.lbl_ibit_csp.setStyleSheet(
            f"color: {recs['csp_color']}; font-size: {fs(13)}px; border: none;")

        # Cycle phase line
        self.lbl_cycle_phase_info.setText(
            f"CYCLE PHASE  {cyc_phase}  ·  wk {week_in} / 208")

        # Chips
        cr_dir = "up" if cr_score > 0 else ("down" if cr_score < 0 else "neutral")
        chips = [("CRYPTO", f"{cr_score:+d}", cr_dir)]
        fg = self._crypto_data.get("fear_greed")
        if fg is not None:
            fg_dir = "up" if fg > 65 else ("down" if fg < 35 else "neutral")
            chips.append(("F&G", f"{fg:.0f}", fg_dir))
        pct_200 = self._crypto_data.get("btc_pct_from_200ma")
        if pct_200 is not None:
            chips.append(("200D MA", f"{pct_200:+.0f}%", "up" if pct_200 > 0 else "down"))
        if btc_rv30 is not None:
            chips.append(("RV30", f"{btc_rv30:.0f}%", "muted"))
        ath_pct = self._crypto_data.get("btc_pct_from_ath")
        if ath_pct is not None:
            chips.append(("ATH DIST", f"{ath_pct:.0f}%",
                          "up" if ath_pct > -10 else ("neutral" if ath_pct > -30 else "down")))
        self._set_chips(self._btc_ibit_chips_lay, chips)

    # ── SPX Premium ───────────────────────────────────────────────────────────

    def _update_spx_card(self, eq_data, eq_regime, mc_regime, vix_pctile, ivr=None):
        vix = eq_data.get("vix")
        sizing, sizing_label = _premium_sizing(vix_pctile, eq_regime["regime"])

        lean_text, naked_rec, lean_color = _spx_directional_lean(
            eq_regime["regime"], eq_regime.get("score", 0), mc_regime["regime"])
        self.lbl_spx_lean.setText(lean_text)
        self.lbl_spx_lean.setStyleSheet(f"color: {lean_color}; font-size: {fs(14)}px; font-weight: bold; border: none;")
        self.lbl_spx_naked.setText(naked_rec)

        if vix is not None:
            self.lbl_vix_val.setText(f"VIX: {vix:.1f}")
        if vix_pctile is not None:
            if vix_pctile >= 60:    pc = COLORS["risk_on"]
            elif vix_pctile < 30:   pc = COLORS["risk_off"]
            else:                   pc = COLORS["neutral"]
            ivr_str = f"  ·  IVR: {ivr:.0f}%" if ivr is not None else ""
            self.lbl_vix_pctile.setText(f"Pctile: {vix_pctile:.0f}%{ivr_str}")
            self.lbl_vix_pctile.setStyleSheet(f"color: {pc}; font-size: {fs(14)}px; border: none;")
            self.bar_vix.setValue(int(vix_pctile)); self.bar_vix.setStyleSheet(_bar_style(pc))

        sizing_color = _exposure_color(int(sizing * 100))
        self.lbl_sizing.setText(f"{sizing:.2f}×")
        self.lbl_sizing.setStyleSheet(f"color: {sizing_color}; font-size: {fs(38)}px; font-weight: bold; border: none;")
        self.lbl_sizing_desc.setText(sizing_label)

        spx_hist = eq_data.get("spx_hist")
        if vix is not None and spx_hist is not None and len(spx_hist) >= 22:
            rv_ann = float(spx_hist.pct_change().dropna().tail(21).std() * np.sqrt(252) * 100)
            iv_rv = vix - rv_ann
            if iv_rv > 3:      iv_c, iv_label = COLORS["risk_on"], "premium rich"
            elif iv_rv < -3:   iv_c, iv_label = COLORS["risk_off"], "premium cheap"
            else:              iv_c, iv_label = COLORS["neutral"], "fairly priced"
            self.lbl_iv_rv.setText(f"IV/RV Spread: {iv_rv:+.1f}pp  ({iv_label})")
            self.lbl_iv_rv.setStyleSheet(f"color: {iv_c}; font-size: {fs(13)}px; border: none;")

        spx = eq_data.get("spx")
        if spx is not None and vix is not None:
            daily_sigma = spx * vix / 100 / np.sqrt(252)
            ev1w = daily_sigma * np.sqrt(5); ev1m = daily_sigma * np.sqrt(21)
            self.lbl_ev1w.setText(f"1-Week:   ±{ev1w:,.0f} pts  (±{ev1w / spx * 100:.1f}%)")
            self.lbl_ev1m.setText(f"1-Month:  ±{ev1m:,.0f} pts  (±{ev1m / spx * 100:.1f}%)")

        recs = _strategy_recs(vix, eq_regime["regime"])
        for tenor, text, color in recs:
            lbl = self._strat_lbls[tenor]; lbl.setText(text)
            lbl.setStyleSheet(f"color: {color}; font-size: {fs(14)}px; border: none;")

        chips = []
        if vix is not None:
            vx_dir = "down" if vix >= 25 else ("up" if vix < 15 else "neutral")
            chips.append(("VIX", f"{vix:.1f}", vx_dir))
        if vix_pctile is not None:
            vp_dir = "up" if vix_pctile >= 60 else ("down" if vix_pctile < 30 else "neutral")
            chips.append(("PCT", f"{vix_pctile:.0f}", vp_dir))
        if ivr is not None:
            chips.append(("IVR", f"{ivr:.0f}%", "muted"))
        sz_dir = "up" if sizing >= 0.75 else ("down" if sizing < 0.4 else "neutral")
        chips.append(("SIZE", f"{sizing:.2f}×", sz_dir))
        lean_dir = "up" if "naked" in lean_text.lower() or "put" in lean_text.lower() else "neutral"
        chips.append(("LEAN", lean_text.split()[0].upper() if lean_text else "—", lean_dir))
        self._set_chips(self._spx_chips_lay, chips)

