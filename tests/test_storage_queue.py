import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from app.domain import Preferences, State, Task, UserError
from app.queue import DownloadQueue
from app.storage import Storage
from app.ui.widgets import PlaylistModel


def test_settings_round_trip(tmp_path):
    storage = Storage(tmp_path)
    prefs = Preferences(output="mp3", bitrate=320, parallel=3, folder="downloads/Музыка")
    storage.save_preferences(prefs)
    assert Storage(tmp_path).load_preferences() == prefs
    assert storage.folder(prefs.folder) == tmp_path / "downloads" / "Музыка"
    assert storage.folder_value(str(tmp_path / "downloads")) == "downloads"


def test_broken_settings_preserved(tmp_path):
    storage = Storage(tmp_path)
    (storage.data / "settings.json").write_text("{broken", encoding="utf-8")
    assert storage.load_preferences() == Preferences()
    assert (storage.data / "settings.damaged.json").exists()


def test_invalid_history_rows_are_skipped(tmp_path):
    storage = Storage(tmp_path)
    storage.write("history.json", ["broken", None, {"nonsense": "value"}])
    assert storage.load_history() == []


def test_all_waiting_playlist_items_are_persisted(tmp_path):
    storage = Storage(tmp_path)
    tasks = [Task(f"url{i}", f"Видео {i}", {}, "downloads") for i in range(800)]
    storage.save_history(tasks)
    recovered = storage.load_history()
    assert len(recovered) == 800 and all(t.state == State.CANCELLED for t in recovered)


def test_history_moves_with_portable_folder(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    storage = Storage(first)
    task = Task("url", "Музыка", {}, str(first / "downloads"), path=str(first / "downloads" / "Музыка.mp3"), state=State.COMPLETED)
    storage.save_history([task])
    row = json.loads((storage.data / "history.json").read_text(encoding="utf-8"))[0]
    assert not Path(row["path"]).is_absolute()
    import shutil
    shutil.copytree(first, second)
    recovered = Storage(second).load_history()[0]
    assert recovered.path == str(second / "downloads" / "Музыка.mp3")


def test_read_only_directory_error(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise PermissionError
    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(UserError, match="недоступна для записи"):
        Storage(tmp_path)


class FakeProcess(QObject):
    event = Signal(dict)
    done = Signal(int)

    def __init__(self, root, job, parent=None):
        super().__init__(parent)
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def shutdown(self):
        self.cancel()
        self.done.emit(1)


@pytest.fixture
def queue(qt, tmp_path, monkeypatch):
    monkeypatch.setattr("app.queue.ManagedProcess", FakeProcess)
    manager = DownloadQueue(Storage(tmp_path))
    yield manager
    manager.shutdown()
    qt.processEvents()


def make_task(number=1):
    return Task(f"url{number}", f"title{number}", {"output": "mp3", "bitrate": 192}, "folder")


def test_duplicate_detection(queue):
    assert queue.add([make_task(), make_task()]) == (1, 1)
    assert queue.add([make_task()]) == (0, 1)
    task = make_task()
    task.options["bitrate"] = 320
    assert queue.add([task]) == (1, 0)


def test_parallelism_and_completion(queue):
    tasks = [make_task(i) for i in range(4)]
    queue.add(tasks)
    queue.pump()
    assert len(queue.running) == 2
    assert tasks[2].state == State.WAITING
    queue.handle_event(tasks[0], {"event": "completed", "path": "media.mp3"})
    assert tasks[0].state != State.COMPLETED
    queue.finished(tasks[0], 0)
    assert tasks[0].state == State.COMPLETED
    queue.pump()
    assert tasks[2].state == State.METADATA and len(queue.running) == 2


def test_cancel_and_retry(queue):
    task = make_task()
    queue.add([task])
    queue.pump()
    process = queue.running[task.id]
    queue.cancel(task)
    assert task.state == State.CANCELLED and process.cancelled
    queue.handle_event(task, {"event": "completed", "path": "wrong.mp3"})
    queue.finished(task, 1)
    assert task.state == State.CANCELLED and not task.path
    queue.retry(task)
    assert task.state == State.WAITING


def test_cancel_waiting(queue):
    task = make_task()
    queue.add([task])
    queue.cancel(task)
    queue.pump()
    assert task.state == State.CANCELLED and not queue.running


def test_failed_worker_does_not_finish(queue):
    task = make_task()
    queue.add([task])
    queue.pump()
    queue.handle_event(task, {"event": "completed", "path": "media.mp3"})
    queue.finished(task, 1)
    assert task.state == State.FAILED
    queue.retry_failed()
    assert task.state == State.WAITING


def test_large_playlist_selection(qt):
    model = PlaylistModel()
    entries = [{"title": f"Видео {i}", "index": i + 1, "unavailable": i % 10 == 0} for i in range(10000)]
    model.set_entries(entries)
    assert model.rowCount() == 10000 and len(model.selected) == 9000
    model.select_all(False)
    assert not model.selected
    model.select_all(True)
    assert len(model.selected_entries()) == 9000


@pytest.mark.parametrize("state", [State.FAILED, State.COMPLETED, State.CANCELLED, State.WAITING])
def test_remove_persists_without_deleting_media(queue, tmp_path, state):
    media = tmp_path / "keep.mp3"
    media.write_bytes(b"existing media")
    task = make_task()
    task.state, task.path = state, str(media)
    queue.tasks.append(task)
    queue.remove(task)
    assert not queue.tasks and not queue.storage.load_history()
    assert media.read_bytes() == b"existing media"
    queue.retry(task)
    queue.pump()
    assert not queue.running


def test_removed_pending_job_never_starts(queue):
    queue.parallel = 1
    tasks = [make_task(i) for i in range(3)]
    queue.add(tasks)
    queue.pump()
    queue.remove(tasks[1])
    queue.finished(tasks[0], 1)
    queue.pump()
    assert tasks[1].id not in queue.running and tasks[1] not in queue.tasks
    assert list(queue.running) == [tasks[2].id]


@pytest.mark.parametrize("state", [State.DOWNLOADING, State.CONVERTING])
def test_remove_active_ignores_late_worker_events(queue, state):
    task = make_task()
    queue.add([task])
    queue.pump()
    task.state = state
    process = queue.running[task.id]
    queue.remove(task)
    assert process.cancelled and not queue.tasks
    process.event.emit({"event": "state", "state": State.DOWNLOADING.value})
    process.event.emit({"event": "completed", "path": "late.mp3"})
    process.done.emit(0)
    assert not queue.running and not queue.tasks and not queue.storage.load_history()
    assert not task.path


def test_clear_mixed_queue_cancels_workers_and_keeps_files(queue, tmp_path):
    tasks = [make_task(i) for i in range(6)]
    queue.add(tasks)
    queue.pump()
    tasks[3].state = State.FAILED
    tasks[4].state = State.COMPLETED
    tasks[5].state = State.CANCELLED
    media = tmp_path / "done.mp4"
    media.write_bytes(b"finished")
    tasks[4].path = str(media)
    processes = list(queue.running.values())
    queue.clear()
    assert all(process.cancelled for process in processes)
    for process in processes:
        process.done.emit(1)
    queue.pump()
    assert not queue.tasks and not queue.running and not queue.storage.load_history()
    assert media.read_bytes() == b"finished"


def test_completed_size_is_read_from_output_not_source(queue, tmp_path):
    media = tmp_path / "converted.mp3"
    media.write_bytes(b"x" * 1234)
    task = make_task()
    queue.add([task])
    queue.pump()
    queue.handle_event(task, {"event": "progress", "downloaded_bytes": 1000000, "total_bytes": 2000000, "stream_label": "Звук", "progress": 50})
    queue.handle_event(task, {"event": "completed", "path": str(media), "final_size": 999999})
    queue.finished(task, 0)
    assert task.final_size == 1234
    queue.persist()
    assert queue.storage.load_history()[0].final_size == 1234
    task.state = State.CANCELLED
    queue.retry(task)
    assert task.final_size is None and task.downloaded_bytes == 0 and task.total_bytes is None


def test_stream_transition_and_processing_keep_source_size_distinct(queue):
    task = make_task()
    queue.add([task])
    queue.pump()
    queue.handle_event(task, {"event": "progress", "progress": 90, "downloaded_bytes": 9000, "total_bytes": 10000, "stream_label": "Видео"})
    queue.handle_event(task, {"event": "progress", "progress": 20, "downloaded_bytes": 200, "total_bytes": 1000, "total_estimated": True, "stream_label": "Звук"})
    assert task.downloaded_bytes == 200 and task.total_bytes == 1000 and task.total_estimated
    queue.handle_event(task, {"event": "state", "state": State.MERGING.value})
    assert task.downloaded_bytes == 200 and task.final_size is None
    queue.handle_event(task, {"event": "state", "state": State.DOWNLOADING.value})
    assert task.downloaded_bytes == 0 and not task.stream_label and task.total_bytes is None
