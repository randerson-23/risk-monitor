import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal
from data_fetch import (fetch_crypto_data, fetch_equity_data, fetch_forward_risk_data,
                          fetch_macro_data, fetch_sector_data)
from forecasting import garch_vol_forecast


class EquityWorker(QThread):
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.data_ready.emit(fetch_equity_data())
        except Exception as exc:
            self.error.emit(str(exc))


class CryptoWorker(QThread):
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.data_ready.emit(fetch_crypto_data())
        except Exception as exc:
            self.error.emit(str(exc))


class MacroWorker(QThread):
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.data_ready.emit(fetch_macro_data())
        except Exception as exc:
            self.error.emit(str(exc))


class SectorWorker(QThread):
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.data_ready.emit(fetch_sector_data())
        except Exception as exc:
            self.error.emit(str(exc))


class MacroForwardWorker(QThread):
    """Forward-looking macro: NY Fed yield-curve probit, NFCI, recession prob."""
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.data_ready.emit(fetch_forward_risk_data())
        except Exception as exc:
            self.error.emit(str(exc))


class SentimentWorker(QThread):
    """Runs consumer sentiment analysis via Anthropic API with web search."""
    data_ready = pyqtSignal(dict)   # {response, sentiment_score, timestamp}
    error = pyqtSignal(str)

    def run(self):
        try:
            from ai_analysis import run_sentiment_analysis
            result = run_sentiment_analysis()
            self.data_ready.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class ForecastWorker(QThread):
    """CPU-bound GARCH fit; emits {'tag': 'spx', 'forecast': {...}}."""
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, tag: str, prices: pd.Series, horizon: int = 20, parent=None):
        super().__init__(parent)
        self._tag = tag
        self._prices = prices
        self._horizon = horizon

    def run(self):
        try:
            fc = garch_vol_forecast(self._prices, horizon=self._horizon)
            self.data_ready.emit({"tag": self._tag, "forecast": fc})
        except Exception as exc:
            self.error.emit(f"{self._tag}: {exc}")
