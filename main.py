import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from configdiff.gui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ConfigDiff")
    app.setQuitOnLastWindowClosed(True)
    icon_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    app.setWindowIcon(QIcon(str(icon_root / "assets" / "ConfigDiff-icon.png")))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
