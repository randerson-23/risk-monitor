from PyQt6.QtCore import QThread, pyqtSignal
from data_fetch import fetch_equity_data, fetch_crypto_data


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
