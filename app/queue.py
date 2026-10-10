from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from app.domain import ACTIVE, TERMINAL, State, Task, UserError
from app.process import ManagedProcess
from app.storage import Storage


class DownloadQueue(QObject):
    changed = Signal()
    updated = Signal(str)
    error = Signal(str)

    def __init__(self, storage: Storage, parallel: int = 2, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.parallel = parallel
        self.tasks = storage.load_history()
        self.running: dict[str, ManagedProcess] = {}
        self.closing = False
        self.persist_timer = QTimer(self)
        self.persist_timer.setSingleShot(True)
        self.persist_timer.setInterval(300)
        self.persist_timer.timeout.connect(self.persist)

    def add(self, tasks: list[Task]) -> tuple[int, int]:
        keys = {t.duplicate_key for t in self.tasks if t.state in ACTIVE or t.state == State.WAITING}
        added = 0
        for task in tasks:
            if task.duplicate_key not in keys:
                self.tasks.append(task)
                keys.add(task.duplicate_key)
                added += 1
        self.changed.emit()
        self.persist_timer.start()
        QTimer.singleShot(0, self.pump)
        return added, len(tasks) - added

    def pump(self):
        if self.closing:
            return
        for task in self.tasks:
            if len(self.running) >= self.parallel:
                break
            if task.state != State.WAITING:
                continue
            task.state = State.METADATA
            try:
                process = ManagedProcess(self.storage.root, {"kind": "download", "task": task.to_dict()}, self)
            except OSError:
                task.state = State.FAILED
                task.error = "Не удалось создать рабочий файл. Проверьте доступ к папке приложения."
                self.updated.emit(task.id)
                continue
            self.running[task.id] = process
            process.event.connect(lambda event, t=task: self.handle_event(t, event))
            process.done.connect(lambda code, t=task: self.finished(t, code))
            process.start()
            self.updated.emit(task.id)
        self.persist_timer.start()

    def handle_event(self, task: Task, event: dict):
        if task.state == State.CANCELLED or not self.contains(task):
            return
        kind = event["event"]
        if kind == "state":
            task.state = State(event["state"])
            task.progress = -1 if task.state in {State.MERGING, State.CONVERTING} else 0
            task.speed, task.eta = 0, None
            task.note = event.get("note", "")
            if task.state == State.DOWNLOADING:
                task.downloaded_bytes, task.total_bytes, task.total_estimated, task.stream_label = 0, None, False, ""
        elif kind == "progress":
            task.progress = event.get("progress", -1)
            task.speed = event.get("speed", 0)
            task.eta = event.get("eta")
            if "downloaded_bytes" in event:
                task.downloaded_bytes = event["downloaded_bytes"]
                task.total_bytes = event.get("total_bytes")
                task.total_estimated = event.get("total_estimated", False)
                task.stream_label = event.get("stream_label", "Поток")
        elif kind == "completed":
            task.path = event["path"]
            task.note = event.get("note", "")
            # Completion becomes visible only after the worker exits successfully.
        elif kind == "error":
            task.state, task.error = State.FAILED, event["message"]
        elif kind == "note":
            task.note = event.get("note", "")
        self.updated.emit(task.id)

    def finished(self, task: Task, code: int):
        process = self.running.pop(task.id, None)
        if not self.contains(task):
            if process:
                process.deleteLater()
            QTimer.singleShot(0, self.pump)
            return
        if task.state != State.CANCELLED:
            if code == 0 and task.path:
                task.state, task.progress = State.COMPLETED, 100
                try:
                    task.final_size = Path(task.path).stat().st_size
                except OSError:
                    task.final_size = None
            else:
                task.state = State.FAILED
                task.error = task.error or "Рабочий процесс завершился без результата. Подробности в журнале."
        task.speed, task.eta = 0, None
        self.updated.emit(task.id)
        self.persist_timer.start()
        if process:
            process.deleteLater()
        QTimer.singleShot(0, self.pump)

    def cancel(self, task: Task):
        if task.state in TERMINAL or not self.contains(task):
            return
        task.state, task.note = State.CANCELLED, "Можно продолжить кнопкой «Повторить»."
        if task.id in self.running:
            self.running[task.id].cancel()
        self.updated.emit(task.id)
        self.persist_timer.start()

    def retry(self, task: Task):
        if task.state not in {State.FAILED, State.CANCELLED} or task.id in self.running or not self.contains(task):
            return
        task.state, task.progress, task.error, task.path, task.note = State.WAITING, 0, "", "", ""
        task.downloaded_bytes, task.total_bytes, task.total_estimated, task.stream_label, task.final_size = 0, None, False, "", None
        self.updated.emit(task.id)
        QTimer.singleShot(0, self.pump)

    def retry_failed(self):
        for task in self.tasks:
            if task.state == State.FAILED:
                self.retry(task)

    def clear_finished(self):
        self.tasks = [t for t in self.tasks if t.state != State.COMPLETED]
        self.changed.emit()
        self.persist()

    def contains(self, task: Task) -> bool:
        return any(item is task for item in self.tasks)

    def remove(self, task: Task):
        if not self.contains(task):
            return
        # Cancel before hiding the entry; cancelled tasks ignore late events.
        if task.state not in TERMINAL:
            task.state, task.note = State.CANCELLED, "Убрано из очереди."
        if process := self.running.get(task.id):
            process.cancel()
        self.tasks = [item for item in self.tasks if item is not task]
        self.changed.emit()
        self.persist()

    def clear(self):
        # Mark every pending job before cancelling workers. No callback can
        # start an item that is about to be removed during this operation.
        for task in self.tasks:
            if task.state not in TERMINAL:
                task.state = State.CANCELLED
        for process in list(self.running.values()):
            process.cancel()
        self.tasks.clear()
        self.changed.emit()
        self.persist()

    def persist(self):
        try:
            self.storage.save_history(self.tasks)
        except UserError as exc:
            logging.exception("History could not be saved")
            self.error.emit(str(exc))

    def shutdown(self):
        self.closing = True
        for task in self.tasks:
            if task.state in ACTIVE or task.state == State.WAITING:
                task.state = State.CANCELLED
        for process in list(self.running.values()):
            process.shutdown()
        self.persist_timer.stop()
        self.persist()
