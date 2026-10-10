"""Run the same UI checks used inside the frozen executable."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "windows" if "--native" in sys.argv else "offscreen"
from PySide6.QtWidgets import QApplication
from app.storage import Storage
from app.ui.theme import apply_theme
from app.ui.verification import verify_ui
from app.ui.window import MainWindow

application = QApplication([])
apply_theme(application)
window = MainWindow(Storage(ROOT / "artifacts" / "updated-ui-review"))
if "--native" in sys.argv:
    window.setWindowOpacity(0)  # Exercise the real HWND without taking the screen.
window.show()
application.processEvents()
try:
    result = verify_ui(window)
    (ROOT / "artifacts" / ("updated-ui-native.json" if "--native" in sys.argv else "updated-ui-checks.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
finally:
    window.queue.tasks.clear()
    window.close()
