import sys

import pyqtgraph as pg
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from main_window import MainWindow

# Apply pyqtgraph dark theme once, globally
pg.setConfigOption("background", "#0d1117")
pg.setConfigOption("foreground", "#8b949e")
pg.setConfigOption("antialias", True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Risk Monitor")
    app.setFont(QFont("Segoe UI", 10))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
