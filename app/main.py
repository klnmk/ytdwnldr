from __future__ import annotations

import logging
import sys


def run() -> int:
    if "--verify-startup" in sys.argv:
        from pathlib import Path
        root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "startup-stage.txt").write_text("importing Qt", encoding="utf-8")
    from PySide6.QtCore import QTimer, QTranslator
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.domain import UserError
    from app.storage import Storage, asset_root
    from app.ui.theme import apply_theme
    from app.ui.window import MainWindow

    application = QApplication(sys.argv)
    if "--verify-startup" in sys.argv:
        (root / "data" / "startup-stage.txt").write_text("Qt initialized", encoding="utf-8")
    application.setApplicationName("СЪЁМ")
    application.setOrganizationName("СЪЁМ")
    apply_theme(application)
    translator = QTranslator(application)
    translator.load(str(asset_root() / "translations" / "qtbase_ru.qm"))
    application.installTranslator(translator)
    try:
        storage = Storage()
        storage.configure_logging()
        window = MainWindow(storage)
    except UserError as exc:
        QMessageBox.critical(None, "Не удалось запустить СЪЁМ", str(exc))
        return 1

    def exception_hook(kind, value, traceback):
        logging.error("Unexpected interface error", exc_info=(kind, value, traceback))
        window.show_error("Ошибка приложения. Подробности сохранены в журнале.")

    sys.excepthook = exception_hook
    window.show()
    if "--verify-startup" in sys.argv:
        (root / "data" / "startup-stage.txt").write_text("window shown", encoding="utf-8")
    if "--verify-startup" in sys.argv:
        # Offline packaging check: render the real empty window and exit cleanly.
        def verified():
            window.grab().save(str(storage.data / "startup-verification.png"))
            (storage.data / "startup-ready.txt").write_text("ready", encoding="utf-8")
        QTimer.singleShot(100, verified)
        QTimer.singleShot(8000, window.close)
    return application.exec()
