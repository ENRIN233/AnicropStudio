# -*- coding: utf-8 -*-
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from ui import MainWindow


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"CRITICAL UNCAUGHT EXCEPTION:\n{error_msg}", file=sys.stderr)


def main():
    sys.excepthook = handle_exception

    app = QApplication(sys.argv)
    app.setApplicationName("AnicropStudio")
    app.setOrganizationName("AnicropGeeks")

    window = MainWindow()
    window.show()

    # 首次启动才播 splash
    settings = QSettings("AnicropGeeks", "AnicropStudio")
    has_seen = settings.value("has_seen_splash", False, type=bool)
    if not has_seen:
        settings.setValue("has_seen_splash", True)
        window.start_boot_splash()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()