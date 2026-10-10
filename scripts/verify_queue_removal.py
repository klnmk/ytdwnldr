"""Cancel real source QProcess downloads in an isolated portable directory."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from app.domain import State, Task
from app.storage import Storage
from app.ui.theme import apply_theme
from app.ui.window import MainWindow


def main():
    application = QApplication([])
    apply_theme(application)
    root = ROOT / "artifacts" / "queue-removal-review"
    binaries = root / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        destination = binaries / name
        if not destination.exists():
            destination.hardlink_to(ROOT / "bin" / name)
    storage = Storage(root)
    # ManagedProcess locates main.py relative to its portable root. Delegate to
    # the real source entry point while keeping all test data in this root.
    (root / "main.py").write_text("import runpy, sys\nsys.path.insert(0, " + repr(str(ROOT)) + ")\nrunpy.run_path(" + repr(str(ROOT / "main.py")) + ", run_name='__main__')\n", encoding="utf-8")
    window = MainWindow(storage)
    window.queue.clear()
    window.queue.parallel = 1
    window.show()
    started = time.monotonic()
    phase = 0
    result = {"worker_pids": [], "child_pids": [], "confirmations": []}
    video_url = "https://www.youtube.com/watch?v=YE7VzlLtp-4"

    def tasks():
        return [Task(video_url, "Отмена реального видео", {"output": "mp4", "height": 1080, "compatible": True}, str(root / "downloads")), Task("https://www.youtube.com/watch?v=jNQXAC9IVRw", "Удаление ожидающего аудио", {"output": "mp3", "bitrate": 192}, str(root / "downloads"))]

    current = tasks()
    window.queue.add(current)
    original_question = QMessageBox.question

    def confirm(*arguments):
        result["confirmations"].append(arguments[2])
        return QMessageBox.StandardButton.Yes

    def record_processes():
        for process in window.queue.running.values():
            pid = int(process.process.processId())
            if pid:
                result["worker_pids"].append(pid)
                try:
                    result["child_pids"].extend(child.pid for child in psutil.Process(pid).children(recursive=True))
                except psutil.NoSuchProcess:
                    pass

    def tick():
        nonlocal phase, current
        try:
            if phase in (0, 2) and any(task.state == State.FAILED for task in current):
                raise RuntimeError("A live verification job failed: " + "; ".join(task.error for task in current if task.error))
            if time.monotonic() - started > 120:
                raise RuntimeError("Real removal verification timed out")
            if phase == 0 and current[0].state == State.DOWNLOADING and current[0].downloaded_bytes > 0:
                assert current[1].state == State.WAITING
                result["downloaded_before_remove"] = current[0].downloaded_bytes
                record_processes()
                window.remove_queue_item(current[1].id)
                window.remove_queue_item(current[0].id)
                assert not window.queue.tasks
                phase = 1
            elif phase == 1 and not window.queue.running:
                assert not storage.load_history()
                current = tasks()
                window.queue.parallel = 2
                window.queue.add(current)
                phase = 2
            elif phase == 2 and any(task.state == State.DOWNLOADING and task.downloaded_bytes > 0 for task in current):
                record_processes()
                QMessageBox.question = confirm
                window.clear_queue()
                assert not window.queue.tasks
                phase = 3
            elif phase == 3 and not window.queue.running:
                tracked = result["worker_pids"] + result["child_pids"]
                assert all(not psutil.pid_exists(pid) for pid in tracked)
                assert not storage.load_history()
                result.update({"passed": True, "seconds": round(time.monotonic() - started, 2), "no_orphan_processes": True, "pending_never_started": True, "persisted_queue_empty": True})
                window.close()
        except Exception as exc:
            result["error"] = str(exc)
            window.close()

    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(tick)
    timer.start()
    try:
        application.exec()
    finally:
        QMessageBox.question = original_question
    (ROOT / "artifacts" / "queue-removal-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    assert result.get("passed"), "Real queue removal failed; see queue-removal-results.json"


if __name__ == "__main__":
    main()
