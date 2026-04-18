import sys

import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication

from main_window import MainWindow
from theme import TOKENS, app_qss, load_fonts, ui_font

# Apply pyqtgraph dark theme once, globally
pg.setConfigOption("background", TOKENS["bg"])
pg.setConfigOption("foreground", TOKENS["text_secondary"])
pg.setConfigOption("antialias", True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Risk Monitor")
    app.setOrganizationName("RiskMonitor")

    load_fonts()
    app.setFont(ui_font(11))
    app.setStyleSheet(app_qss())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
