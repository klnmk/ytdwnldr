from PySide6.QtCore import QPoint, Qt

from app.domain import State, Task
from app.storage import Storage
from app.ui.window import MainWindow


def test_quality_is_not_silently_downgraded(qt, tmp_path):
    storage = Storage(tmp_path)
    (storage.root / "bin").mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        (storage.root / "bin" / name).touch()
    window = MainWindow(storage)
    window.prefs.height = 1080
    window.collections.append({"title": "Тест", "channel": "Канал", "playlist": False, "entries": [{"title": "Тест", "url": "url", "duration": 10, "qualities": [360, 720], "unavailable": False, "m4a": False}]})
    window.collection_picker.addItem("Тест")
    window.show_collection(0)
    assert window.quality.currentData() == 1080
    assert "недоступно" in window.quality.currentText() and not window.download.isEnabled()
    window.quality.setCurrentIndex(window.quality.findData(720))
    assert window.download.isEnabled()
    window.audio_mode.setChecked(True)
    window.change_mode(False)
    window.format.setCurrentIndex(window.format.findData("m4a"))
    assert not window.download.isEnabled()
    window.close()


def test_queue_row_actions_and_russian_layout(qt, tmp_path):
    storage = Storage(tmp_path)
    (storage.root / "bin").mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        (storage.root / "bin" / name).touch()
    window = MainWindow(storage)
    task = Task("url", "Файл", {"output": "mp3", "bitrate": 192}, str(tmp_path), state=State.FAILED, error="Ошибка сети")
    window.queue.tasks.append(task)
    window.queue_model.refresh()
    window.queue_summary()
    window.show()
    qt.processEvents()
    assert "СЪЁМ" in window.windowTitle()
    assert window.queue_stack.currentIndex() == 1
    assert window.retry_button.isEnabled()
    assert not window.grab().isNull()
    assert window.queue_view.viewport().height() >= 68
    for height in (752, 650, 520):
        window.resize(880, height)
        qt.processEvents()
        center, queue_panel = window.splitter.widget(0), window.splitter.widget(1)
        assert center.geometry().bottom() < queue_panel.geometry().top()
        assert center.height() >= center.minimumSizeHint().height()
        assert window.scroll.verticalScrollBar().maximum() > 0
        window.scroll.verticalScrollBar().setValue(window.scroll.verticalScrollBar().maximum())
        qt.processEvents()
        assert window.summary.mapTo(window, QPoint(0, 0)).y() + window.summary.height() <= window.height()
    window.close()
