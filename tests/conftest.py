import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def root():
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def qt():
    from PySide6.QtWidgets import QApplication
    from app.ui.theme import apply_theme
    application = QApplication.instance() or QApplication([])
    apply_theme(application)
    return application
