"""Exercise actual source UI + QProcess downloads and measure event-loop delays."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.domain import TERMINAL, State
from app.storage import Storage
from app.ui.theme import apply_theme
from app.ui.window import MainWindow


def main():
    application = QApplication([])
    apply_theme(application)
    storage = Storage(ROOT)
    backups = {name: (storage.data / name).read_bytes() if (storage.data / name).exists() else None for name in ("settings.json", "history.json")}
    window = MainWindow(storage)
    original_tasks = window.queue.tasks.copy()
    window.queue.tasks.clear()
    window.prefs.folder = "artifacts/live-queue"
    window.prefs.output = "mp3"
    window.prefs.bitrate = 192
    window.audio_mode.setChecked(True)
    window.change_mode(False)
    window.show()
    window.link.setText("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    window.add_links()
    samples = []
    previous = time.perf_counter()
    start = previous
    result = {}
    requested = False

    def tick():
        nonlocal previous, requested
        now = time.perf_counter()
        samples.append(now - previous)
        previous = now
        if window.current_collection() and not requested:
            requested = True
            window.start_download()
        if window.queue.tasks and all(t.state in TERMINAL for t in window.queue.tasks) and not window.queue.running:
            result.update({"seconds": round(now - start, 2), "max_event_loop_gap_seconds": round(max(samples), 3), "states": [t.state.value for t in window.queue.tasks], "errors": [t.error for t in window.queue.tasks if t.error], "paths": [t.path for t in window.queue.tasks]})
            window.grab().save(str(ROOT / "artifacts" / "ui-live-download.png"))
            window.queue.tasks = original_tasks
            window.close()
        elif now - start > 180:
            result.update({"error": "Live queue timeout", "message": window.message.text()})
            window.close()

    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(tick)
    timer.start()
    try:
        application.exec()
    finally:
        for name, content in backups.items():
            target = storage.data / name
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
    (ROOT / "artifacts" / "queue-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True), flush=True)
    assert result.get("states") == [State.COMPLETED.value], "Live Qt queue failed"


if __name__ == "__main__":
    main()
