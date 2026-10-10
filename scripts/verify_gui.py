"""Render real Qt widgets with explicitly synthetic review data; never in release UI."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app.domain import State, Task
from app.storage import Storage
from app.ui.theme import apply_theme
from app.ui.window import MainWindow


def main():
    start = time.perf_counter()
    application = QApplication([])
    apply_theme(application)
    out = ROOT / "artifacts"
    out.mkdir(exist_ok=True)
    storage = Storage(out / "ui-review")
    # Review fixtures only: no real work or user's settings are modified.
    binaries = storage.root / "bin"
    binaries.mkdir(exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        (binaries / name).touch()
    window = MainWindow(storage)
    window.resize(1080, 850)
    window.show()
    application.processEvents()
    window.grab().save(str(out / "ui-empty.png"))
    startup = time.perf_counter() - start
    sample = {"event": "metadata", "title": "Ночные записи · тестовый плейлист", "channel": "Студия СЪЁМ", "playlist": True, "source_url": "https://www.youtube.com/playlist?list=PLsynthetic", "entries": [{"id": f"test{i}", "title": title, "url": f"https://youtube.com/watch?v=test{i}", "channel": "Студия СЪЁМ", "index": i + 1, "duration": 130 + i * 60, "qualities": [360, 720, 1080], "m4a": True, "unavailable": i == 3} for i, title in enumerate(["Сторона А — тёплый звук", "Поздний поезд", "Сеты после полуночи", "Недоступная запись", "Кассетные заметки"])]}
    window.collections.append(sample)
    window.collection_picker.addItem(sample["title"])
    window.show_collection(0)
    window.audio_mode.setChecked(True)
    window.change_mode(False)
    for i, state in enumerate((State.DOWNLOADING, State.CONVERTING, State.COMPLETED, State.FAILED)):
        task = Task(f"url{i}", sample["entries"][i]["title"], {"output": "mp3", "bitrate": 192}, str(ROOT / "downloads"), playlist=sample["title"], index=i + 1, state=state, progress=64 if i == 0 else -1, speed=2.8 * 1048576 if i == 0 else 0, eta=24 if i == 0 else None, error="Видео недоступно." if i == 3 else "")
        window.queue.tasks.append(task)
    window.queue_model.refresh()
    window.queue_summary()
    window.splitter.setSizes([365, 285])
    application.processEvents()
    window.grab().save(str(out / "ui-playlist.png"))
    window.resize(880, 780)
    application.processEvents()
    window.grab().save(str(out / "ui-compact.png"))
    before = time.perf_counter()
    window.playlist_model.set_entries([{**sample["entries"][0], "title": f"Видео {i}", "index": i + 1} for i in range(10000)])
    application.processEvents()
    duration = time.perf_counter() - before
    (out / "gui-metrics.json").write_text(json.dumps({"source_widget_startup_seconds": round(startup, 3), "10000_playlist_rows_and_paint_seconds": round(duration, 3), "synthetic_review_data": True}, indent=2), encoding="utf-8")
    window.queue.tasks.clear()
    window.close()
    print("Qt UI rendered; metrics:", (out / "gui-metrics.json").read_text())


if __name__ == "__main__":
    main()
